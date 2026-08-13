import random
from collections import defaultdict
from datetime import datetime

from flask import redirect, render_template, request, session, url_for

from app.database import get_db, get_user_role, log_activity
from app.helper_common import externalize_data_uri_images, parse_module_names, pptx_to_content_slide_html, safe_int
from app.helper_theory import (
    clone_bank_question_to_test,
    merge_bank_match_rows_into_test,
    score_fill_in_answer,
    score_true_false_answer,
)

LESSON_SLIDE_TYPES = ("content_slide", "title_slide", "heading_slide")
QUESTION_BANK_SUPPORTED_TYPES = ("mcq_single", "true_false", "fill_in", "match")


def register_theory_runtime_routes(app):
    @app.route("/manage_tests/<int:test_id>/questions", methods=["GET", "POST"])
    def manage_test_questions(test_id):
        return _manage_theory_questions(test_id, "test")

    @app.route("/manage_lessons/<int:test_id>/questions", methods=["GET", "POST"])
    def manage_lesson_questions(test_id):
        return _manage_theory_questions(test_id, "lesson")

    def _manage_theory_questions(test_id, builder_mode):
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))
        if get_user_role(username) not in ["teacher", "admin"]:
            return "Access denied", 403

        conn = get_db()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT id, title, subject, background_image, COALESCE(background_fit, 'cover') FROM theory_tests WHERE id = ?",
            (test_id,),
        )
        test = cursor.fetchone()
        if not test:
            conn.close()
            return "Test not found", 404

        bank_selected_subject = (request.args.get("bank_subject") or "").strip()
        bank_selected_module = (request.args.get("bank_module") or "").strip()
        bank_selected_type = (request.args.get("bank_type") or "").strip()

        def load_bank_picker_data():
            cursor.execute("SELECT modules FROM question_bank_questions WHERE COALESCE(modules, '') != ''")
            bank_module_names = []
            for (modules_text,) in cursor.fetchall():
                bank_module_names.extend(parse_module_names(modules_text))
            bank_module_names = sorted({item for item in bank_module_names}, key=str.lower)

            cursor.execute("SELECT DISTINCT TRIM(subject) FROM question_bank_questions WHERE COALESCE(TRIM(subject), '') != '' ORDER BY LOWER(TRIM(subject))")
            bank_subject_names = [row[0] for row in cursor.fetchall() if row[0]]

            where_parts = []
            params = []
            if bank_selected_subject:
                where_parts.append("LOWER(COALESCE(subject, '')) = ?")
                params.append(bank_selected_subject.lower())
            if bank_selected_module:
                where_parts.append("LOWER(COALESCE(modules, '')) LIKE ?")
                params.append(f"%{bank_selected_module.lower()}%")
            if bank_selected_type and bank_selected_type in QUESTION_BANK_SUPPORTED_TYPES:
                where_parts.append("question_type = ?")
                params.append(bank_selected_type)
            where_clause = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
            cursor.execute(
                f"""
                SELECT id, question_text, question_type, marks, subject, modules
                FROM question_bank_questions
                {where_clause}
                ORDER BY id DESC
                LIMIT 200
                """,
                params,
            )
            raw_questions = cursor.fetchall()
            bank_questions = []
            for row in raw_questions:
                row = list(row)
                if row[2] == "match":
                    cursor.execute(
                        """
                        SELECT option_text, match_pair
                        FROM question_bank_options
                        WHERE bank_question_id = ?
                          AND COALESCE(match_pair, '') != ''
                        ORDER BY id
                        LIMIT 1
                        """,
                        (row[0],),
                    )
                    pair_row = cursor.fetchone()
                    if pair_row:
                        option_text, match_pair = pair_row
                        row[1] = f"{match_pair} -> {option_text}"
                bank_questions.append(tuple(row))
            return bank_subject_names, bank_module_names, bank_questions

        if request.method == "POST":
            action = request.form.get("action")
            if action == "add_question":
                q_text = request.form.get("question_text", "").strip()
                if builder_mode == "lesson":
                    q_text = externalize_data_uri_images(q_text)
                q_type = request.form.get("question_type", "")
                marks = int(request.form.get("marks", 1))
                source_modules = ", ".join(
                    parse_module_names(",".join(request.form.getlist("source_modules")) or request.form.get("source_modules") or "")
                )
                if q_type in LESSON_SLIDE_TYPES:
                    marks = 0

                cursor.execute("SELECT COUNT(*) FROM theory_questions WHERE test_id = ?", (test_id,))
                order_index = cursor.fetchone()[0]
                q_id = None
                if builder_mode != "lesson" and q_type == "match":
                    cursor.execute(
                        """
                        SELECT id, COALESCE(source_modules, '')
                        FROM theory_questions
                        WHERE test_id = ?
                          AND question_type = 'match'
                          AND LOWER(TRIM(question_text)) = LOWER(TRIM(?))
                        ORDER BY order_index, id
                        LIMIT 1
                        """,
                        (test_id, q_text),
                    )
                    existing_match_question = cursor.fetchone()
                    if existing_match_question:
                        q_id = existing_match_question[0]
                        merged_modules = ", ".join(
                            sorted(
                                {
                                    *parse_module_names(existing_match_question[1] or ""),
                                    *parse_module_names(source_modules or ""),
                                },
                                key=str.lower,
                            )
                        )
                        cursor.execute(
                            """
                            UPDATE theory_questions
                            SET source_subject = ?, source_modules = ?
                            WHERE id = ?
                            """,
                            (test[2], merged_modules, q_id),
                        )
                if q_id is None:
                    cursor.execute(
                        """
                        INSERT INTO theory_questions (test_id, question_text, question_type, marks, order_index, source_subject, source_modules)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (test_id, q_text, q_type, marks, order_index, test[2], source_modules),
                    )
                    q_id = cursor.lastrowid

                if q_type in ["mcq_single", "mcq_multi"]:
                    options = request.form.getlist("option_text")
                    correct = request.form.getlist("is_correct")
                    for i, opt in enumerate(options):
                        if opt.strip():
                            is_correct = 1 if str(i) in correct else 0
                            cursor.execute(
                                "INSERT INTO theory_options (question_id, option_text, is_correct) VALUES (?, ?, ?)",
                                (q_id, opt.strip(), is_correct),
                            )
                elif q_type == "true_false":
                    correct_answer = request.form.get("tf_correct", "True")
                    correction_term = request.form.get("correction_term", "").strip()
                    cursor.execute(
                        "INSERT INTO theory_options (question_id, option_text, is_correct) VALUES (?, 'True', ?)",
                        (q_id, 1 if correct_answer == "True" else 0),
                    )
                    cursor.execute(
                        "INSERT INTO theory_options (question_id, option_text, is_correct) VALUES (?, 'False', ?)",
                        (q_id, 1 if correct_answer == "False" else 0),
                    )
                    if correction_term:
                        cursor.execute(
                            "INSERT INTO theory_options (question_id, option_text, is_correct, match_pair) VALUES (?, ?, 0, 'correction')",
                            (q_id, correction_term),
                        )
                elif q_type == "fill_in":
                    answer = request.form.get("fill_answer", "").strip()
                    cursor.execute(
                        "INSERT INTO theory_options (question_id, option_text, is_correct) VALUES (?, ?, 1)",
                        (q_id, answer),
                    )
                elif q_type == "match":
                    col_a = request.form.getlist("match_a")
                    col_b = request.form.getlist("match_b")
                    cursor.execute(
                        """
                        SELECT option_text, match_pair
                        FROM theory_options
                        WHERE question_id = ?
                          AND COALESCE(match_pair, '') != ''
                        """,
                        (q_id,),
                    )
                    existing_pairs = {
                        ((option_text or "").strip().lower(), (match_pair or "").strip().lower())
                        for option_text, match_pair in cursor.fetchall()
                    }
                    for a, b in zip(col_a, col_b):
                        if a.strip() and b.strip():
                            pair_signature = (b.strip().lower(), a.strip().lower())
                            if pair_signature in existing_pairs:
                                continue
                            cursor.execute(
                                """
                                INSERT INTO theory_options (question_id, option_text, is_correct, match_pair)
                                VALUES (?, ?, 1, ?)
                                """,
                                (q_id, b.strip(), a.strip()),
                            )
                            existing_pairs.add(pair_signature)
                    cursor.execute(
                        """
                        SELECT COUNT(*)
                        FROM theory_options
                        WHERE question_id = ?
                          AND COALESCE(match_pair, '') != ''
                        """,
                        (q_id,),
                    )
                    pair_count = cursor.fetchone()[0] or 0
                    cursor.execute("UPDATE theory_questions SET marks = ? WHERE id = ?", (pair_count, q_id))
                conn.commit()
                log_activity(username, f"added question to test {test_id}")

            elif action == "duplicate_question" and builder_mode == "lesson":
                q_id = request.form.get("question_id")
                cursor.execute(
                    """
                    SELECT question_text, question_type, marks, order_index
                    FROM theory_questions
                    WHERE id = ? AND test_id = ?
                    """,
                    (q_id, test_id),
                )
                source = cursor.fetchone()
                if source:
                    q_text, q_type, marks, order_index = source
                    cursor.execute(
                        "UPDATE theory_questions SET order_index = order_index + 1 WHERE test_id = ? AND order_index > ?",
                        (test_id, order_index),
                    )
                    cursor.execute(
                        """
                        INSERT INTO theory_questions (test_id, question_text, question_type, marks, order_index)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (test_id, q_text, q_type, marks, order_index + 1),
                    )
                    new_q_id = cursor.lastrowid
                    cursor.execute(
                        """
                        SELECT option_text, is_correct, match_pair
                        FROM theory_options
                        WHERE question_id = ?
                        ORDER BY id
                        """,
                        (q_id,),
                    )
                    for option_text, is_correct, match_pair in cursor.fetchall():
                        cursor.execute(
                            """
                            INSERT INTO theory_options (question_id, option_text, is_correct, match_pair)
                            VALUES (?, ?, ?, ?)
                            """,
                            (new_q_id, option_text, is_correct, match_pair),
                        )
                    conn.commit()
                    log_activity(username, f"duplicated slide {q_id} in test {test_id}")

            elif action == "reorder_questions" and builder_mode == "lesson":
                ordered_ids = request.form.get("ordered_ids", "")
                ids = [int(item) for item in ordered_ids.split(",") if item.strip().isdigit()]
                for index, q_id in enumerate(ids):
                    cursor.execute(
                        "UPDATE theory_questions SET order_index = ? WHERE id = ? AND test_id = ?",
                        (index, q_id, test_id),
                    )
                conn.commit()
                log_activity(username, f"reordered slides in test {test_id}")

            elif action == "delete_question":
                q_id = request.form.get("question_id")
                cursor.execute("DELETE FROM theory_options WHERE question_id = ?", (q_id,))
                cursor.execute("DELETE FROM theory_questions WHERE id = ?", (q_id,))
                conn.commit()

            elif action == "edit_question":
                q_id = request.form.get("question_id")
                q_text = request.form.get("question_text", "").strip()
                if builder_mode == "lesson":
                    q_text = externalize_data_uri_images(q_text)
                q_type = request.form.get("question_type", "")
                marks = int(request.form.get("marks", 1))
                source_modules = ", ".join(
                    parse_module_names(",".join(request.form.getlist("source_modules")) or request.form.get("source_modules") or "")
                )
                if q_type in LESSON_SLIDE_TYPES:
                    marks = 0

                cursor.execute(
                    "UPDATE theory_questions SET question_text = ?, marks = ?, source_subject = ?, source_modules = ? WHERE id = ?",
                    (q_text, marks, test[2], source_modules, q_id),
                )
                cursor.execute("DELETE FROM theory_options WHERE question_id = ?", (q_id,))

                if q_type in ["mcq_single", "mcq_multi"]:
                    options = request.form.getlist("option_text")
                    correct = request.form.getlist("is_correct")
                    for i, opt in enumerate(options):
                        if opt.strip():
                            is_correct = 1 if str(i) in correct else 0
                            cursor.execute(
                                "INSERT INTO theory_options (question_id, option_text, is_correct) VALUES (?, ?, ?)",
                                (q_id, opt.strip(), is_correct),
                            )
                elif q_type == "true_false":
                    correct_answer = request.form.get("tf_correct", "True")
                    correction_term = request.form.get("correction_term", "").strip()
                    cursor.execute(
                        "INSERT INTO theory_options (question_id, option_text, is_correct) VALUES (?, 'True', ?)",
                        (q_id, 1 if correct_answer == "True" else 0),
                    )
                    cursor.execute(
                        "INSERT INTO theory_options (question_id, option_text, is_correct) VALUES (?, 'False', ?)",
                        (q_id, 1 if correct_answer == "False" else 0),
                    )
                    if correction_term:
                        cursor.execute(
                            "INSERT INTO theory_options (question_id, option_text, is_correct, match_pair) VALUES (?, ?, 0, 'correction')",
                            (q_id, correction_term),
                        )
                elif q_type == "fill_in":
                    answer = request.form.get("fill_answer", "").strip()
                    cursor.execute(
                        "INSERT INTO theory_options (question_id, option_text, is_correct) VALUES (?, ?, 1)",
                        (q_id, answer),
                    )
                elif q_type == "match":
                    col_a = request.form.getlist("match_a")
                    col_b = request.form.getlist("match_b")
                    pair_count = 0
                    for a, b in zip(col_a, col_b):
                        if a.strip() and b.strip():
                            cursor.execute(
                                "INSERT INTO theory_options (question_id, option_text, is_correct, match_pair) VALUES (?, ?, 1, ?)",
                                (q_id, b.strip(), a.strip()),
                            )
                            pair_count += 1
                    cursor.execute("UPDATE theory_questions SET marks = ? WHERE id = ?", (pair_count, q_id))
                conn.commit()
                log_activity(username, f"edited question {q_id} in test {test_id}")

            elif action == "import_bank_questions" and builder_mode != "lesson":
                selected_bank_ids = [safe_int(item, 0) for item in request.form.getlist("bank_question_ids")]
                selected_bank_ids = [item for item in selected_bank_ids if item > 0]
                if selected_bank_ids:
                    cursor.execute(
                        """
                        SELECT COALESCE(MAX(order_index), -1) + 1
                        FROM theory_questions
                        WHERE test_id = ?
                        """,
                        (test_id,),
                    )
                    order_index = cursor.fetchone()[0]
                    cursor.execute(
                        """
                        SELECT LOWER(TRIM(question_text))
                        FROM theory_questions
                        WHERE test_id = ?
                        """,
                        (test_id,),
                    )
                    existing_texts = {row[0] for row in cursor.fetchall() if row[0]}
                    selected_match_ids = []
                    selected_regular_ids = []
                    for bank_question_id in selected_bank_ids:
                        cursor.execute("SELECT question_type, question_text FROM question_bank_questions WHERE id = ?", (bank_question_id,))
                        bank_row = cursor.fetchone()
                        if not bank_row:
                            continue
                        bank_type, bank_text = bank_row
                        normalized_text = (bank_text or "").strip().lower()
                        if bank_type == "match":
                            selected_match_ids.append(bank_question_id)
                        elif normalized_text not in existing_texts:
                            selected_regular_ids.append(bank_question_id)
                            existing_texts.add(normalized_text)
                    for bank_question_id in selected_regular_ids:
                        clone_bank_question_to_test(cursor, bank_question_id, test_id, order_index)
                        order_index += 1
                    if selected_match_ids:
                        _, order_index = merge_bank_match_rows_into_test(cursor, selected_match_ids, test_id, order_index)
                    conn.commit()
                    log_activity(username, f"imported question bank items into test {test_id}")

            elif action == "autosave_question" and builder_mode == "lesson":
                q_id = request.form.get("question_id")
                q_text = externalize_data_uri_images(request.form.get("question_text", "").strip())
                marks = safe_int(request.form.get("marks"), 0)
                q_type = request.form.get("question_type", "")
                if q_type in LESSON_SLIDE_TYPES:
                    marks = 0

                cursor.execute("SELECT 1 FROM theory_questions WHERE id = ? AND test_id = ?", (q_id, test_id))
                if not cursor.fetchone():
                    conn.close()
                    return {"ok": False, "error": "not_found"}, 404

                cursor.execute("UPDATE theory_questions SET question_text = ?, marks = ? WHERE id = ?", (q_text, marks, q_id))
                cursor.execute("DELETE FROM theory_options WHERE question_id = ?", (q_id,))

                if q_type in ["mcq_single", "mcq_multi"]:
                    options = request.form.getlist("option_text")
                    correct = request.form.getlist("is_correct")
                    for i, opt in enumerate(options):
                        if opt.strip():
                            cursor.execute(
                                "INSERT INTO theory_options (question_id, option_text, is_correct) VALUES (?, ?, ?)",
                                (q_id, opt.strip(), 1 if str(i) in correct else 0),
                            )
                elif q_type == "true_false":
                    correct_answer = request.form.get("tf_correct", "True")
                    correction_term = request.form.get("correction_term", "").strip()
                    cursor.execute(
                        "INSERT INTO theory_options (question_id, option_text, is_correct) VALUES (?, 'True', ?)",
                        (q_id, 1 if correct_answer == "True" else 0),
                    )
                    cursor.execute(
                        "INSERT INTO theory_options (question_id, option_text, is_correct) VALUES (?, 'False', ?)",
                        (q_id, 1 if correct_answer == "False" else 0),
                    )
                    if correction_term:
                        cursor.execute(
                            "INSERT INTO theory_options (question_id, option_text, is_correct, match_pair) VALUES (?, ?, 0, 'correction')",
                            (q_id, correction_term),
                        )
                elif q_type == "fill_in":
                    answer = request.form.get("fill_answer", "").strip()
                    cursor.execute(
                        "INSERT INTO theory_options (question_id, option_text, is_correct) VALUES (?, ?, 1)",
                        (q_id, answer),
                    )
                elif q_type == "match":
                    col_a = request.form.getlist("match_a")
                    col_b = request.form.getlist("match_b")
                    pair_count = 0
                    for a, b in zip(col_a, col_b):
                        if a.strip() and b.strip():
                            cursor.execute(
                                "INSERT INTO theory_options (question_id, option_text, is_correct, match_pair) VALUES (?, ?, 1, ?)",
                                (q_id, b.strip(), a.strip()),
                            )
                            pair_count += 1
                    cursor.execute("UPDATE theory_questions SET marks = ? WHERE id = ?", (pair_count, q_id))

                if "background_image" in request.form:
                    background_image = externalize_data_uri_images(request.form.get("background_image", "").strip() or None)
                    background_fit = request.form.get("background_fit", "cover").strip() or "cover"
                    if background_fit not in ("cover", "contain", "stretch"):
                        background_fit = "cover"
                    cursor.execute(
                        "UPDATE theory_tests SET background_image = ?, background_fit = ? WHERE id = ?",
                        (background_image, background_fit, test_id),
                    )

                conn.commit()
                return {"ok": True, "saved_at": datetime.now().strftime("%H:%M:%S")}

            elif action == "save_lesson_background" and builder_mode == "lesson":
                background_image = externalize_data_uri_images(request.form.get("background_image", "").strip() or None)
                background_fit = request.form.get("background_fit", "cover").strip() or "cover"
                if background_fit not in ("cover", "contain", "stretch"):
                    background_fit = "cover"
                cursor.execute(
                    "UPDATE theory_tests SET background_image = ?, background_fit = ? WHERE id = ?",
                    (background_image, background_fit, test_id),
                )
                conn.commit()
                log_activity(username, f"updated lesson background for test {test_id}")

            elif action == "import_pptx" and builder_mode == "lesson":
                import_success = None
                import_error = None
                pptx_file = request.files.get("pptx_file")
                append = request.form.get("append") is not None

                try:
                    if not pptx_file or not pptx_file.filename:
                        raise ValueError("Please choose a PowerPoint .pptx file.")
                    if not pptx_file.filename.lower().endswith(".pptx"):
                        raise ValueError("Only .pptx files can be imported.")

                    if not append:
                        cursor.execute(
                            """
                            DELETE FROM theory_options
                            WHERE question_id IN (SELECT id FROM theory_questions WHERE test_id = ?)
                            """,
                            (test_id,),
                        )
                        cursor.execute("DELETE FROM theory_questions WHERE test_id = ?", (test_id,))
                        order_index = 0
                    else:
                        cursor.execute(
                            """
                            SELECT COALESCE(MAX(order_index), -1) + 1
                            FROM theory_questions
                            WHERE test_id = ?
                            """,
                            (test_id,),
                        )
                        order_index = cursor.fetchone()[0]

                    slide_html = pptx_to_content_slide_html(pptx_file)
                    if not slide_html:
                        raise ValueError("No text or pictures were found in that PowerPoint file.")

                    for html in slide_html:
                        cursor.execute(
                            """
                            INSERT INTO theory_questions (test_id, question_text, question_type, marks, order_index)
                            VALUES (?, ?, 'content_slide', 0, ?)
                            """,
                            (test_id, externalize_data_uri_images(html), order_index),
                        )
                        order_index += 1

                    conn.commit()
                    log_activity(username, f"imported PPTX slides into test {test_id}")
                    import_success = f"Imported {len(slide_html)} PowerPoint slide(s)."
                except Exception as e:
                    conn.rollback()
                    import_error = str(e)

                cursor.execute(
                    """
                    SELECT id, question_text, question_type, marks, order_index
                    FROM theory_questions WHERE test_id = ? ORDER BY order_index
                    """,
                    (test_id,),
                )
                questions = cursor.fetchall()
                questions_with_options = []
                for q in questions:
                    cursor.execute("SELECT id, option_text, is_correct, match_pair FROM theory_options WHERE question_id = ?", (q[0],))
                    options = cursor.fetchall()
                    questions_with_options.append({"q": q, "options": options})

                conn.close()
                return render_template(
                    "manage_lesson_questions.html",
                    test=test,
                    questions=questions_with_options,
                    import_success=import_success,
                    import_error=import_error,
                    builder_mode=builder_mode,
                )

            elif action == "import_questions_json":
                import_success = None
                import_error = None

                from theory_json_importer import insert_theory_test_from_json

                payload = request.form.get("questions_json", "").strip()
                append = request.form.get("append") is not None

                try:
                    if not payload:
                        raise ValueError("questions_json is empty")

                    if not append:
                        cursor.execute(
                            """
                            DELETE FROM theory_options
                            WHERE question_id IN (SELECT id FROM theory_questions WHERE test_id = ?)
                            """,
                            (test_id,),
                        )
                        cursor.execute("DELETE FROM theory_questions WHERE test_id = ?", (test_id,))
                        start_order_index = 0
                    else:
                        cursor.execute(
                            """
                            SELECT COALESCE(MAX(order_index), -1) + 1
                            FROM theory_questions
                            WHERE test_id = ?
                            """,
                            (test_id,),
                        )
                        start_order_index = cursor.fetchone()[0]

                    insert_theory_test_from_json(
                        cursor,
                        test_id=test_id,
                        username=username,
                        payload=payload,
                        start_order_index=start_order_index,
                    )

                    conn.commit()
                    log_activity(username, f"imported questions into test {test_id} (append={append})")
                    import_success = "Import completed successfully."
                except Exception as e:
                    conn.rollback()
                    import_error = str(e)

                cursor.execute(
                    """
                    SELECT id, question_text, question_type, marks, order_index
                    FROM theory_questions WHERE test_id = ? ORDER BY order_index
                    """,
                    (test_id,),
                )
                questions = cursor.fetchall()

                questions_with_options = []
                for q in questions:
                    cursor.execute("SELECT id, option_text, is_correct, match_pair FROM theory_options WHERE question_id = ?", (q[0],))
                    options = cursor.fetchall()
                    questions_with_options.append({"q": q, "options": options})

                bank_subject_names, bank_module_names, bank_questions = load_bank_picker_data()

                conn.close()
                return render_template(
                    "manage_lesson_questions.html" if builder_mode == "lesson" else "manage_test_questions.html",
                    test=test,
                    questions=questions_with_options,
                    import_success=import_success,
                    import_error=import_error,
                    builder_mode=builder_mode,
                    bank_subject_names=bank_subject_names,
                    bank_module_names=bank_module_names,
                    bank_questions=bank_questions,
                    bank_selected_subject=bank_selected_subject,
                    bank_selected_module=bank_selected_module,
                    bank_selected_type=bank_selected_type,
                )

            conn.close()
            if builder_mode == "lesson":
                return redirect(url_for("manage_lesson_questions", test_id=test_id))
            return redirect(url_for("manage_test_questions", test_id=test_id))

        cursor.execute(
            """
            SELECT id, question_text, question_type, marks, order_index, source_subject, source_modules
            FROM theory_questions WHERE test_id = ? ORDER BY order_index
            """,
            (test_id,),
        )
        questions = cursor.fetchall()

        questions_with_options = []
        for q in questions:
            cursor.execute("SELECT id, option_text, is_correct, match_pair FROM theory_options WHERE question_id = ?", (q[0],))
            options = cursor.fetchall()
            questions_with_options.append({"q": q, "options": options})

        bank_subject_names, bank_module_names, bank_questions = load_bank_picker_data()

        conn.close()
        return render_template(
            "manage_lesson_questions.html" if builder_mode == "lesson" else "manage_test_questions.html",
            test=test,
            questions=questions_with_options,
            builder_mode=builder_mode,
            bank_subject_names=bank_subject_names,
            bank_module_names=bank_module_names,
            bank_questions=bank_questions,
            bank_selected_subject=bank_selected_subject,
            bank_selected_module=bank_selected_module,
            bank_selected_type=bank_selected_type,
        )

    @app.route("/take_test/<int:test_id>", methods=["GET", "POST"])
    def take_test(test_id):
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))

        option_order_key = f"test_order_{test_id}"
        question_order_key = f"test_question_order_{test_id}"

        conn = get_db()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT id, title, subject, time_limit, allow_multiple, max_attempts, show_answers, background_image, COALESCE(background_fit, 'cover') FROM theory_tests WHERE id = ? AND is_active = 1",
            (test_id,),
        )
        test = cursor.fetchone()
        if not test:
            conn.close()
            return "Test not found or not available", 404

        cursor.execute(
            """
            SELECT id, question_text, question_type, marks
            FROM theory_questions WHERE test_id = ? ORDER BY order_index
            """,
            (test_id,),
        )
        questions = cursor.fetchall()
        content_slide_count = sum(1 for q in questions if q[2] in LESSON_SLIDE_TYPES)
        question_count = len(questions) - content_slide_count
        has_content_slides = content_slide_count > 0
        is_lesson_only = content_slide_count > 0 and question_count == 0

        cursor.execute("SELECT COUNT(*) FROM theory_submissions WHERE test_id = ? AND username = ?", (test_id, username))
        attempt_count = cursor.fetchone()[0]
        allow_multiple = test[4]
        max_attempts = test[5]

        redirect_endpoint = "lesson_tests" if has_content_slides else "learner_tests"

        if not is_lesson_only and not allow_multiple and attempt_count > 0:
            conn.close()
            return redirect(url_for(redirect_endpoint))
        if not is_lesson_only and allow_multiple and attempt_count >= max_attempts:
            conn.close()
            return redirect(url_for(redirect_endpoint))

        if request.method == "GET":
            cursor.execute("SELECT current_slide, max_slide, completed FROM theory_progress WHERE test_id = ? AND username = ?", (test_id, username))
            progress_row = cursor.fetchone()
            initial_slide = progress_row[0] if progress_row and is_lesson_only and not progress_row[2] else 0
            max_slide = (len(questions) - 1) if progress_row and is_lesson_only and progress_row[2] else (progress_row[1] if progress_row and is_lesson_only else 0)
            if not has_content_slides:
                stored_question_order = session.get(question_order_key, [])
                question_lookup = {q[0]: q for q in questions}
                if stored_question_order and set(stored_question_order) == set(question_lookup.keys()):
                    questions = [question_lookup[q_id] for q_id in stored_question_order if q_id in question_lookup]
                else:
                    questions = list(questions)
                    random.shuffle(questions)
                    session[question_order_key] = [q[0] for q in questions]
            else:
                session.pop(question_order_key, None)
            questions_with_options = []
            session_order = {}
            for q in questions:
                cursor.execute("SELECT id, option_text, is_correct, match_pair FROM theory_options WHERE question_id = ?", (q[0],))
                options = list(cursor.fetchall())
                q_type = q[2]
                if q_type in ["mcq_single", "mcq_multi"]:
                    random.shuffle(options)
                elif q_type == "match":
                    options = sorted(options, key=lambda o: o[0])
                    display_values = options[:]
                    random.shuffle(display_values)
                    options = [(o[0], display_values[i][1], o[2], o[3]) for i, o in enumerate(options)]
                session_order[str(q[0])] = [o[0] for o in options]
                questions_with_options.append({"q": q, "options": options})
            session[option_order_key] = session_order
            conn.close()
            return render_template(
                "take_test.html",
                test=test,
                questions=questions_with_options,
                attempt_number=attempt_count + 1,
                initial_slide=initial_slide,
                has_content_slides=has_content_slides,
                content_slide_count=content_slide_count,
                question_count=question_count,
                is_lesson_only=is_lesson_only,
                max_slide=max_slide,
                lesson_completed=is_lesson_only and attempt_count > 0,
            )

        stored_question_order = session.get(question_order_key, [])
        if stored_question_order:
            question_lookup = {q[0]: q for q in questions}
            ordered_questions = [question_lookup[q_id] for q_id in stored_question_order if q_id in question_lookup]
            remaining_questions = [q for q in questions if q[0] not in stored_question_order]
            questions = ordered_questions + remaining_questions

        session_order = session.get(option_order_key, {})
        questions_with_options = []
        for q in questions:
            q_id = q[0]
            cursor.execute("SELECT id, option_text, is_correct, match_pair FROM theory_options WHERE question_id = ?", (q_id,))
            all_options = {o[0]: o for o in cursor.fetchall()}
            stored_ids = session_order.get(str(q_id), [])
            if stored_ids:
                options = [all_options[oid] for oid in stored_ids if oid in all_options]
            else:
                options = list(all_options.values())
            questions_with_options.append({"q": q, "options": options})

        if is_lesson_only:
            time_spent = max(0, int(request.form.get("time_spent_seconds", 0) or 0))
            cursor.execute(
                """
                SELECT COALESCE(time_spent_seconds, 0)
                FROM theory_progress
                WHERE test_id = ? AND username = ?
                """,
                (test_id, username),
            )
            saved_time_row = cursor.fetchone()
            saved_time = saved_time_row[0] if saved_time_row else 0
            total_time = saved_time + time_spent
            cursor.execute(
                """
                INSERT INTO theory_submissions (test_id, username, score, total, percentage, submitted_at, time_spent_seconds, submission_type)
                VALUES (?, ?, 1, 1, 100, ?, ?, 'lesson')
                """,
                (test_id, username, datetime.now().isoformat(), total_time),
            )
            submission_id = cursor.lastrowid
            for item in questions_with_options:
                cursor.execute(
                    """
                    INSERT INTO theory_answers (submission_id, question_id, answer_text, is_correct, marks_awarded)
                    VALUES (?, ?, 'Viewed', 1, 0)
                    """,
                    (submission_id, item["q"][0]),
                )
            cursor.execute(
                """
                INSERT INTO theory_progress (test_id, username, current_slide, max_slide, time_spent_seconds, completed, updated_at)
                VALUES (?, ?, ?, ?, 0, 1, ?)
                ON CONFLICT(test_id, username) DO UPDATE SET
                    current_slide = excluded.current_slide,
                    max_slide = excluded.max_slide,
                    completed = 1,
                    updated_at = excluded.updated_at
                """,
                (test_id, username, len(questions_with_options) - 1, len(questions_with_options) - 1, datetime.now().isoformat()),
            )
            conn.commit()
            conn.close()
            session.pop(option_order_key, None)
            session.pop(question_order_key, None)
            log_activity(username, f"completed lesson {test_id} — 100%")
            return redirect(url_for("lesson_tests"))

        score = 0
        total = 0
        answers_to_save = []

        for item in questions_with_options:
            q = item["q"]
            q_id, q_text, q_type, marks = q
            options = item["options"]
            if q_type in ["content_slide", "title_slide", "heading_slide"]:
                answers_to_save.append((q_id, "Viewed", 1, 0))
                continue
            effective_marks = len([o for o in options if o[3] and o[3] != "correction"]) if q_type == "match" else marks
            total += effective_marks
            awarded = 0
            answer_text = ""

            if q_type == "mcq_single":
                selected = request.form.get(f"q_{q_id}")
                answer_text = selected or ""
                cursor.execute("SELECT option_text FROM theory_options WHERE question_id = ? AND is_correct = 1 LIMIT 1", (q_id,))
                correct_row = cursor.fetchone()
                correct_option = correct_row[0] if correct_row else None
                if selected and selected == correct_option:
                    awarded = marks
            elif q_type == "mcq_multi":
                selected = set(request.form.getlist(f"q_{q_id}"))
                cursor.execute("SELECT option_text FROM theory_options WHERE question_id = ? AND is_correct = 1", (q_id,))
                correct = set(row[0] for row in cursor.fetchall())
                answer_text = ", ".join(sorted(selected))
                if selected == correct:
                    awarded = marks
            elif q_type == "true_false":
                selected = request.form.get(f"q_{q_id}")
                correction_submitted = request.form.get(f"q_{q_id}_correction", "").strip()
                answer_text = selected or ""
                if correction_submitted:
                    answer_text += f" (correction: {correction_submitted})"
                awarded = score_true_false_answer(selected, correction_submitted, options, effective_marks)
            elif q_type == "fill_in":
                answer_text = request.form.get(f"q_{q_id}", "").strip()
                awarded = score_fill_in_answer(answer_text, options, marks)
            elif q_type == "match":
                match_answers = []
                awarded = 0
                for idx, o in enumerate(options, start=1):
                    col_b_correct = o[1]
                    submitted = request.form.get(f"q_{q_id}_{idx}", "")
                    match_answers.append(f"{idx}={submitted}")
                    if submitted == col_b_correct:
                        awarded += 1
                answer_text = "; ".join(match_answers)

            score += awarded
            answers_to_save.append((q_id, answer_text, 1 if awarded == effective_marks else 0, awarded))

        percentage = round((score / total) * 100) if total else 0
        time_spent = max(0, int(request.form.get("time_spent_seconds", 0) or 0))

        cursor.execute(
            """
            INSERT INTO theory_submissions (test_id, username, score, total, percentage, submitted_at, time_spent_seconds, submission_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (test_id, username, score, total, percentage, datetime.now().isoformat(), time_spent, "test"),
        )
        submission_id = cursor.lastrowid

        for q_id, answer_text, is_correct, awarded in answers_to_save:
            cursor.execute(
                """
                INSERT INTO theory_answers (submission_id, question_id, answer_text, is_correct, marks_awarded)
                VALUES (?, ?, ?, ?, ?)
                """,
                (submission_id, q_id, answer_text, is_correct, awarded),
            )

        conn.commit()
        cursor.execute(
            "UPDATE theory_progress SET completed = 1, current_slide = ?, updated_at = ? WHERE test_id = ? AND username = ?",
            (len(questions_with_options) - 1, datetime.now().isoformat(), test_id, username),
        )
        conn.commit()
        conn.close()
        session.pop(option_order_key, None)
        session.pop(question_order_key, None)
        log_activity(username, f"completed theory test {test_id} — {percentage}%")
        return redirect(url_for("test_results", submission_id=submission_id))

    @app.route("/test_results/<int:submission_id>")
    def test_results(submission_id):
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))

        conn = get_db()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT s.id, s.score, s.total, s.percentage, s.submitted_at, t.title, t.subject,
                   t.show_answers, t.allow_multiple, t.max_attempts, t.id as test_id
            FROM theory_submissions s
            JOIN theory_tests t ON s.test_id = t.id
            WHERE s.id = ? AND s.username = ?
            """,
            (submission_id, username),
        )
        submission = cursor.fetchone()
        if not submission:
            conn.close()
            return "Results not found", 404

        test_id = submission[10]
        show_answers = submission[7]
        allow_multiple = submission[8]
        max_attempts = submission[9]

        cursor.execute("SELECT COUNT(*), MAX(percentage) FROM theory_submissions WHERE test_id = ? AND username = ?", (test_id, username))
        attempt_row = cursor.fetchone()
        attempts_used = attempt_row[0]
        best_percentage = attempt_row[1]
        can_retry = allow_multiple and attempts_used < max_attempts

        cursor.execute(
            """
            SELECT q.question_text, q.question_type, q.marks,
                   a.answer_text, a.is_correct, a.marks_awarded, a.question_id
            FROM theory_answers a
            JOIN theory_questions q ON a.question_id = q.id
            WHERE a.submission_id = ?
            ORDER BY q.order_index
            """,
            (submission_id,),
        )
        answers = cursor.fetchall()

        detailed = []
        for ans in answers:
            q_text, q_type, marks, answer_text, is_correct, marks_awarded, q_id = ans
            cursor.execute(
                """
                SELECT option_text, is_correct, match_pair
                FROM theory_options WHERE question_id = ?
                """,
                (q_id,),
            )
            options = cursor.fetchall()
            detailed.append(
                {
                    "question": q_text,
                    "type": q_type,
                    "marks": marks,
                    "answer": answer_text,
                    "correct": is_correct,
                    "awarded": marks_awarded,
                    "options": options,
                }
            )

        conn.close()
        return render_template(
            "test_results.html",
            submission=submission,
            detailed=detailed,
            show_answers=show_answers,
            can_retry=can_retry,
            attempts_used=attempts_used,
            max_attempts=max_attempts,
            best_percentage=best_percentage,
            test_id=test_id,
        )

    @app.route("/manage_tests/<int:test_id>/reuse", methods=["POST"])
    def reuse_test(test_id):
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))
        if get_user_role(username) not in ["teacher", "admin"]:
            return "Access denied", 403

        title = request.form.get("title", "").strip()
        subject = request.form.get("subject", "").strip()
        assign_date = request.form.get("assign_date")
        time_limit = safe_int(request.form.get("time_limit"), 0)
        allow_multiple = 1 if request.form.get("allow_multiple") else 0
        max_attempts = safe_int(request.form.get("max_attempts"), 1)
        show_answers = 1 if request.form.get("show_answers") else 0
        groups = request.form.getlist("groups")

        if not title or not assign_date:
            return redirect(url_for("manage_tests"))

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT background_image, COALESCE(background_fit, 'cover') FROM theory_tests WHERE id = ?", (test_id,))
        source_bg_row = cursor.fetchone()
        background_image = source_bg_row[0] if source_bg_row else None
        background_fit = source_bg_row[1] if source_bg_row else "cover"

        cursor.execute(
            """
            INSERT INTO theory_tests
                (title, subject, assign_date, time_limit, allow_multiple, max_attempts,
                 show_answers, background_image, background_fit, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                title,
                subject,
                assign_date,
                time_limit,
                allow_multiple,
                max_attempts,
                show_answers,
                background_image,
                background_fit,
                username,
                datetime.now().isoformat(),
            ),
        )
        new_test_id = cursor.lastrowid

        for group_name in groups:
            if group_name.strip():
                cursor.execute("INSERT INTO theory_test_groups (test_id, group_name) VALUES (?, ?)", (new_test_id, group_name))

        cursor.execute(
            """
            SELECT id, question_text, question_type, marks, order_index
            FROM theory_questions WHERE test_id = ? ORDER BY order_index
            """,
            (test_id,),
        )
        questions = cursor.fetchall()

        if questions:
            q_ids = [q[0] for q in questions]
            placeholders = ",".join("?" * len(q_ids))
            cursor.execute(
                f"""
                SELECT question_id, option_text, is_correct, match_pair
                FROM theory_options WHERE question_id IN ({placeholders})
                ORDER BY question_id, id
                """,
                q_ids,
            )
            all_options = cursor.fetchall()
        else:
            all_options = []

        options_by_q = defaultdict(list)
        for opt in all_options:
            options_by_q[opt[0]].append(opt[1:])

        for q_id, q_text, q_type, marks, order_index in questions:
            cursor.execute(
                """
                INSERT INTO theory_questions (test_id, question_text, question_type, marks, order_index)
                VALUES (?, ?, ?, ?, ?)
                """,
                (new_test_id, q_text, q_type, marks, order_index),
            )
            new_q_id = cursor.lastrowid
            for opt_text, is_correct, match_pair in options_by_q[q_id]:
                cursor.execute(
                    """
                    INSERT INTO theory_options (question_id, option_text, is_correct, match_pair)
                    VALUES (?, ?, ?, ?)
                    """,
                    (new_q_id, opt_text, is_correct, match_pair),
                )

        conn.commit()
        conn.close()
        log_activity(username, f"reused test {test_id} as '{title}'")
        return redirect(url_for("manage_test_questions", test_id=new_test_id))
