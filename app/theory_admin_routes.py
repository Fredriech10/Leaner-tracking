import csv
import io
from datetime import datetime

from flask import Response, jsonify, redirect, render_template, request, session, url_for
from markupsafe import escape

from app.database import get_db, get_groups, get_teachers, get_user_role, log_activity
from app.helper_common import normalize_question_bank_group_text, parse_module_names, safe_int
from app.helper_theory import (
    bank_question_exists,
    clone_bank_question_to_test,
    cleanup_duplicate_generated_questions,
    create_generated_match_question,
    get_question_bank_counts,
    pick_unique_bank_question_ids,
)

QUESTION_BANK_SUPPORTED_TYPES = ("mcq_single", "true_false", "fill_in", "match")


def register_theory_admin_routes(app):
    @app.route("/manage_tests")
    def manage_tests():
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))
        role = get_user_role(username)
        if role not in ["teacher", "admin"]:
            return "Access denied", 403

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                t.id, t.title, t.subject, t.assign_date, t.time_limit, t.is_active,
                GROUP_CONCAT(DISTINCT tg.group_name),
                COUNT(DISTINCT q.id),
                t.allow_multiple, t.max_attempts, t.show_answers,
                GROUP_CONCAT(DISTINCT tt.teacher_username),
                SUM(CASE WHEN q.question_type IN ('content_slide', 'title_slide', 'heading_slide') THEN 1 ELSE 0 END) as content_count
            FROM theory_tests t
            LEFT JOIN theory_questions q ON t.id = q.test_id
            LEFT JOIN theory_test_groups tg ON t.id = tg.test_id
            LEFT JOIN theory_test_teachers tt ON t.id = tt.test_id
            GROUP BY t.id
            HAVING COALESCE(content_count, 0) = 0
            ORDER BY t.created_at DESC
            """
        )
        tests = cursor.fetchall()
        groups = get_groups(username) if role == "teacher" else get_groups()
        teachers = get_teachers()
        teacher_checkboxes = "".join(
            f'<label style="font-weight:normal;display:inline-flex;align-items:center;gap:5px;">'
            f'<input type="checkbox" name="teachers" value="{escape(teacher[0])}"> {escape(teacher[1] or teacher[0])}</label>'
            for teacher in teachers
        )

        test_list = ""
        for test in tests:
            test_id = test[0]
            test_title = escape(test[1] or "")
            test_subject = escape(test[2] or "")
            assign_date = test[3] or "—"
            time_limit_val = test[4] or 0
            is_active = bool(test[5])
            groups_text = escape(test[6] or "All Groups")
            question_count = test[7] or 0
            allow_multiple = bool(test[8])
            max_attempts = test[9] or 1
            show_answers = bool(test[10])
            teachers_text = escape(test[11] or "All Teachers")
            category_badge = '<span class="badge-inactive" style="background:#e3f2fd;color:#0078D4;">Test</span>'
            status_badge = '<span class="badge-active">Active</span>' if is_active else '<span class="badge-inactive">Inactive</span>'
            attempt_text = f"{max_attempts} max" if allow_multiple else "1 (single)"
            toggle_label = "Deactivate" if is_active else "Activate"
            toggle_class = "btn-warning" if is_active else "btn-success"

            test_list += f"""
            <tr>
                <td>{test_title}</td>
                <td>{test_subject or '—'}</td>
                <td>{category_badge}</td>
                <td>{groups_text}</td>
                <td>{teachers_text}</td>
                <td>{question_count}</td>
                <td>{assign_date}</td>
                <td>{time_limit_val if time_limit_val else 'No limit'}</td>
                <td>{attempt_text}</td>
                <td>{'✔ Yes' if show_answers else '✘ No'}</td>
                <td>{status_badge}</td>
                <td style="white-space:nowrap; vertical-align:middle;">
                    <div class="action-cell">
                    <a href="/manage_tests/{test_id}/questions" class="btn btn-primary" title="Edit questions">✏️</a>
                    <a href="/manage_tests/{test_id}/edit" class="btn btn-warning" title="Edit settings">⚙️</a>
                    <button type="button" class="btn btn-success" title="Reuse: copy questions into a new test"
                        onclick="openReuseModal(this)"
                        data-test-id="{test_id}"
                        data-title="{test_title}"
                        data-subject="{test_subject}"
                        data-time-limit="{time_limit_val}"
                        data-allow-multiple="{1 if allow_multiple else 0}"
                        data-max-attempts="{max_attempts}"
                        data-show-answers="{1 if show_answers else 0}">📋</button>
                    <form method="post" action="/manage_tests/{test_id}/toggle" style="display:inline-flex; margin:0;">
                        <button type="submit" class="btn {toggle_class}" title="{toggle_label}">{'⏸' if is_active else '▶'}</button>
                    </form>
                    <form method="post" action="/manage_tests/{test_id}/delete" style="display:inline-flex; margin:0;"
                          onsubmit="return confirm('⚠️ WARNING: Delete this test, all questions, AND ALL STUDENT SUBMISSIONS?\n\nThis will permanently remove:\n- All test questions\n- All student attempts and scores\n- Test from Group Results\n\nThis action CANNOT be undone!')">
                        <button type="submit" class="btn btn-danger" title="Delete test">🗑</button>
                    </form>
                    </div>
                </td>
            </tr>
            """

        conn.close()
        return render_template(
            "manage_tests.html",
            tests=tests,
            groups=groups,
            teacher_checkboxes=teacher_checkboxes,
            test_list=test_list,
            linked_test_count=0,
            standalone_test_count=len(tests),
            page_title="Theory Tests",
            page_intro="This page manages the simple question-only part of Theory.",
        )

    @app.route("/question_bank", methods=["GET", "POST"])
    def question_bank():
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))
        if get_user_role(username) not in ["teacher", "admin"]:
            return "Access denied", 403

        conn = get_db()
        cursor = conn.cursor()
        message = ""
        error = ""

        if request.method == "POST":
            action = request.form.get("action", "").strip()
            if action == "delete_question":
                question_id = request.form.get("question_id", type=int)
                if question_id:
                    cursor.execute("DELETE FROM question_bank_options WHERE bank_question_id = ?", (question_id,))
                    cursor.execute("DELETE FROM question_bank_questions WHERE id = ?", (question_id,))
                    conn.commit()
                    message = "Question removed from bank."
            elif action == "delete_question_group":
                raw_ids = (request.form.get("question_ids") or "").strip()
                question_ids = [safe_int(part, 0) for part in raw_ids.split(",") if part.strip()]
                question_ids = [item for item in question_ids if item > 0]
                if question_ids:
                    placeholders = ",".join("?" for _ in question_ids)
                    cursor.execute(f"DELETE FROM question_bank_options WHERE bank_question_id IN ({placeholders})", question_ids)
                    cursor.execute(f"DELETE FROM question_bank_questions WHERE id IN ({placeholders})", question_ids)
                    conn.commit()
                    message = f"Removed {len(question_ids)} grouped match pair(s)."
            elif action == "bulk_delete_questions":
                question_ids = []
                for raw_item in request.form.getlist("question_ids"):
                    for part in str(raw_item).split(","):
                        parsed = safe_int(part, 0)
                        if parsed > 0:
                            question_ids.append(parsed)
                question_ids = sorted(set(question_ids))
                if question_ids:
                    placeholders = ",".join("?" for _ in question_ids)
                    cursor.execute(f"DELETE FROM question_bank_options WHERE bank_question_id IN ({placeholders})", question_ids)
                    cursor.execute(f"DELETE FROM question_bank_questions WHERE id IN ({placeholders})", question_ids)
                    conn.commit()
                    message = f"Removed {len(question_ids)} bank question(s)."
            elif action == "import_bank_csv":
                upload = request.files.get("questions_csv")
                try:
                    if not upload or not upload.filename:
                        raise ValueError("Please choose a CSV file.")
                    content = upload.stream.read().decode("utf-8-sig")
                    reader = csv.DictReader(io.StringIO(content))
                    imported = 0
                    skipped = 0
                    for item in reader:
                        q_text = (item.get("question_text") or item.get("question") or "").strip()
                        q_type = (item.get("question_type") or "").strip().lower()
                        if not q_text or q_type not in QUESTION_BANK_SUPPORTED_TYPES:
                            continue
                        marks = safe_int(item.get("marks"), 1)
                        if q_type == "mcq_single":
                            marks = 1
                        subject = (item.get("subject") or "").strip()
                        modules = ", ".join(parse_module_names(item.get("modules") or item.get("module") or ""))
                        option_payload = []
                        if q_type == "mcq_single":
                            option_texts = []
                            for idx in range(1, 7):
                                option_text = (item.get(f"option_{idx}") or "").strip()
                                if option_text:
                                    option_texts.append(option_text)
                            correct_raw = (item.get("correct_answer") or "").strip()
                            correct_index = safe_int(correct_raw, 0) - 1 if correct_raw.isdigit() else -1
                            normalized_correct = correct_raw.lower()
                            for idx, option_text in enumerate(option_texts):
                                option_payload.append((option_text, 1 if idx == correct_index or option_text.lower() == normalized_correct else 0, None))
                        elif q_type == "true_false":
                            correct_answer = (item.get("correct_answer") or "True").strip().title()
                            option_payload.extend([("True", 1 if correct_answer == "True" else 0, None), ("False", 1 if correct_answer == "False" else 0, None)])
                            correction = (item.get("correction") or "").strip()
                            if correction:
                                option_payload.append((correction, 0, "correction"))
                        elif q_type == "fill_in":
                            answer = (item.get("answer") or item.get("correct_answer") or "").strip()
                            if answer:
                                option_payload.append((answer, 1, None))
                        elif q_type == "match":
                            left = ""
                            right = ""
                            for idx in range(1, 7):
                                candidate_left = (item.get(f"match_a_{idx}") or "").strip()
                                candidate_right = (item.get(f"match_b_{idx}") or "").strip()
                                if candidate_left and candidate_right:
                                    left = candidate_left
                                    right = candidate_right
                                    break
                            if left and right:
                                option_payload.append((right, 1, left))
                        if bank_question_exists(cursor, q_text, q_type, subject, modules, option_payload):
                            skipped += 1
                            continue
                        cursor.execute(
                            """
                            INSERT INTO question_bank_questions (question_text, question_type, marks, subject, modules, created_by, created_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (q_text, q_type, marks, subject, modules, username, datetime.now().isoformat()),
                        )
                        bank_question_id = cursor.lastrowid
                        for option_text, is_correct, match_pair in option_payload:
                            cursor.execute(
                                """
                                INSERT INTO question_bank_options (bank_question_id, option_text, is_correct, match_pair)
                                VALUES (?, ?, ?, ?)
                                """,
                                (bank_question_id, option_text, is_correct, match_pair),
                            )
                        imported += 1
                    conn.commit()
                    message = f"Imported {imported} bank question(s)."
                    if skipped:
                        message += f" Skipped {skipped} duplicate(s)."
                except Exception as exc:
                    error = f"Import failed: {exc}"
            elif action == "add_question":
                q_text = (request.form.get("question_text") or "").strip()
                q_type = (request.form.get("question_type") or "").strip()
                marks = safe_int(request.form.get("marks"), 1)
                if q_type == "mcq_single":
                    marks = 1
                subject = (request.form.get("subject") or "").strip()
                modules = ", ".join(parse_module_names(request.form.get("modules") or ""))
                if not q_text or q_type not in QUESTION_BANK_SUPPORTED_TYPES:
                    error = "Question text and a supported type are required."
                else:
                    option_payload = []
                    if q_type == "mcq_single":
                        option_texts = request.form.getlist("option_text")
                        correct_index = safe_int(request.form.get("is_correct"), -1)
                        for idx, option_text in enumerate(option_texts):
                            option_text = option_text.strip()
                            if option_text:
                                option_payload.append((option_text, 1 if idx == correct_index else 0, None))
                    elif q_type == "true_false":
                        tf_correct = (request.form.get("tf_correct") or "True").strip()
                        correction = (request.form.get("correction_term") or "").strip()
                        option_payload.extend([("True", 1 if tf_correct == "True" else 0, None), ("False", 1 if tf_correct == "False" else 0, None)])
                        if correction:
                            option_payload.append((correction, 0, "correction"))
                    elif q_type == "fill_in":
                        answer = (request.form.get("fill_answer") or "").strip()
                        if answer:
                            option_payload.append((answer, 1, None))
                    elif q_type == "match":
                        match_a = request.form.getlist("match_a")
                        match_b = request.form.getlist("match_b")
                        for left, right in zip(match_a, match_b):
                            left = left.strip()
                            right = right.strip()
                            if left and right:
                                option_payload.append((right, 1, left))
                                break
                    if bank_question_exists(cursor, q_text, q_type, subject, modules, option_payload):
                        error = "That question already exists in the bank."
                    else:
                        cursor.execute(
                            """
                            INSERT INTO question_bank_questions (question_text, question_type, marks, subject, modules, created_by, created_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (q_text, q_type, marks, subject, modules, username, datetime.now().isoformat()),
                        )
                        bank_question_id = cursor.lastrowid
                        for option_text, is_correct, match_pair in option_payload:
                            cursor.execute(
                                """
                                INSERT INTO question_bank_options (bank_question_id, option_text, is_correct, match_pair)
                                VALUES (?, ?, ?, ?)
                                """,
                                (bank_question_id, option_text, is_correct, match_pair),
                            )
                        conn.commit()
                        message = "Question added to bank."

        selected_subject = (request.args.get("subject") or "").strip()
        selected_module = (request.args.get("module") or "").strip()
        selected_question_type = (request.args.get("question_type") or "").strip()
        where_parts = []
        params = []
        if selected_subject:
            where_parts.append("LOWER(COALESCE(subject, '')) = ?")
            params.append(selected_subject.lower())
        if selected_module:
            where_parts.append("LOWER(COALESCE(modules, '')) LIKE ?")
            params.append(f"%{selected_module.lower()}%")
        if selected_question_type and selected_question_type in QUESTION_BANK_SUPPORTED_TYPES:
            where_parts.append("question_type = ?")
            params.append(selected_question_type)
        where_clause = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
        cursor.execute(
            f"""
            SELECT id, question_text, question_type, marks, subject, modules, created_by, created_at
            FROM question_bank_questions
            {where_clause}
            ORDER BY id DESC
            """,
            params,
        )
        question_rows = cursor.fetchall()
        raw_questions = []
        for row in question_rows:
            cursor.execute(
                """
                SELECT id, option_text, is_correct, match_pair
                FROM question_bank_options
                WHERE bank_question_id = ?
                ORDER BY id
                """,
                (row[0],),
            )
            raw_questions.append({"q": row, "options": cursor.fetchall()})

        questions = []
        grouped_questions = {}
        grouped_order = []
        for item in raw_questions:
            q = item["q"]
            group_key = (
                normalize_question_bank_group_text(q[1]),
                (q[2] or "").strip().lower(),
                (q[4] or "").strip().lower(),
                (q[5] or "").strip().lower(),
            )
            if group_key not in grouped_questions:
                grouped_questions[group_key] = {
                    "q": q,
                    "options": [],
                    "group_ids": [],
                    "pair_count": 0,
                    "is_grouped_match": q[2] == "match",
                    "is_grouped_question": False,
                }
                grouped_order.append(group_key)
            grouped_questions[group_key]["options"].extend(item["options"])
            grouped_questions[group_key]["group_ids"].append(q[0])
            grouped_questions[group_key]["pair_count"] += len([opt for opt in item["options"] if opt[3] and opt[3] != "correction"])

        for key in grouped_order:
            grouped_item = grouped_questions[key]
            grouped_item["is_grouped_question"] = len(grouped_item["group_ids"]) > 1
            seen_options = set()
            unique_options = []
            for option in grouped_item["options"]:
                option_key = ((option[1] or "").strip().lower(), int(option[2] or 0), (option[3] or "").strip().lower())
                if option_key in seen_options:
                    continue
                seen_options.add(option_key)
                unique_options.append(option)
            grouped_item["options"] = unique_options
            questions.append(grouped_item)

        cursor.execute("SELECT modules FROM question_bank_questions WHERE COALESCE(modules, '') != ''")
        module_names = []
        for (modules_text,) in cursor.fetchall():
            module_names.extend(parse_module_names(modules_text))
        module_names = sorted({item for item in module_names}, key=str.lower)
        cursor.execute("SELECT DISTINCT TRIM(subject) FROM question_bank_questions WHERE COALESCE(TRIM(subject), '') != '' ORDER BY LOWER(TRIM(subject))")
        subject_names = [row[0] for row in cursor.fetchall() if row[0]]
        conn.close()
        return render_template(
            "question_bank.html",
            questions=questions,
            module_names=module_names,
            subject_names=subject_names,
            selected_subject=selected_subject,
            selected_module=selected_module,
            selected_question_type=selected_question_type,
            question_types=QUESTION_BANK_SUPPORTED_TYPES,
            message=message,
            error=error,
        )

    @app.route("/question_bank_template.csv")
    def question_bank_template():
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))
        if get_user_role(username) not in ["teacher", "admin"]:
            return "Access denied", 403

        output = io.StringIO()
        fieldnames = [
            "question_text", "question_type", "marks", "subject", "modules",
            "option_1", "option_2", "option_3", "option_4", "correct_answer", "correction",
            "match_a_1", "match_b_1", "match_a_2", "match_b_2", "match_a_3", "match_b_3", "match_a_4", "match_b_4",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows([
            {"question_text": "What does CPU stand for?", "question_type": "mcq_single", "marks": "1", "subject": "Computer Basics", "modules": "Hardware, Fundamentals", "option_1": "Central Process Unit", "option_2": "Central Processing Unit", "option_3": "Computer Personal Unit", "option_4": "Central Processor Utility", "correct_answer": "2"},
            {"question_text": "The desktop is the main screen area you see after logging in.", "question_type": "true_false", "marks": "1", "subject": "Computer Basics", "modules": "Desktop", "correct_answer": "True", "correction": ""},
            {"question_text": "The shortcut key for copy is ____.", "question_type": "fill_in", "marks": "1", "subject": "Keyboard", "modules": "Shortcuts", "correct_answer": "Ctrl+C"},
            {"question_text": "Match the shortcut to the action.", "question_type": "match", "marks": "1", "subject": "Keyboard", "modules": "Shortcuts", "match_a_1": "Copy", "match_b_1": "Ctrl+C"},
            {"question_text": "Match the shortcut to the action.", "question_type": "match", "marks": "1", "subject": "Keyboard", "modules": "Shortcuts", "match_a_1": "Paste", "match_b_1": "Ctrl+V"},
        ])
        response = Response(output.getvalue(), mimetype="text/csv")
        response.headers["Content-Disposition"] = "attachment; filename=question_bank_template.csv"
        return response

    @app.route("/generate_theory_test", methods=["GET", "POST"])
    def generate_theory_test():
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))
        if get_user_role(username) not in ["teacher", "admin"]:
            return "Access denied", 403

        conn = get_db()
        cursor = conn.cursor()
        groups = get_groups(username) if get_user_role(username) == "teacher" else get_groups()
        teachers = get_teachers()

        cursor.execute("SELECT modules FROM question_bank_questions WHERE COALESCE(modules, '') != ''")
        module_names = []
        for (modules_text,) in cursor.fetchall():
            module_names.extend(parse_module_names(modules_text))
        module_names = sorted({item for item in module_names}, key=str.lower)

        cursor.execute("SELECT DISTINCT TRIM(subject) FROM question_bank_questions WHERE COALESCE(TRIM(subject), '') != '' ORDER BY LOWER(TRIM(subject))")
        subject_names = [row[0] for row in cursor.fetchall() if row[0]]
        cursor.execute("SELECT COALESCE(TRIM(subject), ''), COALESCE(modules, '') FROM question_bank_questions")
        subject_module_map = {}
        for subject_name, modules_text in cursor.fetchall():
            normalized_subject = (subject_name or "").strip()
            if not normalized_subject:
                continue
            subject_module_map.setdefault(normalized_subject, [])
            subject_module_map[normalized_subject].extend(parse_module_names(modules_text))
        subject_module_map = {subject_name: sorted({module for module in modules if module}, key=str.lower) for subject_name, modules in subject_module_map.items()}
        counts = get_question_bank_counts(cursor, module_names, [])

        error = ""
        message = ""
        if request.method == "POST":
            title = (request.form.get("title") or "").strip()
            subject = (request.form.get("subject") or "").strip()
            assign_date = (request.form.get("assign_date") or "").strip()
            time_limit = safe_int(request.form.get("time_limit"), 0)
            allow_multiple = 1 if request.form.get("allow_multiple") else 0
            max_attempts = safe_int(request.form.get("max_attempts"), 1)
            show_answers = 1 if request.form.get("show_answers") else 0
            selected_groups = request.form.getlist("groups")
            selected_teachers = request.form.getlist("teachers")
            selected_modules = parse_module_names(",".join(request.form.getlist("modules")))
            selected_subjects = [item.strip() for item in request.form.getlist("bank_subjects") if item.strip()]
            request_counts = {q_type: max(0, safe_int(request.form.get(f"count_{q_type}"), 0)) for q_type in QUESTION_BANK_SUPPORTED_TYPES}

            if not title or not assign_date:
                error = "Title and assign date are required."
            elif not selected_modules:
                error = "Select at least one module."
            elif not any(request_counts.values()):
                error = "Choose at least one question count."
            else:
                selected_questions = []
                selected_match_pairs = []
                used_question_texts = set()
                for q_type, needed in request_counts.items():
                    if needed <= 0:
                        continue
                    picked, used_question_texts = pick_unique_bank_question_ids(cursor, q_type, needed, selected_modules, selected_subjects, used_question_texts)
                    if len(picked) < needed:
                        scope_text = "selected modules"
                        if selected_subjects:
                            scope_text += " and subjects"
                        error = f"Not enough {q_type.replace('_', ' ')} questions in the {scope_text}."
                        break
                    if q_type == "match":
                        selected_match_pairs = picked
                    else:
                        selected_questions.extend(picked)

                if not error:
                    cursor.execute(
                        """
                        INSERT INTO theory_tests
                            (title, subject, assign_date, time_limit, allow_multiple, max_attempts, show_answers, created_by, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (title, subject, assign_date, time_limit, allow_multiple, max_attempts, show_answers, username, datetime.now().isoformat()),
                    )
                    test_id = cursor.lastrowid
                    for group_name in selected_groups:
                        if group_name.strip():
                            cursor.execute("INSERT INTO theory_test_groups (test_id, group_name) VALUES (?, ?)", (test_id, group_name))
                    for teacher_username in selected_teachers:
                        if teacher_username.strip():
                            cursor.execute("INSERT INTO theory_test_teachers (test_id, teacher_username) VALUES (?, ?)", (test_id, teacher_username))
                    order_index = 0
                    for bank_question_id in selected_questions:
                        clone_bank_question_to_test(cursor, bank_question_id, test_id, order_index)
                        order_index += 1
                    if selected_match_pairs:
                        create_generated_match_question(cursor, selected_match_pairs, test_id, order_index)
                    conn.commit()
                    conn.close()
                    cleanup_duplicate_generated_questions(test_id=test_id, unsubmitted_only=False)
                    log_activity(username, f"generated theory test '{title}' from question bank")
                    return redirect(url_for("manage_test_questions", test_id=test_id))

        conn.close()
        return render_template(
            "generate_theory_test.html",
            groups=groups,
            teachers=teachers,
            module_names=module_names,
            subject_names=subject_names,
            subject_module_map=subject_module_map,
            counts=counts,
            error=error,
            message=message,
        )

    @app.route("/question_bank_counts")
    def question_bank_counts():
        username = session.get("username")
        if not username:
            return jsonify({"error": "unauthorized"}), 401
        if get_user_role(username) not in ["teacher", "admin"]:
            return jsonify({"error": "forbidden"}), 403

        modules = request.args.getlist("modules")
        subjects = request.args.getlist("subjects")
        conn = get_db()
        cursor = conn.cursor()
        counts = get_question_bank_counts(cursor, modules, subjects)
        conn.close()
        return jsonify({"counts": counts})

    @app.route("/manage_tests/create", methods=["POST"])
    def create_test():
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))
        if get_user_role(username) not in ["teacher", "admin"]:
            return "Access denied", 403

        title = request.form.get("title", "").strip()
        subject = request.form.get("subject", "").strip()
        groups = request.form.getlist("groups")
        teachers = request.form.getlist("teachers")
        time_limit = safe_int(request.form.get("time_limit"), 0)
        assign_date = request.form.get("assign_date")
        allow_multiple = 1 if request.form.get("allow_multiple") else 0
        max_attempts = safe_int(request.form.get("max_attempts"), 1)
        show_answers = 1 if request.form.get("show_answers") else 0

        if not title:
            return "Test title is required", 400

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO theory_tests
                (title, subject, assign_date, time_limit, allow_multiple, max_attempts, show_answers, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (title, subject, assign_date, time_limit, allow_multiple, max_attempts, show_answers, username, datetime.now().isoformat()),
        )
        test_id = cursor.lastrowid
        for group_name in groups:
            if group_name.strip():
                cursor.execute("INSERT INTO theory_test_groups (test_id, group_name) VALUES (?, ?)", (test_id, group_name))
        for teacher in teachers:
            if teacher.strip():
                cursor.execute("INSERT INTO theory_test_teachers (test_id, teacher_username) VALUES (?, ?)", (test_id, teacher))
        conn.commit()
        conn.close()
        log_activity(username, f"created theory test '{title}'")
        return redirect(url_for("manage_test_questions", test_id=test_id))

    @app.route("/manage_tests/<int:test_id>/edit", methods=["GET", "POST"])
    def edit_test(test_id):
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))
        if get_user_role(username) not in ["teacher", "admin"]:
            return "Access denied", 403

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id, title, subject, assign_date, time_limit, allow_multiple, max_attempts, show_answers FROM theory_tests WHERE id = ?", (test_id,))
        test = cursor.fetchone()
        if not test:
            conn.close()
            return "Test not found", 404

        if request.method == "POST":
            allow_multiple = 1 if request.form.get("allow_multiple") else 0
            max_attempts = safe_int(request.form.get("max_attempts"), 1)
            show_answers = 1 if request.form.get("show_answers") else 0
            groups = request.form.getlist("groups")
            teachers = request.form.getlist("teachers")
            assign_date = request.form.get("assign_date")

            cursor.execute(
                """
                UPDATE theory_tests
                SET assign_date = ?, allow_multiple = ?, max_attempts = ?, show_answers = ?
                WHERE id = ?
                """,
                (assign_date, allow_multiple, max_attempts, show_answers, test_id),
            )

            cursor.execute("DELETE FROM theory_test_groups WHERE test_id = ?", (test_id,))
            for group_name in groups:
                if group_name.strip():
                    cursor.execute("INSERT INTO theory_test_groups (test_id, group_name) VALUES (?, ?)", (test_id, group_name))

            cursor.execute("DELETE FROM theory_test_teachers WHERE test_id = ?", (test_id,))
            for teacher in teachers:
                if teacher.strip():
                    cursor.execute("INSERT INTO theory_test_teachers (test_id, teacher_username) VALUES (?, ?)", (test_id, teacher))

            conn.commit()
            conn.close()
            log_activity(username, f"edited theory test settings for test {test_id}")
            return redirect(url_for("manage_tests"))

        cursor.execute("SELECT group_name FROM theory_test_groups WHERE test_id = ?", (test_id,))
        current_groups = {row[0] for row in cursor.fetchall()}
        cursor.execute("SELECT teacher_username FROM theory_test_teachers WHERE test_id = ?", (test_id,))
        current_teachers = {row[0] for row in cursor.fetchall()}
        all_groups = get_groups()
        all_teachers = get_teachers()
        conn.close()
        return render_template("edit_test.html", test=test, current_groups=current_groups, all_groups=all_groups, all_teachers=all_teachers, current_teachers=current_teachers)

    @app.route("/manage_tests/<int:test_id>/toggle", methods=["POST"])
    def toggle_test(test_id):
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))
        if get_user_role(username) not in ["teacher", "admin"]:
            return "Access denied", 403

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT is_active FROM theory_tests WHERE id = ?", (test_id,))
        row = cursor.fetchone()
        if row:
            new_state = 0 if row[0] else 1
            cursor.execute("UPDATE theory_tests SET is_active = ? WHERE id = ?", (new_state, test_id))
            conn.commit()
        conn.close()
        return redirect(url_for("manage_tests"))

    @app.route("/manage_tests/<int:test_id>/delete", methods=["POST"])
    def delete_test(test_id):
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))
        if get_user_role(username) not in ["teacher", "admin"]:
            return "Access denied", 403

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT title FROM theory_tests WHERE id = ?", (test_id,))
        test_row = cursor.fetchone()
        test_title = test_row[0] if test_row else f"Test {test_id}"
        cursor.execute("DELETE FROM theory_answers WHERE submission_id IN (SELECT id FROM theory_submissions WHERE test_id = ?)", (test_id,))
        cursor.execute("DELETE FROM theory_submissions WHERE test_id = ?", (test_id,))
        cursor.execute("DELETE FROM theory_options WHERE question_id IN (SELECT id FROM theory_questions WHERE test_id = ?)", (test_id,))
        cursor.execute("DELETE FROM theory_questions WHERE test_id = ?", (test_id,))
        cursor.execute("DELETE FROM theory_test_groups WHERE test_id = ?", (test_id,))
        cursor.execute("DELETE FROM task_groups WHERE task_id IN (SELECT id FROM tasks WHERE theory_test_id = ?)", (test_id,))
        cursor.execute("DELETE FROM tasks WHERE theory_test_id = ?", (test_id,))
        cursor.execute("DELETE FROM theory_tests WHERE id = ?", (test_id,))
        conn.commit()
        conn.close()
        log_activity(username, f"deleted theory test '{test_title}' and all related submissions")
        return redirect(url_for("manage_tests"))
