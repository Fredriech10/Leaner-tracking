import io
import json
from datetime import datetime

from flask import redirect, render_template, request, send_file, session, url_for
from markupsafe import escape

from app.database import get_db, get_marking_db, get_teachers, get_user_role, log_activity
from app.helper_marking import get_marking_scripts
from app.practical_simulators import (
    WORD_INSERT_PICTURE_SIMULATOR_KEY,
    WORD_CAPS_PRACTICAL_KEY,
    get_simulator_catalog,
    get_simulator_definition,
)


def _load_word_bank_questions(cursor):
    cursor.execute(
        """
        SELECT id, category, title, prompt_html, steps_json, marks
        FROM practical_question_bank
        WHERE program = 'word'
        ORDER BY category, title
        """
    )
    questions = []
    for bank_id, category, title, prompt_html, steps_json, marks in cursor.fetchall():
        try:
            steps = json.loads(steps_json or "[]")
        except Exception:
            steps = []
        questions.append(
            {
                "id": bank_id,
                "category": category or "General",
                "title": title,
                "prompt_html": prompt_html,
                "steps": steps,
                "marks": marks or len(steps) or 1,
            }
        )
    return questions


def _save_task_practical_questions(cursor, task_id, selected_question_ids):
    cursor.execute("DELETE FROM task_practical_questions WHERE task_id = ?", (task_id,))
    for order_index, question_id in enumerate(selected_question_ids, start=1):
        cursor.execute(
            """
            INSERT INTO task_practical_questions (task_id, bank_question_id, order_index)
            VALUES (?, ?, ?)
            """,
            (task_id, question_id, order_index),
        )


