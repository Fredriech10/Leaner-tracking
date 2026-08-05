import os
from datetime import datetime

from flask import redirect, render_template, request, send_file, session, url_for
from markupsafe import escape

from app.database import get_db, get_groups, get_teachers, get_user_role, log_activity
from app.helper_common import resolve_interactive_learning_path, safe_int


def register_lesson_routes(app):
    @app.route("/interactive_learning_files/<path:relative_path>")
    def download_interactive_learning_file(relative_path):
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))

        file_path = resolve_interactive_learning_path(relative_path)
        if not file_path:
            return "File not found", 404

        return send_file(file_path, as_attachment=True, download_name=os.path.basename(file_path))

    @app.route("/manage_lessons")
    def manage_lessons():
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
            HAVING COALESCE(content_count, 0) > 0
            ORDER BY t.created_at DESC
            """
        )
        lessons = cursor.fetchall()
        groups = get_groups(username) if role == "teacher" else get_groups()
        teachers = get_teachers()
        teacher_checkboxes = "".join(
            f'<label style="font-weight:normal;display:inline-flex;align-items:center;gap:5px;">'
            f'<input type="checkbox" name="teachers" value="{escape(teacher[0])}"> {escape(teacher[1] or teacher[0])}</label>'
            for teacher in teachers
        )
        lesson_list = ""
        for lesson in lessons:
            lesson_id = lesson[0]
            lesson_title = escape(lesson[1] or "")
            lesson_subject = escape(lesson[2] or "")
            assign_date = lesson[3] or "—"
            time_limit_val = lesson[4] or 0
            is_active = bool(lesson[5])
            groups_text = escape(lesson[6] or "All Groups")
            total_items = lesson[7] or 0
            show_answers = bool(lesson[10])
            teachers_text = escape(lesson[11] or "All Teachers")
            content_count = lesson[12] or 0
            test_question_count = max(0, total_items - content_count)
            status_badge = '<span class="badge-active">Active</span>' if is_active else '<span class="badge-inactive">Inactive</span>'
            toggle_label = "Deactivate" if is_active else "Activate"
            toggle_class = "btn-warning" if is_active else "btn-success"
            lesson_list += f"""
            <tr>
                <td>{lesson_title}</td>
                <td>{lesson_subject or '—'}</td>
                <td>{groups_text}</td>
                <td>{teachers_text}</td>
                <td>{content_count}</td>
                <td>{test_question_count}</td>
                <td>{assign_date}</td>
                <td>{time_limit_val if time_limit_val else 'No limit'}</td>
                <td>{'✔ Yes' if show_answers else '✘ No'}</td>
                <td>{status_badge}</td>
                <td style="white-space:nowrap; vertical-align:middle;">
                    <div class="action-cell">
                    <a href="/manage_lessons/{lesson_id}/questions" class="btn btn-primary" title="Edit lesson">✏️</a>
                    <a href="/manage_tests/{lesson_id}/edit" class="btn btn-warning" title="Edit settings">⚙️</a>
                    <form method="post" action="/manage_lessons/{lesson_id}/toggle" style="display:inline-flex; margin:0;">
                        <button type="submit" class="btn {toggle_class}" title="{toggle_label}">{'⏸' if is_active else '▶'}</button>
                    </form>
                    <form method="post" action="/manage_lessons/{lesson_id}/delete" style="display:inline-flex; margin:0;"
                          onsubmit="return confirm('Delete this lesson setup, its questions, and all learner submissions?')">
                        <button type="submit" class="btn btn-danger" title="Delete lesson">🗑</button>
                    </form>
                    </div>
                </td>
            </tr>
            """
        conn.close()

        return render_template(
            "manage_lessons.html",
            groups=groups,
            teacher_checkboxes=teacher_checkboxes,
            test_list=lesson_list,
            page_title="Lesson Setup",
            page_intro="Create and manage slide-based lessons here. Theory Tests remain the plain question-only tests.",
        )

    @app.route("/manage_lesson_tests")
    def manage_lesson_tests():
        return redirect(url_for("manage_lessons"))

    @app.route("/manage_lessons/create", methods=["POST"])
    def create_lesson():
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))
        if get_user_role(username) not in ["teacher", "admin"]:
            return "Access denied", 403

        title = request.form.get("title", "").strip()
        subject = request.form.get("subject", "").strip()
        assign_date = request.form.get("assign_date", "").strip()
        time_limit = safe_int(request.form.get("time_limit"), 0)
        allow_multiple = 1 if request.form.get("allow_multiple") else 0
        max_attempts = safe_int(request.form.get("max_attempts"), 1)
        show_answers = 1 if request.form.get("show_answers") else 0
        groups = request.form.getlist("groups")
        teachers = request.form.getlist("teachers")

        if not title or not assign_date:
            return "Title and assign date are required", 400

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
        lesson_id = cursor.lastrowid

        for group_name in groups:
            if group_name.strip():
                cursor.execute("INSERT INTO theory_test_groups (test_id, group_name) VALUES (?, ?)", (lesson_id, group_name))
        for teacher_username in teachers:
            if teacher_username.strip():
                cursor.execute("INSERT INTO theory_test_teachers (test_id, teacher_username) VALUES (?, ?)", (lesson_id, teacher_username))

        conn.commit()
        conn.close()
        log_activity(username, f"created theory lesson '{title}'")
        return redirect(url_for("manage_lesson_questions", test_id=lesson_id))

    @app.route("/manage_lessons/<int:lesson_id>/toggle", methods=["POST"])
    def toggle_lesson(lesson_id):
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))
        if get_user_role(username) not in ["teacher", "admin"]:
            return "Access denied", 403

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT is_active FROM theory_tests WHERE id = ?", (lesson_id,))
        row = cursor.fetchone()
        if row:
            cursor.execute("UPDATE theory_tests SET is_active = ? WHERE id = ?", (0 if row[0] else 1, lesson_id))
            conn.commit()
        conn.close()
        return redirect(url_for("manage_lessons"))

    @app.route("/manage_lessons/<int:lesson_id>/delete", methods=["POST"])
    def delete_lesson(lesson_id):
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))
        if get_user_role(username) not in ["teacher", "admin"]:
            return "Access denied", 403

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT title FROM theory_tests WHERE id = ?", (lesson_id,))
        row = cursor.fetchone()
        lesson_title = row[0] if row else f"Lesson {lesson_id}"
        cursor.execute("DELETE FROM theory_answers WHERE submission_id IN (SELECT id FROM theory_submissions WHERE test_id = ?)", (lesson_id,))
        cursor.execute("DELETE FROM theory_submissions WHERE test_id = ?", (lesson_id,))
        cursor.execute("DELETE FROM theory_progress WHERE test_id = ?", (lesson_id,))
        cursor.execute("DELETE FROM theory_options WHERE question_id IN (SELECT id FROM theory_questions WHERE test_id = ?)", (lesson_id,))
        cursor.execute("DELETE FROM theory_questions WHERE test_id = ?", (lesson_id,))
        cursor.execute("DELETE FROM theory_test_groups WHERE test_id = ?", (lesson_id,))
        cursor.execute("DELETE FROM theory_test_teachers WHERE test_id = ?", (lesson_id,))
        cursor.execute("DELETE FROM theory_tests WHERE id = ?", (lesson_id,))
        conn.commit()
        conn.close()
        log_activity(username, f"deleted lesson setup '{lesson_title}'")
        return redirect(url_for("manage_lessons"))

    @app.route("/manage_lessons/<int:lesson_id>/checkpoints", methods=["GET", "POST"])
    def manage_lesson_checkpoints(lesson_id):
        return redirect(url_for("manage_lesson_questions", test_id=lesson_id))

    @app.route("/lessons")
    def learner_lessons():
        return redirect(url_for("lesson_tests"))

    @app.route("/lesson/<int:lesson_id>", methods=["GET", "POST"])
    def lesson_view(lesson_id):
        return redirect(url_for("take_test", test_id=lesson_id), code=307 if request.method == "POST" else 302)
