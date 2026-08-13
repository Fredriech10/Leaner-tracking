from datetime import datetime

from flask import redirect, render_template, request, session, url_for

from app.database import get_db, get_user_role

LESSON_SLIDE_TYPES = ("content_slide", "title_slide", "heading_slide")


def register_theory_learner_routes(app):
    @app.route("/tests")
    def learner_tests():
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT group_name FROM users WHERE username = ?", (username,))
        row = cursor.fetchone()
        user_group = row[0] if row else None

        cursor.execute(
            """
            SELECT t.id, t.title, t.subject, t.time_limit,
                   best.best_percentage,
                   sub.id as latest_submission_id,
                   t.allow_multiple, t.max_attempts,
                   COALESCE(cnt.attempt_count, 0) as attempt_count,
                   COALESCE(qstats.content_count, 0) as content_count,
                   COALESCE(qstats.question_count, 0) as question_count,
                   COALESCE(prog.current_slide, 0) as current_slide,
                   COALESCE(prog.completed, 0) as progress_completed,
                   COALESCE(prog.max_slide, 0) as max_slide,
                   COALESCE(prog.time_spent_seconds, 0) as progress_seconds
            FROM theory_tests t
            LEFT JOIN (
                SELECT test_id, MAX(percentage) as best_percentage
                FROM theory_submissions WHERE username = ?
                GROUP BY test_id
            ) best ON t.id = best.test_id
            LEFT JOIN (
                SELECT test_id, id, percentage,
                       ROW_NUMBER() OVER (PARTITION BY test_id ORDER BY submitted_at DESC) as rn
                FROM theory_submissions WHERE username = ?
            ) sub ON t.id = sub.test_id AND sub.rn = 1
            LEFT JOIN (
                SELECT test_id, COUNT(*) as attempt_count
                FROM theory_submissions WHERE username = ?
                GROUP BY test_id
            ) cnt ON t.id = cnt.test_id
            LEFT JOIN (
                SELECT test_id,
                       SUM(CASE WHEN question_type IN ('content_slide', 'title_slide', 'heading_slide') THEN 1 ELSE 0 END) as content_count,
                       COUNT(*) as question_count
                FROM theory_questions
                GROUP BY test_id
            ) qstats ON t.id = qstats.test_id
            LEFT JOIN theory_progress prog ON prog.test_id = t.id AND prog.username = ?
            WHERE t.is_active = 1
              AND COALESCE(qstats.content_count, 0) = 0
              AND (
                  NOT EXISTS (SELECT 1 FROM theory_test_groups WHERE test_id = t.id)
                  OR EXISTS (SELECT 1 FROM theory_test_groups WHERE test_id = t.id AND group_name = ?)
              )
            GROUP BY t.id
            ORDER BY
                CASE WHEN best.best_percentage IS NULL THEN 0 ELSE 1 END,
                t.created_at DESC
            """,
            (username, username, username, username, user_group),
        )
        tests = cursor.fetchall()
        conn.close()
        return render_template("learner_tests.html", tests=tests)

    @app.route("/lesson_tests")
    def lesson_tests():
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT group_name FROM users WHERE username = ?", (username,))
        row = cursor.fetchone()
        user_group = row[0] if row else None

        cursor.execute(
            """
            SELECT t.id, t.title, t.subject, t.time_limit,
                   best.best_percentage,
                   sub.id as latest_submission_id,
                   t.allow_multiple, t.max_attempts,
                   COALESCE(cnt.attempt_count, 0) as attempt_count,
                   COALESCE(qstats.content_count, 0) as content_count,
                   COALESCE(qstats.total_questions, 0) as total_questions,
                   COALESCE(prog.current_slide, 0) as current_slide,
                   COALESCE(prog.max_slide, 0) as max_slide,
                   COALESCE(prog.time_spent_seconds, 0) as progress_seconds
            FROM theory_tests t
            LEFT JOIN (
                SELECT test_id, MAX(percentage) as best_percentage
                FROM theory_submissions WHERE username = ?
                GROUP BY test_id
            ) best ON t.id = best.test_id
            LEFT JOIN (
                SELECT test_id, id, percentage,
                       ROW_NUMBER() OVER (PARTITION BY test_id ORDER BY submitted_at DESC) as rn
                FROM theory_submissions WHERE username = ?
            ) sub ON t.id = sub.test_id AND sub.rn = 1
            LEFT JOIN (
                SELECT test_id, COUNT(*) as attempt_count
                FROM theory_submissions WHERE username = ?
                GROUP BY test_id
            ) cnt ON t.id = cnt.test_id
            LEFT JOIN (
                SELECT test_id,
                       SUM(CASE WHEN question_type IN ('content_slide', 'title_slide', 'heading_slide') THEN 1 ELSE 0 END) as content_count,
                       COUNT(*) as total_questions
                FROM theory_questions
                GROUP BY test_id
            ) qstats ON t.id = qstats.test_id
            LEFT JOIN theory_progress prog ON prog.test_id = t.id AND prog.username = ?
            WHERE t.is_active = 1
              AND COALESCE(qstats.content_count, 0) > 0
              AND (
                  NOT EXISTS (SELECT 1 FROM theory_test_groups WHERE test_id = t.id)
                  OR EXISTS (SELECT 1 FROM theory_test_groups WHERE test_id = t.id AND group_name = ?)
              )
            GROUP BY t.id
            ORDER BY t.created_at DESC
            """,
            (username, username, username, username, user_group),
        )
        tests = cursor.fetchall()
        conn.close()
        return render_template("learner_lesson_tests.html", tests=tests)

    @app.route("/my_tasks")
    def learner_tasks():
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))

        conn = get_db()
        cursor = conn.cursor()
        role = get_user_role(username)
        cursor.execute("SELECT group_name FROM users WHERE username = ?", (username,))
        row = cursor.fetchone()
        user_group = row[0] if row else None
        today = datetime.now().date().isoformat()

        if role in ["teacher", "admin"]:
            cursor.execute(
                """
                SELECT t.id, t.name, t.assign_date, t.task_type, t.allow_multiple,
                       t.max_attempts, t.is_active, t.theory_test_id, t.subject_id, s.name,
                       COALESCE(t.practical_mode, 'upload')
                FROM tasks t
                JOIN subjects s ON t.subject_id = s.id
                ORDER BY t.assign_date, s.name, t.name
                """
            )
        else:
            cursor.execute(
                """
                SELECT t.id, t.name, t.assign_date, t.task_type, t.allow_multiple,
                       t.max_attempts, t.is_active, t.theory_test_id, t.subject_id, s.name,
                       COALESCE(t.practical_mode, 'upload')
                FROM tasks t
                JOIN subjects s ON t.subject_id = s.id
                JOIN task_groups tg ON t.id = tg.task_id
                WHERE tg.group_name = ? AND t.assign_date <= ? AND t.is_active = 1
                ORDER BY t.assign_date, s.name, t.name
                """,
                (user_group, today),
            )

        task_rows = cursor.fetchall()
        tasks = []
        for task_id, task_name, assign_date, task_type, allow_multiple, max_attempts, is_active, theory_test_id, subject_id, subject_name, practical_mode in task_rows:
            cursor.execute(
                "SELECT COUNT(*), COALESCE(MAX(score), 0) FROM results WHERE username = ? AND subject = ? AND task = ?",
                (username, subject_name, task_name),
            )
            submission_count, best_score = cursor.fetchone()
            tasks.append(
                {
                    "id": task_id,
                    "name": task_name,
                    "assign_date": assign_date,
                    "task_type": task_type,
                    "allow_multiple": allow_multiple,
                    "max_attempts": max_attempts,
                    "is_active": is_active,
                    "theory_test_id": theory_test_id,
                    "subject_id": subject_id,
                    "subject": subject_name,
                    "practical_mode": practical_mode,
                    "submission_count": submission_count or 0,
                    "best_score": best_score,
                }
            )

        conn.close()
        return render_template("learner_tasks.html", tasks=tasks, username=username)

    @app.route("/preview_test/<int:test_id>")
    def preview_test(test_id):
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))
        if get_user_role(username) not in ["teacher", "admin"]:
            return "Access denied", 403

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id, title, subject, time_limit, allow_multiple, max_attempts, show_answers, background_image, COALESCE(background_fit, 'cover') FROM theory_tests WHERE id = ?", (test_id,))
        test = cursor.fetchone()
        if not test:
            conn.close()
            return "Test not found", 404

        cursor.execute(
            """
            SELECT id, question_text, question_type, marks
            FROM theory_questions WHERE test_id = ? ORDER BY order_index
            """,
            (test_id,),
        )
        questions = cursor.fetchall()

        questions_with_options = []
        for question in questions:
            cursor.execute("SELECT id, option_text, is_correct, match_pair FROM theory_options WHERE question_id = ?", (question[0],))
            options = list(cursor.fetchall())
            if question[2] == "match":
                options = sorted(options, key=lambda option: option[0])
            questions_with_options.append({"q": question, "options": options})
        content_slide_count = sum(1 for question in questions if question[2] in LESSON_SLIDE_TYPES)
        conn.close()
        return render_template(
            "take_test.html",
            test=test,
            questions=questions_with_options,
            attempt_number=0,
            is_preview=True,
            initial_slide=0,
            has_content_slides=content_slide_count > 0,
            content_slide_count=content_slide_count,
            question_count=len(questions) - content_slide_count,
            is_lesson_only=content_slide_count > 0 and len(questions) == content_slide_count,
            max_slide=0,
            lesson_completed=False,
        )

    @app.route("/tests/<int:test_id>/progress", methods=["POST"])
    def save_theory_progress(test_id):
        username = session.get("username")
        if not username:
            return {"ok": False, "error": "not_logged_in"}, 401

        payload = request.get_json(silent=True) or {}
        current_slide = int(payload.get("current_slide", 0) or 0)
        max_slide = int(payload.get("max_slide", current_slide) or 0)
        time_delta = max(0, int(payload.get("time_delta", 0) or 0))
        completed = 1 if payload.get("completed") else 0

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM theory_tests WHERE id = ?", (test_id,))
        if not cursor.fetchone():
            conn.close()
            return {"ok": False, "error": "not_found"}, 404

        cursor.execute(
            """
            INSERT INTO theory_progress (test_id, username, current_slide, max_slide, time_spent_seconds, completed, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(test_id, username) DO UPDATE SET
                current_slide = excluded.current_slide,
                max_slide = MAX(theory_progress.max_slide, excluded.max_slide),
                time_spent_seconds = theory_progress.time_spent_seconds + excluded.time_spent_seconds,
                completed = CASE WHEN excluded.completed = 1 THEN 1 ELSE theory_progress.completed END,
                updated_at = excluded.updated_at
            """,
            (test_id, username, current_slide, max_slide, time_delta, completed, datetime.now().isoformat()),
        )
        conn.commit()
        conn.close()
        return {"ok": True}
