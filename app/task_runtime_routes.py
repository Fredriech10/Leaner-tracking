import os
from datetime import datetime

from flask import redirect, render_template, request, send_file, session, url_for
from io import BytesIO
from markupsafe import escape

from app.database import get_db, get_groups, get_teachers, get_user_role, log_activity, save_result, update_weakness
from app.helper_marking import get_marking_scripts, mark_file
from app.practical_simulators import get_simulator_catalog, get_simulator_definition, score_simulator_attempt
from app.runtime import update_active_user


def register_task_runtime_routes(app):
    @app.route("/tasks/<int:task_id>/edit", methods=["GET", "POST"])
    def edit_task(task_id):
        username = session.get("username")
        if not username or get_user_role(username) not in ["teacher", "admin"]:
            return "Access denied", 403

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT t.id, t.name, t.assign_date, t.marking_script, t.question_text, t.subject_id,
                   t.sample_file, t.sample_file_name, t.allow_multiple, t.max_attempts,
                   t.practical_mode, t.simulator_key
            FROM tasks t
            WHERE t.id = ? AND t.task_type = 'practical'
            """,
            (task_id,),
        )
        task = cursor.fetchone()
        if not task:
            conn.close()
            return "Task not found", 404

        subject_id = task[5]
        if request.method == "POST":
            assign_date = request.form.get("assign_date")
            practical_mode = request.form.get("practical_mode") or "upload"
            simulator_key = request.form.get("simulator_key") or None
            marking_script = request.form.get("marking_script") if practical_mode == "upload" else None
            allow_multiple = 1 if request.form.get("allow_multiple") else 0
            max_attempts = int(request.form.get("max_attempts", 1)) if allow_multiple else 1
            groups = request.form.getlist("groups")
            question_text = request.form.get("question_text", "").strip()
            if practical_mode == "simulator" and simulator_key and not question_text:
                simulator_definition = get_simulator_definition(simulator_key)
                if simulator_definition:
                    question_text = simulator_definition["default_question_html"]
            cursor.execute(
                """
                UPDATE tasks
                SET assign_date = ?, marking_script = ?, question_text = ?, allow_multiple = ?, max_attempts = ?,
                    practical_mode = ?, simulator_key = ?, sample_file = CASE WHEN ? = 'upload' THEN sample_file ELSE NULL END,
                    sample_file_name = CASE WHEN ? = 'upload' THEN sample_file_name ELSE NULL END
                WHERE id = ?
                """,
                (assign_date, marking_script, question_text, allow_multiple, max_attempts, practical_mode, simulator_key if practical_mode == "simulator" else None, practical_mode, practical_mode, task_id),
            )

            cursor.execute("DELETE FROM task_groups WHERE task_id = ?", (task_id,))
            for g in groups:
                if g.strip():
                    cursor.execute("INSERT INTO task_groups (task_id, group_name) VALUES (?, ?)", (task_id, g))

            cursor.execute("DELETE FROM task_teachers WHERE task_id = ?", (task_id,))
            teachers = request.form.getlist("teachers")
            for t in teachers:
                if t.strip():
                    cursor.execute("INSERT INTO task_teachers (task_id, teacher_username) VALUES (?, ?)", (task_id, t))

            sample_file = request.files.get("sample_file")
            if practical_mode == "upload" and sample_file and sample_file.filename:
                sample_bytes = sample_file.read()
                sample_filename = sample_file.filename
                cursor.execute(
                    """
                    UPDATE tasks
                    SET sample_file = ?, sample_file_name = ?
                    WHERE id = ?
                    """,
                    (sample_bytes, sample_filename, task_id),
                )

            conn.commit()
            conn.close()
            log_activity(username, f"edited task {task[1]}")
            return redirect(url_for("manage_tasks", subject_id=subject_id))

        cursor.execute("SELECT group_name FROM task_groups WHERE task_id = ?", (task_id,))
        current_groups = {row[0] for row in cursor.fetchall()}
        cursor.execute("SELECT teacher_username FROM task_teachers WHERE task_id = ?", (task_id,))
        current_teachers = {row[0] for row in cursor.fetchall()}
        all_groups = get_groups()
        available_scripts = get_marking_scripts()
        simulator_catalog = get_simulator_catalog()
        teachers = get_teachers()
        conn.close()

        script_options = '<option value="">-- No marking script --</option>'
        for s in available_scripts:
            selected = "selected" if s == task[3] else ""
            script_options += f'<option value="{escape(s)}" {selected}>{escape(s)}</option>'

        teacher_checkboxes = ""
        for t in teachers:
            checked = "checked" if t[0] in current_teachers else ""
            teacher_checkboxes += f'<label style="display:inline-flex;align-items:center;gap:5px;"><input type="checkbox" name="teachers" value="{escape(t[0])}" {checked}> {escape(t[1] or t[0])}</label>'

        return render_template(
            "edit_task.html",
            task=task,
            current_groups=current_groups,
            all_groups=all_groups,
            available_scripts=available_scripts,
            simulator_catalog=simulator_catalog,
            teacher_checkboxes=teacher_checkboxes,
        )

    @app.route("/tasks/<int:task_id>/toggle", methods=["POST"])
    def toggle_task(task_id):
        username = session.get("username")
        if not username or get_user_role(username) not in ["teacher", "admin"]:
            return "Access denied", 403
        subject_id = request.form.get("subject_id")
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT is_active FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        if row:
            new_state = 0 if row[0] else 1
            cursor.execute("UPDATE tasks SET is_active = ? WHERE id = ?", (new_state, task_id))
            conn.commit()
            state_label = "activated" if new_state else "deactivated"
            log_activity(username, f"{state_label} task {task_id}")
        conn.close()
        return redirect(url_for("manage_tasks", subject_id=subject_id))

    @app.route("/tasks/<int:task_id>/clear_uploads", methods=["GET", "POST"])
    def clear_task_uploads(task_id):
        username = session.get("username")
        if not username:
            return "Unauthorized", 401

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT sample_file, sample_file_name
            FROM tasks
            WHERE id = ? AND task_type = 'practical'
            """,
            (task_id,),
        )
        row = cursor.fetchone()
        conn.close()

        if not row:
            return "Sample not found", 404

        sample_bytes, sample_name = row
        if not sample_bytes:
            return "No sample file uploaded", 404

        if not sample_name:
            sample_name = f"task_{task_id}_sample"

        ext = os.path.splitext(sample_name)[1].lower()
        bio = BytesIO(sample_bytes)
        mimetype = None
        if ext == ".docx":
            mimetype = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        elif ext == ".xlsx":
            mimetype = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        elif ext == ".html":
            mimetype = "text/html; charset=utf-8"

        return send_file(bio, mimetype=mimetype, as_attachment=True, download_name=sample_name)

    def clear_task_uploads_delete(task_id):
        username = session.get("username")
        if not username or get_user_role(username) not in ["teacher", "admin"]:
            return "Access denied", 403
        subject_id = request.form.get("subject_id")
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT t.name, s.name FROM tasks t
            JOIN subjects s ON s.id = t.subject_id
            WHERE t.id = ?
            """,
            (task_id,),
        )
        row = cursor.fetchone()
        if row:
            task_name, subject_name = row
            cursor.execute("DELETE FROM results WHERE subject = ? AND task = ?", (subject_name, task_name))
            conn.commit()
            log_activity(username, f"cleared uploads for {subject_name} {task_name}")
        conn.close()
        return redirect(url_for("manage_tasks", subject_id=subject_id))

    @app.route("/upload/<username>/<subject_id>/<task_id>", methods=["GET", "POST"])
    def upload(username, subject_id, task_id):
        session_user = session.get("username")
        if session_user != username:
            return "Unauthorized", 401

        update_active_user(username)
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("SELECT name FROM subjects WHERE id = ?", (subject_id,))
        subject_row = cursor.fetchone()
        if not subject_row:
            conn.close()
            return "Subject not found", 404
        subject_name = subject_row[0]

        cursor.execute(
            "SELECT name, assign_date, marking_script, question_text, allow_multiple, max_attempts, "
            "is_active, marking_setup_id, practical_mode, simulator_key FROM tasks WHERE id = ?",
            (task_id,),
        )
        task_row = cursor.fetchone()
        if not task_row:
            conn.close()
            return "Task not found", 404
        task_name, assign_date, marking_script, question_text, allow_multiple, max_attempts, task_is_active, marking_setup_id, practical_mode, simulator_key = task_row

        user_role = get_user_role(username)
        if user_role not in ["teacher", "admin"] and not task_is_active:
            conn.close()
            return """
            <p><a href="/student_dashboard">← Back to Dashboard</a></p>
            <h2>Upload Closed</h2>
            <p style="color:#A4262C;">This task is currently not accepting uploads. Please contact your teacher.</p>
            """, 403

        cursor.execute("SELECT group_name FROM users WHERE username = ?", (username,))
        user_group_row = cursor.fetchone()
        user_group = user_group_row[0] if user_group_row else None
        cursor.execute("SELECT full_name FROM users WHERE username = ?", (username,))
        learner_name_row = cursor.fetchone()
        learner_full_name = (learner_name_row[0] or username) if learner_name_row else username

        if user_role not in ["teacher", "admin"]:
            today = datetime.now().date().isoformat()
            cursor.execute(
                """
                SELECT COUNT(*) FROM task_groups
                WHERE task_id = ? AND group_name = ?
                """,
                (task_id, user_group),
            )
            if cursor.fetchone()[0] == 0:
                conn.close()
                return "Access denied: Task not assigned to your group", 403

            if assign_date > today:
                conn.close()
                return "Access denied: Task is not yet available", 403

        if request.method == "POST":
            cursor.execute("SELECT COUNT(*) FROM results WHERE username = ? AND subject = ? AND task = ?", (username, subject_name, task_name))
            submission_count = cursor.fetchone()[0]

            if not allow_multiple and submission_count >= 1:
                conn.close()
                return '<p><a href="/student_dashboard">← Back to Dashboard</a></p><h2>Upload Closed</h2><p style="color:#A4262C;">This task allows only a single submission, and you have already submitted once.</p>', 403

            if allow_multiple and submission_count >= max_attempts:
                conn.close()
                return '<p><a href="/student_dashboard">← Back to Dashboard</a></p><h2>Upload Closed</h2><p style="color:#A4262C;">You have reached the maximum number of submissions for this task.</p>', 403

            if practical_mode == "simulator":
                result = score_simulator_attempt(simulator_key, request.form)
                if not result:
                    conn.close()
                    return "Simulator task is not configured correctly", 500
            else:
                file = request.files.get("file")
                if not file:
                    conn.close()
                    return "No file uploaded", 400

                original_ext = os.path.splitext(file.filename or "")[1] or ".tmp"
                temp_path = f"temp_{username}{original_ext}"
                file.save(temp_path)

                try:
                    result = mark_file(temp_path, marking_script, marking_setup_id)
                finally:
                    if os.path.exists(temp_path):
                        os.remove(temp_path)

            if result.get("error"):
                conn.close()
                return f"""
                <p><a href="/student_dashboard">← Back to Dashboard</a></p>
                <h2>Submission Error</h2>
                <p style="color:red;">{escape(result['error'])}</p>
                """

            weak_skills = [r["question"] for r in result["results"] if not r["passed"]]
            update_weakness(username, weak_skills)
            save_result(username, subject_name, task_name, result["percentage"], ", ".join(weak_skills[:3]) or "Well done!")
            log_activity(username, f"submitted {subject_name} {task_name}")

            correct_items = [r for r in result["results"] if r["passed"]]
            wrong_items = [r for r in result["results"] if not r["passed"]]
            conn.close()
            return render_template(
                "upload_result.html",
                subject_name=subject_name,
                task_name=task_name,
                score=result["score"],
                total=result["total"],
                percentage=result["percentage"],
                correct_items=correct_items,
                wrong_items=wrong_items,
            )

        conn.close()

        sample_link_html = ""
        cursor = None
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT sample_file, sample_file_name FROM tasks WHERE id = ? AND task_type = 'practical'", (task_id,))
            row = cursor.fetchone()
            if row and row[0]:
                sample_name = row[1] or f"task_{task_id}_sample"
                sample_link_html = f'<p><a href="/tasks/{task_id}/sample_file" target="_blank">📎 Download task sample</a> ({escape(sample_name)})</p>'
        finally:
            try:
                if cursor:
                    conn.close()
            except Exception:
                pass

        simulator_definition = get_simulator_definition(simulator_key) if practical_mode == "simulator" else None
        simulator_template = "upload_task.html"
        if practical_mode == "simulator":
            simulator_template = (
                "simulator_html_practical.html"
                if simulator_definition and simulator_definition.get("shell", {}).get("app") == "html"
                else "simulator_practical.html"
            )

        return render_template(
            simulator_template,
            subject_name=subject_name,
            task_name=task_name,
            question_text=question_text,
            sample_link_html=sample_link_html,
            learner_full_name=learner_full_name,
            simulator_definition=simulator_definition,
        )

    @app.route("/subjects/<username>")
    def subjects(username):
        if not session.get("username"):
            return redirect(url_for("login"))

        session_user = session.get("username")
        if session_user != username:
            return "Unauthorized", 401
        return redirect(url_for("learner_tasks"))

    @app.route("/tasks/<username>/<subject_id>")
    def tasks(username, subject_id):
        if not session.get("username"):
            return redirect(url_for("login"))

        session_user = session.get("username")
        if session_user != username:
            return "Unauthorized", 401
        return redirect(url_for("learner_tasks"))
