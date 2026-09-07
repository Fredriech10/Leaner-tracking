"""Teacher-facing no-code builder for Word upload tasks."""

import json
from datetime import datetime

from flask import redirect, render_template, request, session, url_for
from werkzeug.utils import secure_filename

from app.database import get_db, get_marking_db, get_teachers, get_user_role, log_activity


RULES = {
    "font_name": ("font", "font_name"),
    "font_size": ("font", "size"),
    "font_color": ("font", "color"),
    "bold": ("font", "bold"),
    "italic": ("font", "italic"),
    "underline": ("font", "underline"),
    "alignment": ("paragraph_formatting", "alignment"),
    "orientation": ("document", "orientation"),
    "paper_size": ("document", "paper_size"),
    "table_cell_text": ("table", "cell_text"),
}


def _rule_from_form(index):
    rule_key = request.form.get(f"rule_{index}", "")
    description = request.form.get(f"description_{index}", "").strip()
    target_text = request.form.get(f"target_{index}", "").strip()
    expected_value = request.form.get(f"expected_{index}", "").strip()
    marks = max(1, int(request.form.get(f"marks_{index}", "1") or 1))
    if not description or rule_key not in RULES:
        return None

    domain, check_type = RULES[rule_key]
    target, expected = ({"locator": {"contains_text": target_text}} if target_text else {}), expected_value
    if rule_key == "font_size":
        expected = float(expected_value)
    elif rule_key in {"bold", "italic", "underline"}:
        expected = expected_value.lower() not in {"false", "no", "0"}
    elif rule_key == "paper_size":
        expected = expected_value.upper()
    elif rule_key == "table_cell_text":
        # Expected format: row,column,text. Table number is entered as the target.
        parts = [part.strip() for part in expected_value.split(",", 2)]
        if len(parts) != 3 or not all(parts):
            raise ValueError("Table cell text must be entered as row, column, text.")
        target = {"locator": {"table_index": max(0, int(target_text or "1") - 1)}}
        expected = {"row": int(parts[0]), "col": int(parts[1]), "text": parts[2]}
    elif rule_key not in {"orientation", "paper_size"} and not target_text:
        raise ValueError(f"Criterion {index + 1} needs target text to locate the change.")

    return {
        "question_number": str(index + 1),
        "description": description,
        "domain": domain,
        "type": check_type,
        "target": target,
        "expected": expected,
        "marks": marks,
    }


def register_custom_word_task_routes(app):
    @app.route("/subjects/<int:subject_id>/custom_word_task", methods=["GET", "POST"])
    def custom_word_task(subject_id):
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))
        if get_user_role(username) not in {"teacher", "admin"}:
            return "Access denied", 403

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM subjects WHERE id = ?", (subject_id,))
        subject = cursor.fetchone()
        groups = [row[0] for row in cursor.execute("SELECT DISTINCT group_name FROM users WHERE group_name IS NOT NULL ORDER BY group_name")]
        conn.close()
        if not subject:
            return "Subject not found", 404

        error = None
        if request.method == "POST":
            try:
                title = request.form.get("title", "").strip()
                instructions = request.form.get("instructions", "").strip()
                starter = request.files.get("starter_file")
                paper = request.files.get("question_paper")
                if not title or not starter or not starter.filename:
                    raise ValueError("Task name and Word starter document are required.")
                if not starter.filename.lower().endswith(".docx"):
                    raise ValueError("The Word starter document must be a .docx file.")

                rules = []
                for index in range(int(request.form.get("criterion_count", "0") or 0)):
                    rule = _rule_from_form(index)
                    if rule:
                        rules.append(rule)
                if not rules:
                    raise ValueError("Add at least one marking criterion.")

                now = datetime.now().isoformat()
                setup = {"task_name": title, "program": "word", "file": "student_file.docx", "questions": rules, "total_marks": sum(rule["marks"] for rule in rules)}
                paper_blob = paper.read() if paper and paper.filename else None
                paper_name = secure_filename(paper.filename) if paper and paper.filename else None
                marking_conn = get_marking_db()
                try:
                    marking_cursor = marking_conn.cursor()
                    marking_cursor.execute(
                        """INSERT INTO marking_setups (title, created_by, created_at, updated_at, question_paper_filename, question_paper_blob, json_script_filename, json_script_blob, notes)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (title, username, now, now, paper_name, paper_blob,
                         f"{secure_filename(title)}.json", json.dumps(setup, ensure_ascii=False).encode("utf-8"), instructions),
                    )
                    setup_id = marking_cursor.lastrowid
                    marking_conn.commit()
                finally:
                    marking_conn.close()

                starter_blob = starter.read()
                conn = get_db()
                try:
                    cursor = conn.cursor()
                    cursor.execute(
                        """INSERT INTO tasks (subject_id, name, assign_date, created_by, created_at, marking_script, marking_setup_id, task_type, is_active, sample_file, sample_file_name, allow_multiple, max_attempts, question_text, practical_mode)
                           VALUES (?, ?, ?, ?, ?, ?, ?, 'practical', ?, ?, ?, 0, 1, ?, 'upload')""",
                        (subject_id, title, request.form.get("assign_date"), username, now, "marking_experiment_adapter", setup_id,
                         1 if request.form.get("is_active") else 0, starter_blob, secure_filename(starter.filename), instructions),
                    )
                    task_id = cursor.lastrowid
                    for group in request.form.getlist("groups"):
                        cursor.execute("INSERT INTO task_groups (task_id, group_name) VALUES (?, ?)", (task_id, group))
                    for teacher in request.form.getlist("teachers"):
                        cursor.execute("INSERT INTO task_teachers (task_id, teacher_username) VALUES (?, ?)", (task_id, teacher))
                    if paper_blob and paper_name:
                        cursor.execute("INSERT INTO task_resources (task_id, file_name, file_blob, created_at) VALUES (?, ?, ?, ?)", (task_id, paper_name, paper_blob, now))
                    for support in request.files.getlist("support_files"):
                        if support and support.filename:
                            cursor.execute("INSERT INTO task_resources (task_id, file_name, file_blob, created_at) VALUES (?, ?, ?, ?)", (task_id, secure_filename(support.filename), support.read(), now))
                    conn.commit()
                finally:
                    conn.close()
                log_activity(username, f"created no-code Word practical task {title}")
                return redirect(url_for("manage_tasks", subject_id=subject_id))
            except Exception as exc:
                error = str(exc)

        return render_template(
            "custom_word_task.html",
            subject_id=subject_id,
            subject_name=subject[0],
            groups=groups,
            teachers=get_teachers(),
            rules=RULES,
            username=username,
            today=datetime.now().date().isoformat(),
            error=error,
        )