def register_task_admin_routes(app):
    @app.route("/manage_subjects", methods=["GET", "POST"])
    def manage_subjects():
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))

        role = get_user_role(username)
        if role not in ["teacher", "admin"]:
            return "Access denied", 403

        if request.method == "POST":
            action = request.form.get("action")
            if action == "create":
                subject_name = request.form.get("subject_name")
                if subject_name:
                    conn = get_db()
                    cursor = conn.cursor()
                    try:
                        cursor.execute(
                            "INSERT INTO subjects (name, created_by, created_at) VALUES (?, ?, ?)",
                            (subject_name, username, datetime.now().isoformat()),
                        )
                        conn.commit()
                        log_activity(username, f"created subject {subject_name}")
                    except Exception:
                        pass
                    conn.close()
            elif action == "delete":
                subject_id = request.form.get("subject_id")
                if subject_id:
                    conn = get_db()
                    cursor = conn.cursor()
                    cursor.execute("SELECT name FROM subjects WHERE id = ?", (subject_id,))
                    subj = cursor.fetchone()
                    if subj:
                        cursor.execute("DELETE FROM results WHERE subject = ?", (subj[0],))
                        cursor.execute("DELETE FROM task_groups WHERE task_id IN (SELECT id FROM tasks WHERE subject_id = ?)", (subject_id,))
                        cursor.execute("DELETE FROM tasks WHERE subject_id = ?", (subject_id,))
                        cursor.execute("DELETE FROM subjects WHERE id = ?", (subject_id,))
                        conn.commit()
                        log_activity(username, f"deleted subject {subj[0]} and all related tasks and results")
                    conn.close()

            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT id, name FROM subjects ORDER BY name")
            subjects = cursor.fetchall()
            conn.close()
            return render_template("manage_subjects.html", subjects=subjects)

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id, name FROM subjects ORDER BY name")
        subjects = cursor.fetchall()
        conn.close()
        return render_template("manage_subjects.html", subjects=subjects)

    @app.route("/manage_tasks/<subject_id>", methods=["GET", "POST"])
    def manage_tasks(subject_id):
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))

        role = get_user_role(username)
        if role not in ["teacher", "admin"]:
            return "Access denied", 403

        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("SELECT name FROM subjects WHERE id = ?", (subject_id,))
        subj = cursor.fetchone()
        if not subj:
            conn.close()
            return "Subject not found", 404
        subject_name = subj[0]

        if request.method == "POST":
            action = request.form.get("action")
            if action == "create":
                task_name = request.form.get("task_name")
                assign_date = request.form.get("assign_date")
                practical_mode = request.form.get("practical_mode") or "upload"
                simulator_key = request.form.get("simulator_key") or None
                marking_script = request.form.get("marking_script") if practical_mode == "upload" else None
                marking_setup_id = request.form.get("marking_setup_id") if practical_mode == "upload" else None
                allow_multiple = 1 if request.form.get("allow_multiple") else 0
                max_attempts = int(request.form.get("max_attempts", 1)) if allow_multiple else 1
                groups = request.form.getlist("groups")
                teachers = request.form.getlist("teachers")
                if task_name and assign_date:
                    selected_word_question_ids = [
                        int(value) for value in request.form.getlist("word_question_ids") if str(value).strip().isdigit()
                    ]
                    question_text = request.form.get("question_text", "").strip()
                    if practical_mode == "simulator" and simulator_key == WORD_CAPS_PRACTICAL_KEY:
                        simulator_key = WORD_CAPS_PRACTICAL_KEY
                        if selected_word_question_ids:
                            cursor.execute(
                                "SELECT COUNT(*), COALESCE(SUM(marks), 0) FROM practical_question_bank WHERE id IN ({})".format(
                                    ",".join("?" for _ in selected_word_question_ids)
                                ),
                                tuple(selected_word_question_ids),
                            )
                            selected_count, total_marks = cursor.fetchone()
                            question_text = (
                                f"<p><strong>Word practical:</strong> {selected_count} selected question"
                                f"{'' if selected_count == 1 else 's'} worth {total_marks} mark"
                                f"{'' if total_marks == 1 else 's'} in total.</p>"
                            )
                    elif practical_mode == "simulator" and simulator_key and not question_text:
                        simulator_definition = get_simulator_definition(simulator_key)
                        if simulator_definition:
                            question_text = simulator_definition["default_question_html"]
                    cursor.execute(
                        "INSERT INTO tasks (subject_id, name, assign_date, marking_script, marking_setup_id, "
                        "question_text, task_type, practical_mode, simulator_key, allow_multiple, max_attempts, created_by, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, 'practical', ?, ?, ?, ?, ?, ?)",
                        (
                            subject_id,
                            task_name,
                            assign_date,
                            marking_script,
                            marking_setup_id,
                            question_text,
                            practical_mode,
                            simulator_key if practical_mode == "simulator" else None,
                            allow_multiple,
                            max_attempts,
                            username,
                            datetime.now().isoformat(),
                        ),
                    )
                    task_id = cursor.lastrowid
                    if practical_mode == "simulator" and simulator_key == WORD_CAPS_PRACTICAL_KEY:
                        _save_task_practical_questions(cursor, task_id, selected_word_question_ids)
                    if practical_mode == "upload" and "sample_file" in request.files:
                        file = request.files["sample_file"]
                        if file.filename:
                            file_content = file.read()
                            file_name = file.filename
                            cursor.execute("UPDATE tasks SET sample_file = ?, sample_file_name = ? WHERE id = ?", (file_content, file_name, task_id))
                    for group in groups:
                        cursor.execute("INSERT INTO task_groups (task_id, group_name) VALUES (?, ?)", (task_id, group))
                    for teacher in teachers:
                        if teacher.strip():
                            cursor.execute("INSERT INTO task_teachers (task_id, teacher_username) VALUES (?, ?)", (task_id, teacher))
                    conn.commit()
                    log_activity(username, f"created task {task_name} in {subject_name}")
            elif action == "reuse":
                source_task_id = request.form.get("source_task_id")
                new_task_name = request.form.get("task_name", "").strip()
                new_assign_date = request.form.get("assign_date")
                new_practical_mode = request.form.get("practical_mode") or "upload"
                new_simulator_key = request.form.get("simulator_key") or None
                new_marking_script = (request.form.get("marking_script") or None) if new_practical_mode == "upload" else None
                new_marking_setup_id = (request.form.get("marking_setup_id") or None) if new_practical_mode == "upload" else None
                new_allow_multiple = 1 if request.form.get("allow_multiple") else 0
                new_max_attempts = int(request.form.get("max_attempts", 1)) if new_allow_multiple else 1
                new_groups = request.form.getlist("groups")
                new_teachers = request.form.getlist("teachers")
                if source_task_id and new_task_name and new_assign_date:
                    cursor.execute("SELECT question_text, sample_file, sample_file_name, simulator_key FROM tasks WHERE id = ?", (source_task_id,))
                    src = cursor.fetchone()
                    src_question = src[0] if src else ""
                    src_file = src[1] if src else None
                    src_file_name = src[2] if src else None
                    src_simulator_key = src[3] if src else None
                    effective_simulator_key = new_simulator_key if new_practical_mode == "simulator" else None
                    if new_practical_mode == "simulator" and not effective_simulator_key:
                        effective_simulator_key = src_simulator_key
                    if new_practical_mode == "simulator" and not src_question and effective_simulator_key:
                        simulator_definition = get_simulator_definition(effective_simulator_key)
                        if simulator_definition:
                            src_question = simulator_definition["default_question_html"]
                    cursor.execute(
                        "INSERT INTO tasks (subject_id, name, assign_date, marking_script, marking_setup_id, "
                        "question_text, task_type, practical_mode, simulator_key, allow_multiple, max_attempts, sample_file, sample_file_name, "
                        "created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, 'practical', ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            subject_id,
                            new_task_name,
                            new_assign_date,
                            new_marking_script,
                            new_marking_setup_id,
                            src_question,
                            new_practical_mode,
                            effective_simulator_key,
                            new_allow_multiple,
                            new_max_attempts,
                            src_file if new_practical_mode == "upload" else None,
                            src_file_name if new_practical_mode == "upload" else None,
                            username,
                            datetime.now().isoformat(),
                        ),
                    )
                    new_task_id = cursor.lastrowid
                    if new_practical_mode == "simulator":
                        cursor.execute(
                            """
                            INSERT INTO task_practical_questions (task_id, bank_question_id, order_index, title_override, prompt_override_html, steps_json_override, marks_override)
                            SELECT ?, bank_question_id, order_index, title_override, prompt_override_html, steps_json_override, marks_override
                            FROM task_practical_questions
                            WHERE task_id = ?
                            ORDER BY order_index
                            """,
                            (new_task_id, source_task_id),
                        )
                    for g in new_groups:
                        if g.strip():
                            cursor.execute("INSERT INTO task_groups (task_id, group_name) VALUES (?, ?)", (new_task_id, g))
                    for t in new_teachers:
                        if t.strip():
                            cursor.execute("INSERT INTO task_teachers (task_id, teacher_username) VALUES (?, ?)", (new_task_id, t))
                    conn.commit()
                    log_activity(username, f"reused task {source_task_id} as '{new_task_name}' in {subject_name}")
            elif action == "assign_theory":
                task_name = request.form.get("task_name")
                assign_date = request.form.get("assign_date")
                theory_test_id = request.form.get("theory_test_id")
                groups = request.form.getlist("groups")
                teachers = request.form.getlist("teachers")
                if task_name and assign_date and theory_test_id:
                    cursor.execute(
                        "INSERT INTO tasks (subject_id, name, assign_date, theory_test_id, task_type, created_by, created_at) VALUES (?, ?, ?, ?, 'theory', ?, ?)",
                        (subject_id, task_name, assign_date, theory_test_id, username, datetime.now().isoformat()),
                    )
                    task_id = cursor.lastrowid
                    for group in groups:
                        cursor.execute("INSERT INTO task_groups (task_id, group_name) VALUES (?, ?)", (task_id, group))
                    for teacher in teachers:
                        if teacher.strip():
                            cursor.execute("INSERT INTO task_teachers (task_id, teacher_username) VALUES (?, ?)", (task_id, teacher))
                    conn.commit()
                    log_activity(username, f"assigned theory test as task {task_name} in {subject_name}")
            elif action == "delete":
                task_id = request.form.get("task_id")
                if task_id:
                    cursor.execute("SELECT name, subject_id FROM tasks WHERE id = ?", (task_id,))
                    tsk = cursor.fetchone()
                    if tsk:
                        task_name = tsk[0]
                        subject_id_val = tsk[1]
                        cursor.execute("SELECT name FROM subjects WHERE id = ?", (subject_id_val,))
                        subj_row = cursor.fetchone()
                        if subj_row:
                            subject_name = subj_row[0]
                            cursor.execute("DELETE FROM results WHERE subject = ? AND task = ?", (subject_name, task_name))
                        cursor.execute("DELETE FROM task_groups WHERE task_id = ?", (task_id,))
                        cursor.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
                        conn.commit()
                        log_activity(username, f"deleted task {task_name} from {subject_name} and all related results")

            conn.close()
            return redirect(url_for("manage_tasks", subject_id=subject_id))

        cursor.execute("SELECT DISTINCT group_name FROM users WHERE group_name IS NOT NULL ORDER BY group_name")
        all_groups = [row[0] for row in cursor.fetchall()]

        available_scripts = get_marking_scripts()
        marking_conn = get_marking_db()
        marking_cursor = marking_conn.cursor()
        marking_cursor.execute("SELECT id, title FROM marking_setups ORDER BY title, id")
        available_marking_setups = marking_cursor.fetchall()
        marking_conn.close()

        cursor.execute("SELECT id, title, subject FROM theory_tests ORDER BY title")
        available_theory_tests = cursor.fetchall()

        teachers = get_teachers()
        simulator_catalog = get_simulator_catalog()
        simulator_catalog[WORD_CAPS_PRACTICAL_KEY] = {
            "title": "Word CAPS Practical Builder",
            "description": "Build a Word practical from a tick-box question bank.",
        }
        word_bank_questions = _load_word_bank_questions(cursor)
        teacher_checkboxes = "".join(
            f'<label style="display:inline-flex;align-items:center;gap:5px;">'
            f'<input type="checkbox" name="teachers" value="{escape(t[0])}"> {escape(t[1] or t[0])}</label>'
            for t in teachers
        )

        cursor.execute(
            """
            SELECT t.id, t.name, t.assign_date, t.marking_script, t.task_type, t.theory_test_id,
                   t.allow_multiple, t.max_attempts, t.is_active, t.question_text, t.sample_file_name,
                   t.marking_setup_id, t.practical_mode, t.simulator_key,
                   GROUP_CONCAT(DISTINCT tg.group_name),
                   GROUP_CONCAT(DISTINCT tt.teacher_username)
            FROM tasks t
            LEFT JOIN task_groups tg ON t.id = tg.task_id
            LEFT JOIN task_teachers tt ON t.id = tt.task_id
            WHERE t.subject_id = ?
            GROUP BY t.id
            ORDER BY t.assign_date, t.name
            """,
            (subject_id,),
        )
        tasks = cursor.fetchall()
        conn.close()

        task_list = ""
        for task_id, task_name, assign_date, marking_script, task_type, theory_test_id, allow_multiple, max_attempts, is_active, question_text, sample_file_name, marking_setup_id, practical_mode, simulator_key, group_list, teacher_list in tasks:
            if task_type == "theory":
                type_label = '<span style="background:#0078D4;color:white;padding:2px 6px;border-radius:10px;font-size:0.8em;">📝 Theory</span>'
                script_label = f"Test ID: {theory_test_id}"
            else:
                type_label = '<span style="background:#107C10;color:white;padding:2px 6px;border-radius:10px;font-size:0.8em;">📁 Practical</span>'
                if practical_mode == "simulator":
                    simulator_title = simulator_catalog.get(simulator_key or "", {}).get("title", simulator_key or "Simulator")
                    script_label = f'<span style="color:#005a9e;">Simulator: {escape(simulator_title)}</span>'
                else:
                    script_label = marking_script if marking_script else '<span style="color:red;">None assigned</span>'
                if practical_mode == "upload" and marking_setup_id:
                    setup_name = next((title for setup_id, title in available_marking_setups if setup_id == marking_setup_id), None)
                    setup_label = escape(setup_name or f"Setup {marking_setup_id}")
                    script_label += f'<br><span style="color:#005a9e;">Setup: {setup_label}</span>'

            status_badge = '<span style="background:#c8f7c5;color:#107C10;padding:2px 8px;border-radius:10px;font-size:0.8em;">Active</span>' if is_active else '<span style="background:#f7c5c5;color:#A4262C;padding:2px 8px;border-radius:10px;font-size:0.8em;">Inactive</span>'
            toggle_label = "⏸ Deactivate" if is_active else "▶ Activate"
            toggle_style = "background:#ff8c00;color:white;" if is_active else "background:#107C10;color:white;"
            if task_type == "practical":
                mode_label = "Simulator" if practical_mode == "simulator" else "Upload"
                attempts_label = f"{mode_label} / " + ("Single" if not allow_multiple else f"Multiple ({max_attempts})")
            else:
                attempts_label = "Theory task"

            task_list += f"""
            <tr>
                <td>{escape(task_name)} {type_label}</td>
                <td>{assign_date}</td>
                <td>{group_list or 'None'}</td>
                <td>{teacher_list or 'None'}</td>
                <td>{script_label}</td>
                <td>{f'<a href="/tasks/{task_id}/sample_file" target="_blank">{escape(sample_file_name)}</a>' if sample_file_name else 'None'}</td>
                <td>{attempts_label}</td>
                <td>{status_badge}</td>
                <td style="white-space:nowrap; vertical-align:middle;">
                    {'<a href="/tasks/' + str(task_id) + '/edit" title="Edit task" class="btn btn-primary">✏️</a>' if task_type == 'practical' else ''}
                    <a href="/tasks/{task_id}/preview" class="icon-btn" title="Preview learner view">👁</a>
                    {'<button type="button" class="btn btn-success" title="Reuse: copy into a new task" onclick="openReuseTaskModal(' + str(task_id) + ', ' + repr(task_name) + ', ' + repr(marking_script or '') + ', ' + str(allow_multiple) + ', ' + str(max_attempts) + ', ' + repr(marking_setup_id or '') + ', ' + repr(practical_mode or 'upload') + ', ' + repr(simulator_key or '') + ')">📋</button>' if task_type == 'practical' else ''}
                    <form method="post" action="/tasks/{task_id}/toggle" style="display:inline-flex; margin:0;">
                        <input type="hidden" name="subject_id" value="{subject_id}">
                        <button type="submit" title="{toggle_label}" class="btn" style="{toggle_style}">{'⏸' if is_active else '▶'}</button>
                    </form>
                    <form method="post" action="/tasks/{task_id}/clear_uploads" style="display:inline-flex; margin:0;"
                          onsubmit="return confirm('Clear ALL uploads for {escape(task_name)}? This cannot be undone.')">
                        <input type="hidden" name="subject_id" value="{subject_id}">
                        <button type="submit" title="Clear uploads" class="btn btn-danger">🗑</button>
                    </form>
                    <form method="post" style="display:inline-flex; margin:0;" onsubmit="return confirm('⚠️ WARNING: Delete task {escape(task_name)} and ALL STUDENT SUBMISSIONS?\n\nThis will permanently remove:\n- All student uploads and scores\n- Task from Group Results\n\nThis action CANNOT be undone!')">
                        <input type="hidden" name="action" value="delete">
                        <input type="hidden" name="task_id" value="{task_id}">
                        <button type="submit" title="Delete task" class="btn" style="background:#555;color:white;">🗑</button>
                    </form>
                </td>
            </tr>
            """

        group_checkboxes = ""
        for group in all_groups:
            group_checkboxes += f'<label style="display:inline-flex;align-items:center;gap:5px;margin-right:10px;"><input type="checkbox" name="groups" value="{escape(group)}"> {escape(group)}</label>'

        script_options = '<option value="">-- No marking script --</option>'
        for script in available_scripts:
            script_options += f'<option value="{escape(script)}">{escape(script)}</option>'

        marking_setup_options = '<option value="">-- No marking setup --</option>'
        for setup_id, setup_title in available_marking_setups:
            marking_setup_options += f'<option value="{setup_id}">{escape(setup_title)}</option>'

        simulator_options = ""
        for simulator_key, simulator_meta in simulator_catalog.items():
            simulator_options += f'<option value="{escape(simulator_key)}">{escape(simulator_meta["title"])}</option>'

        theory_test_options = '<option value="">-- Select Theory Test --</option>'
        for tt_id, tt_title, tt_subject in available_theory_tests:
            label = f"{tt_title}" + (f" ({tt_subject})" if tt_subject else "")
            theory_test_options += f'<option value="{tt_id}">{escape(label)}</option>'

        return render_template(
            "manage_tasks.html",
            subject_name=subject_name,
            script_options=script_options,
            marking_setup_options=marking_setup_options,
            simulator_options=simulator_options,
            default_simulator_key=WORD_INSERT_PICTURE_SIMULATOR_KEY,
            group_checkboxes=group_checkboxes,
            teacher_checkboxes=teacher_checkboxes,
            task_list=task_list,
            word_bank_questions=word_bank_questions,
            word_caps_practical_key=WORD_CAPS_PRACTICAL_KEY,
        )

    @app.route("/tasks/<int:task_id>/preview")
    def task_preview(task_id):
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))

        role = get_user_role(username)
        if role not in ["teacher", "admin"]:
            return "Access denied", 403

        simulator_catalog = get_simulator_catalog()
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT t.name, t.assign_date, t.marking_script, t.question_text, t.task_type, t.theory_test_id, "
            "t.sample_file_name, s.name, t.practical_mode, t.simulator_key "
            "FROM tasks t JOIN subjects s ON t.subject_id = s.id WHERE t.id = ?",
            (task_id,),
        )
        task_row = cursor.fetchone()
        if not task_row:
            conn.close()
            return "Task not found", 404

        task_name, assign_date, marking_script, question_text, task_type, theory_test_id, sample_file_name, subject_name, practical_mode, simulator_key = task_row
        theory_test_title = None
        simulator_title = None
        if task_type == "theory" and theory_test_id:
            cursor.execute("SELECT title FROM theory_tests WHERE id = ?", (theory_test_id,))
            test_row = cursor.fetchone()
            theory_test_title = test_row[0] if test_row else None
        elif task_type == "practical" and practical_mode == "simulator":
            simulator_title = simulator_catalog.get(simulator_key or "", {}).get("title")

        conn.close()
        return render_template(
            "task_preview.html",
            subject_name=subject_name,
            task_name=task_name,
            assign_date=assign_date,
            task_type=task_type,
            marking_script=marking_script,
            question_text=question_text,
            sample_file_name=sample_file_name,
            sample_url=f"/tasks/{task_id}/sample_file" if sample_file_name else None,
            practical_mode=practical_mode,
            simulator_title=simulator_title,
            theory_test_title=theory_test_title,
            theory_test_id=theory_test_id,
        )

    @app.route("/tasks/<int:task_id>/sample_file")
    def download_sample_file(task_id):
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT sample_file, sample_file_name FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        conn.close()

        if not row or not row[0]:
            return "Sample file not found", 404

        file_content, file_name = row
        return send_file(
            io.BytesIO(file_content),
            as_attachment=True,
            download_name=file_name,
            mimetype="application/octet-stream",
        )
