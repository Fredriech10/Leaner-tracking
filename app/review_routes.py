import sqlite3
from collections import defaultdict

from flask import flash, redirect, render_template, request, session, url_for

from app.database import get_db, get_grades, get_groups, get_user_role
from app.helper_theory import (
    build_match_review_rows,
    get_fill_in_accepted_answers,
    get_true_false_option_data,
    normalize_review_text,
    parse_true_false_answer_text,
    regrade_theory_question_answers,
)


def register_review_routes(app):
    @app.route("/response_review")
    def response_review():
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))
        role = get_user_role(username)
        if role not in ["teacher", "admin"]:
            return "Access denied", 403

        review_type = (request.args.get("type") or "theory").strip()
        selected_group = (request.args.get("group") or "").strip()
        selected_grade = (request.args.get("grade") or "").strip()
        selected_item = (request.args.get("item") or "").strip()
        groups = get_groups(username if role == "teacher" else None, grade=selected_grade)
        grade_options = get_grades(username if role == "teacher" else None)

        conn = get_db()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        available_items = []
        if review_type == "theory":
            query = """
                SELECT DISTINCT tt.id, COALESCE(tt.subject || ' - ', '') || tt.title
                FROM theory_submissions s
                JOIN theory_tests tt ON tt.id = s.test_id
                JOIN users u ON u.username = s.username
                WHERE u.role = 'student'
            """
            params = []
            if role == "teacher":
                query += " AND u.teacher_username = ?"
                params.append(username)
            if selected_grade:
                query += " AND u.grade = ?"
                params.append(selected_grade)
            if selected_group:
                query += " AND u.group_name = ?"
                params.append(selected_group)
            query += " ORDER BY tt.title"
            cursor.execute(query, params)
            available_items = [(str(row[0]), row[1]) for row in cursor.fetchall()]

        if not selected_item and available_items:
            selected_item = available_items[0][0]

        question_summaries = []
        item_label = ""
        selected_test_id = int(selected_item) if selected_item and selected_item.isdigit() else None

        if review_type == "theory" and selected_test_id:
            cursor.execute("SELECT title, subject FROM theory_tests WHERE id = ?", (selected_test_id,))
            test_row = cursor.fetchone()
            if test_row:
                item_label = f"{test_row['subject']} - {test_row['title']}" if test_row["subject"] else test_row["title"]

            submission_query = """
                SELECT s.id, s.username
                FROM theory_submissions s
                JOIN (
                    SELECT username, MAX(submitted_at) AS latest_submitted_at
                    FROM theory_submissions
                    WHERE test_id = ?
                    GROUP BY username
                ) latest ON latest.username = s.username AND latest.latest_submitted_at = s.submitted_at
                JOIN users u ON u.username = s.username
                WHERE s.test_id = ?
            """
            submission_params = [selected_test_id, selected_test_id]
            if role == "teacher":
                submission_query += " AND u.teacher_username = ?"
                submission_params.append(username)
            if selected_grade:
                submission_query += " AND u.grade = ?"
                submission_params.append(selected_grade)
            if selected_group:
                submission_query += " AND u.group_name = ?"
                submission_params.append(selected_group)
            cursor.execute(submission_query, submission_params)
            latest_submissions = cursor.fetchall()
            submission_ids = [row["id"] for row in latest_submissions]

            cursor.execute(
                """
                SELECT id, question_text, question_type, marks
                FROM theory_questions
                WHERE test_id = ?
                ORDER BY order_index
                """,
                (selected_test_id,),
            )
            questions = cursor.fetchall()

            answers_by_question = defaultdict(list)
            if submission_ids:
                placeholders = ",".join("?" for _ in submission_ids)
                cursor.execute(
                    f"""
                    SELECT question_id, answer_text, is_correct, marks_awarded
                    FROM theory_answers
                    WHERE submission_id IN ({placeholders})
                    """,
                    submission_ids,
                )
                for row in cursor.fetchall():
                    answers_by_question[row["question_id"]].append(dict(row))

            for question in questions:
                q_id = question["id"]
                q_type = question["question_type"]
                marks = question["marks"] or 0
                cursor.execute(
                    """
                    SELECT id, option_text, is_correct, match_pair
                    FROM theory_options
                    WHERE question_id = ?
                    ORDER BY id
                    """,
                    (q_id,),
                )
                options = cursor.fetchall()
                answers = answers_by_question.get(q_id, [])
                accepted_answers = []
                option_rows = []
                correct_count = sum(1 for answer in answers if answer["is_correct"])

                if q_type == "true_false":
                    correct_choice, accepted_corrections = get_true_false_option_data(options)
                    accepted_answers = ([correct_choice] if correct_choice else []) + accepted_corrections
                    buckets = defaultdict(int)
                    for answer in answers:
                        selected, correction = parse_true_false_answer_text(answer["answer_text"])
                        label = f"{selected} | {correction}" if correction else (selected or "No answer")
                        buckets[label] += 1
                    total_answers = len(answers)
                    accepted_correction_keys = {normalize_review_text(item) for item in accepted_corrections}
                    for label, count in sorted(buckets.items(), key=lambda item: (-item[1], item[0])):
                        correction_value = label.split(" | ", 1)[1] if " | " in label else ""
                        is_existing_accepted = correction_value and normalize_review_text(correction_value) in accepted_correction_keys
                        option_rows.append(
                            {
                                "label": label,
                                "count": count,
                                "pct": round((count / total_answers) * 100) if total_answers else 0,
                                "is_correct": label == correct_choice,
                                "acceptable_answer": correction_value if correction_value and not is_existing_accepted else "",
                                "remove_answer": correction_value if is_existing_accepted else "",
                                "action_label": "Use correction" if correction_value else "",
                            }
                        )
                elif q_type == "fill_in":
                    accepted_answers = get_fill_in_accepted_answers(options)
                    buckets = defaultdict(int)
                    for answer in answers:
                        buckets[answer["answer_text"] or "No answer"] += 1
                    total_answers = len(answers)
                    accepted_keys = {normalize_review_text(item) for item in accepted_answers}
                    for label, count in sorted(buckets.items(), key=lambda item: (-item[1], item[0])):
                        normalized = normalize_review_text(label)
                        option_rows.append(
                            {
                                "label": label,
                                "count": count,
                                "pct": round((count / total_answers) * 100) if total_answers else 0,
                                "is_correct": normalized in accepted_keys,
                                "acceptable_answer": label if label and label != "No answer" and normalized not in accepted_keys else "",
                                "remove_answer": label if label and normalized in accepted_keys else "",
                                "action_label": "Use response" if label and label != "No answer" else "",
                            }
                        )
                elif q_type == "match":
                    orientation_rows = None
                    for answer in answers:
                        orientation_rows, _ = build_match_review_rows(options, answer["answer_text"] or "")
                        if orientation_rows:
                            break
                    if orientation_rows is None:
                        orientation_rows, _ = build_match_review_rows(options, "")
                    for row_data in orientation_rows:
                        responses = []
                        for answer in answers:
                            learner_rows, _ = build_match_review_rows(options, answer["answer_text"] or "")
                            for learner_row in learner_rows:
                                if learner_row["left"] == row_data["left"] and learner_row["learner_match"] != "No answer":
                                    responses.append(learner_row["learner_match"])
                                    break
                        option_rows.append(
                            {
                                "left": row_data["left"],
                                "accepted": row_data["correct_match"],
                                "responses": responses,
                            }
                        )
                else:
                    correct_values = {option["option_text"] for option in options if option["is_correct"] == 1}
                    accepted_answers = list(correct_values)
                    buckets = defaultdict(int)
                    for answer in answers:
                        buckets[answer["answer_text"] or "No answer"] += 1
                    total_answers = len(answers)
                    for label, count in sorted(buckets.items(), key=lambda item: (-item[1], item[0])):
                        option_rows.append(
                            {
                                "label": label,
                                "count": count,
                                "pct": round((count / total_answers) * 100) if total_answers else 0,
                                "is_correct": label in correct_values,
                                "acceptable_answer": "",
                                "remove_answer": "",
                            }
                        )

                question_summaries.append(
                    {
                        "question_id": q_id,
                        "question": question["question_text"],
                        "type": q_type,
                        "marks": marks,
                        "responses": len(answers),
                        "correct_pct": round((correct_count / len(answers)) * 100) if answers else 0,
                        "accepted_answers": accepted_answers,
                        "options": option_rows,
                    }
                )

        conn.close()
        return render_template(
            "response_review.html",
            review_type=review_type,
            groups=groups,
            grade_options=grade_options,
            selected_grade=selected_grade,
            selected_group=selected_group,
            selected_item=selected_item,
            available_items=available_items,
            item_label=item_label,
            question_summaries=question_summaries,
            selected_test_id=selected_test_id,
            can_manage_reviews=role in ["teacher", "admin"],
        )

    @app.route("/response_review/learner")
    def response_review_learner():
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))
        role = get_user_role(username)
        if role not in ["teacher", "admin"]:
            return "Access denied", 403

        learner_username = (request.args.get("learner") or "").strip()
        test_id = request.args.get("item", type=int)
        if not learner_username or not test_id:
            return redirect(url_for("response_review"))

        conn = get_db()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT full_name, group_name
            FROM users
            WHERE username = ?
            """,
            (learner_username,),
        )
        learner_row = cursor.fetchone()
        if not learner_row:
            conn.close()
            return "Learner not found", 404

        cursor.execute(
            """
            SELECT s.id, s.score, s.total, s.percentage, s.submitted_at, tt.title, tt.subject
            FROM theory_submissions s
            JOIN theory_tests tt ON tt.id = s.test_id
            WHERE s.username = ? AND s.test_id = ?
            ORDER BY s.submitted_at DESC
            LIMIT 1
            """,
            (learner_username, test_id),
        )
        submission = cursor.fetchone()
        if not submission:
            conn.close()
            return render_template(
                "response_review_learner.html",
                learner_name=learner_row["full_name"] or learner_username,
                learner_username=learner_username,
                learner_group=learner_row["group_name"] or "—",
                item_label="No submission found",
                review_rows=[],
                score_summary=None,
                can_manage_reviews=True,
            )

        cursor.execute(
            """
            SELECT q.question_text, q.question_type, q.marks, a.answer_text, a.is_correct, a.marks_awarded, a.question_id
            FROM theory_answers a
            JOIN theory_questions q ON q.id = a.question_id
            WHERE a.submission_id = ?
            ORDER BY q.order_index
            """,
            (submission["id"],),
        )
        answer_rows = cursor.fetchall()

        review_rows = []
        for row in answer_rows:
            cursor.execute(
                """
                SELECT id, option_text, is_correct, match_pair
                FROM theory_options
                WHERE question_id = ?
                ORDER BY id
                """,
                (row["question_id"],),
            )
            options = cursor.fetchall()
            correct_answers = []
            match_rows = []
            if row["question_type"] == "true_false":
                correct_choice, accepted_corrections = get_true_false_option_data(options)
                correct_answers = ([correct_choice] if correct_choice else []) + accepted_corrections
            elif row["question_type"] == "fill_in":
                correct_answers = get_fill_in_accepted_answers(options)
            elif row["question_type"] == "match":
                match_rows, _ = build_match_review_rows(options, row["answer_text"])
            else:
                correct_answers = [option["option_text"] for option in options if option["is_correct"] == 1]

            suggested_acceptable_answer = ""
            if row["question_type"] == "true_false":
                _selected, submitted_correction = parse_true_false_answer_text(row["answer_text"] or "")
                if submitted_correction:
                    suggested_acceptable_answer = submitted_correction
            elif row["question_type"] == "fill_in":
                suggested_acceptable_answer = (row["answer_text"] or "").strip()

            review_rows.append(
                {
                    "question_id": row["question_id"],
                    "question": row["question_text"],
                    "type": row["question_type"],
                    "marks": row["marks"],
                    "answer": row["answer_text"] or "No answer",
                    "correct": row["is_correct"],
                    "marks_awarded": row["marks_awarded"],
                    "correct_answers": correct_answers,
                    "match_rows": match_rows,
                    "suggested_acceptable_answer": suggested_acceptable_answer,
                }
            )

        conn.close()
        return render_template(
            "response_review_learner.html",
            learner_name=learner_row["full_name"] or learner_username,
            learner_username=learner_username,
            learner_group=learner_row["group_name"] or "—",
            item_label=f"{submission['subject']} - {submission['title']}" if submission["subject"] else submission["title"],
            review_rows=review_rows,
            score_summary={
                "score": submission["score"],
                "total": submission["total"],
                "percentage": submission["percentage"],
                "submitted_at": submission["submitted_at"][:16] if submission["submitted_at"] else "—",
            },
            can_manage_reviews=True,
        )

    @app.route("/response_review/true_false_accept", methods=["POST"])
    def response_review_true_false_accept():
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))
        if get_user_role(username) not in ["teacher", "admin"]:
            return "Access denied", 403

        test_id = request.form.get("test_id", type=int)
        question_id = request.form.get("question_id", type=int)
        acceptable_answer = (request.form.get("acceptable_answer") or "").strip()
        submitted_answer = (request.form.get("submitted_answer") or "").strip()
        selected_group = (request.form.get("selected_group") or "").strip()
        selected_grade = (request.form.get("selected_grade") or "").strip()
        learner_username = (request.form.get("learner_username") or "").strip()
        if not (test_id and question_id):
            flash("Accepted answer could not be added.", "error")
            return redirect(url_for("response_review"))

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT question_type FROM theory_questions WHERE id = ?", (question_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            flash("Question not found.", "error")
            return redirect(url_for("response_review"))
        q_type = row[0]

        if q_type == "true_false" and not acceptable_answer:
            _selected, derived_correction = parse_true_false_answer_text(submitted_answer)
            acceptable_answer = derived_correction
        elif q_type == "fill_in" and not acceptable_answer:
            acceptable_answer = submitted_answer.strip()

        if not acceptable_answer:
            conn.close()
            flash("No learner response was available to add.", "error")
            if learner_username:
                return redirect(url_for("response_review_learner", learner=learner_username, item=test_id))
            return redirect(url_for("response_review", type="theory", grade=selected_grade, group=selected_group, item=test_id))

        if q_type == "true_false":
            cursor.execute(
                """
                SELECT 1
                FROM theory_options
                WHERE question_id = ?
                  AND match_pair = 'correction'
                  AND LOWER(TRIM(option_text)) = LOWER(TRIM(?))
                LIMIT 1
                """,
                (question_id, acceptable_answer),
            )
            if cursor.fetchone():
                conn.close()
                flash("That correction is already accepted.", "success")
                if learner_username:
                    return redirect(url_for("response_review_learner", learner=learner_username, item=test_id))
                return redirect(url_for("response_review", type="theory", grade=selected_grade, group=selected_group, item=test_id))
            cursor.execute(
                """
                INSERT INTO theory_options (question_id, option_text, is_correct, match_pair)
                VALUES (?, ?, 0, 'correction')
                """,
                (question_id, acceptable_answer),
            )
        elif q_type == "fill_in":
            cursor.execute(
                """
                SELECT 1
                FROM theory_options
                WHERE question_id = ?
                  AND is_correct = 1
                  AND LOWER(TRIM(option_text)) = LOWER(TRIM(?))
                LIMIT 1
                """,
                (question_id, acceptable_answer),
            )
            if cursor.fetchone():
                conn.close()
                flash("That answer is already accepted.", "success")
                if learner_username:
                    return redirect(url_for("response_review_learner", learner=learner_username, item=test_id))
                return redirect(url_for("response_review", type="theory", grade=selected_grade, group=selected_group, item=test_id))
            cursor.execute(
                """
                INSERT INTO theory_options (question_id, option_text, is_correct)
                VALUES (?, ?, 1)
                """,
                (question_id, acceptable_answer),
            )
        conn.commit()
        conn.close()

        updated = regrade_theory_question_answers(test_id, question_id, selected_group or None, learner_username or None)
        flash(f"Accepted answer added. {updated} learner answer(s) regraded.", "success")
        if learner_username:
            return redirect(url_for("response_review_learner", learner=learner_username, item=test_id))
        return redirect(url_for("response_review", type="theory", grade=selected_grade, group=selected_group, item=test_id))

    @app.route("/response_review/accepted_answer_remove", methods=["POST"])
    def response_review_accepted_answer_remove():
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))
        if get_user_role(username) not in ["teacher", "admin"]:
            return "Access denied", 403

        test_id = request.form.get("test_id", type=int)
        question_id = request.form.get("question_id", type=int)
        remove_answer = (request.form.get("remove_answer") or "").strip()
        selected_group = (request.form.get("selected_group") or "").strip()
        selected_grade = (request.form.get("selected_grade") or "").strip()
        if not (test_id and question_id and remove_answer):
            flash("Accepted answer could not be removed.", "error")
            return redirect(url_for("response_review"))

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            """
            DELETE FROM theory_options
            WHERE question_id = ? AND option_text = ? AND (is_correct = 1 OR match_pair = 'correction')
            """,
            (question_id, remove_answer),
        )
        conn.commit()
        conn.close()

        updated = regrade_theory_question_answers(test_id, question_id, selected_group or None)
        flash(f"Accepted answer removed. {updated} learner answer(s) regraded.", "success")
        return redirect(url_for("response_review", type="theory", grade=selected_grade, group=selected_group, item=test_id))
