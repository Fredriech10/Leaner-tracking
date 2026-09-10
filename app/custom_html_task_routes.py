"""Teacher-facing no-code builder for HTML upload tasks."""

import json
from datetime import datetime

from flask import redirect, render_template, request, session, url_for
from werkzeug.utils import secure_filename

from app.database import get_db, get_marking_db, get_teachers, get_user_role, log_activity
from marking.tasks.marking_experiment_adapter import mark_with_setup


RULES = {
    "document_structure": ("Document", "HTML document structure", "document_structure"),
    "document_title": ("Document", "Browser title", "document_title"),
    "body_background_color": ("Body", "Body background colour", "body_background_color"),
    "element_text": ("Text and headings", "Element text", "element_text"),
    "element_has_child_tag": ("Text and headings", "Element contains formatting tag", "element_has_child_tag"),
    "element_attribute": ("Text and headings", "Element attribute", "element_attribute"),
    "html_comment_contains": ("Document", "HTML comment contains text", "html_comment_contains"),
    "list_exists": ("Lists", "List type present", "list_exists"),
    "list_item_contains": ("Lists", "List item text", "list_item_contains"),
    "list_minimum_items": ("Lists", "Minimum list items", "list_minimum_items"),
    "horizontal_rule": ("Layout", "Horizontal rule", "horizontal_rule"),
    "line_break": ("Layout", "Line break", "line_break"),
    "link_href": ("Links", "Link destination", "link_href"),
    "link_present": ("Links", "Hyperlink present", "link_present"),
    "link_text": ("Links", "Link display text", "link_text"),
    "image_src": ("Images", "Image source", "image_src"),
    "image_alt": ("Images", "Image alternative text", "image_alt"),
    "table_cell_text": ("Tables", "Table cell text", "table_cell_text"),
}


def _rule_from_form(index):
    key = request.form.get(f"rule_{index}", "")
    description = request.form.get(f"description_{index}", "").strip()
    if key not in RULES or not description:
        return None
    tag = request.form.get(f"tag_{index}", "").strip().lower()
    text = request.form.get(f"target_{index}", "").strip()
    value = request.form.get(f"value_{index}", "").strip()
    attribute = request.form.get(f"attribute_{index}", "").strip().lower()
    _, _, check_type = RULES[key]
    target = {k: v for k, v in {"tag": tag, "text": text, "attribute": attribute}.items() if v}
    expected = value
    if check_type == "element_attribute":
        if not tag or not attribute or not value:
            raise ValueError("Element attribute criteria need a tag, attribute and expected value.")
        expected = {"attribute": attribute, "value": value}
    elif check_type in {"element_text", "element_has_child_tag", "document_title", "body_background_color", "html_comment_contains", "list_exists", "list_item_contains", "link_href", "link_text", "image_src", "image_alt", "table_cell_text"} and not value:
        raise ValueError(f"Criterion {index + 1} needs an expected value.")
    elif check_type == "list_minimum_items":
        if tag not in {"ul", "ol"} or not value.isdigit():
            raise ValueError("Minimum list items needs list type (ul or ol) and a whole number.")
        expected = int(value)
    elif check_type == "horizontal_rule" and attribute and not value:
        raise ValueError("A horizontal-rule attribute needs an expected value.")
    return {"question_number": str(index + 1), "description": description, "domain": "html", "type": check_type, "target": target, "expected": expected, "marks": 1, "builder_rule": key, "builder_values": {"tag": tag, "value": value, "attribute": attribute}, "builder_target": text}


def _render(subject_id, subject_name, groups, username, error=None, editing_task=None, criteria=None):
    return render_template("custom_html_task.html", subject_id=subject_id, subject_name=subject_name, groups=groups, teachers=get_teachers(), rules=RULES, username=username, today=datetime.now().date().isoformat(), error=error, editing_task=editing_task, initial_criteria=criteria or [])


def register_custom_html_task_routes(app):
    @app.route("/html_marking_setups/<int:setup_id>/test", methods=["GET", "POST"])
    def test_html_marking_setup(setup_id):
        username = session.get("username")
        if not username or get_user_role(username) not in {"teacher", "admin"}:
            return "Access denied", 403
        error = result = None
        if request.method == "POST":
            sample = request.files.get("sample_submission")
            if not sample or not sample.filename or not sample.filename.lower().endswith((".html", ".htm")):
                error = "Choose a completed HTML file (.html or .htm)."
            else:
                import os, tempfile
                path = None
                try:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".html") as handle:
                        sample.save(handle); path = handle.name
                    result = mark_with_setup(path, setup_id)
                    error = result.get("error")
                finally:
                    if path:
                        try: os.unlink(path)
                        except OSError: pass
        return render_template("test_marking_setup.html", setup_id=setup_id, setup_title="HTML marking setup", error=error, result=result)

    @app.route("/subjects/<int:subject_id>/custom_html_task", methods=["GET", "POST"])
    @app.route("/tasks/<int:task_id>/html_builder/edit", methods=["GET", "POST"])
    def custom_html_task(subject_id=None, task_id=None):
        username = session.get("username")
        if not username or get_user_role(username) not in {"teacher", "admin"}:
            return "Access denied", 403
        conn = get_db()
        existing = None
        if task_id is not None:
            existing = conn.execute("SELECT subject_id, name, assign_date, question_text, is_active, marking_setup_id FROM tasks WHERE id=? AND task_type='practical'", (task_id,)).fetchone()
            if not existing or not existing[5]:
                conn.close(); return "This task does not have a no-code HTML marking setup.", 404
            subject_id = existing[0]
        subject = conn.execute("SELECT name FROM subjects WHERE id=?", (subject_id,)).fetchone()
        groups = [row[0] for row in conn.execute("SELECT DISTINCT group_name FROM users WHERE group_name IS NOT NULL ORDER BY group_name")]
        if not subject:
            conn.close(); return "Subject not found", 404
        criteria = []
        if existing:
            marking_conn = get_marking_db()
            row = marking_conn.execute("SELECT json_script_blob FROM marking_setups WHERE id=?", (existing[5],)).fetchone()
            marking_conn.close()
            setup = json.loads((row[0] or b"{}").decode("utf-8")) if row else {}
            if setup.get("program") != "html": conn.close(); return "This is not an HTML builder setup.", 400
            criteria = setup.get("builder_criteria", [])
        error = None
        if request.method == "POST":
            try:
                title = request.form.get("title", "").strip()
                if not title: raise ValueError("Task name is required.")
                rules = [rule for index in range(int(request.form.get("criterion_count", "0") or 0)) if (rule := _rule_from_form(index))]
                if not rules: raise ValueError("Add at least one marking criterion.")
                instructions = request.form.get("instructions", "").strip()
                now = datetime.now().isoformat()
                starter = request.files.get("starter_file")
                paper = request.files.get("question_paper")
                if existing:
                    setup_id = existing[5]
                    setup = {"task_name": title, "program": "html", "file": "student_file.html", "questions": rules, "builder_criteria": rules, "total_marks": len(rules)}
                    mc = get_marking_db(); mc.execute("UPDATE marking_setups SET title=?, notes=?, json_script_blob=?, updated_at=? WHERE id=?", (title, instructions, json.dumps(setup).encode("utf-8"), now, setup_id)); mc.commit(); mc.close()
                    conn.execute("UPDATE tasks SET name=?, assign_date=?, question_text=?, is_active=? WHERE id=?", (title, request.form.get("assign_date"), instructions, 1 if request.form.get("is_active") else 0, task_id))
                    conn.execute("DELETE FROM task_groups WHERE task_id=?", (task_id,)); conn.executemany("INSERT INTO task_groups (task_id, group_name) VALUES (?, ?)", [(task_id, group) for group in request.form.getlist("groups")])
                    conn.execute("DELETE FROM task_teachers WHERE task_id=?", (task_id,)); conn.executemany("INSERT INTO task_teachers (task_id, teacher_username) VALUES (?, ?)", [(task_id, teacher) for teacher in request.form.getlist("teachers")]); conn.commit()
                else:
                    if not starter or not starter.filename or not starter.filename.lower().endswith((".html", ".htm")):
                        raise ValueError("An HTML starter file is required.")
                    starter_blob, starter_name = starter.read(), secure_filename(starter.filename)
                    paper_blob = paper.read() if paper and paper.filename else None; paper_name = secure_filename(paper.filename) if paper and paper.filename else None
                    setup = {"task_name": title, "program": "html", "file": "student_file.html", "questions": rules, "builder_criteria": rules, "total_marks": len(rules)}
                    mc = get_marking_db(); cursor = mc.cursor(); cursor.execute("INSERT INTO marking_setups (title, created_by, created_at, updated_at, question_paper_filename, question_paper_blob, json_script_filename, json_script_blob, notes, starter_file_filename, starter_file_blob) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (title, username, now, now, paper_name, paper_blob, f"{secure_filename(title)}.json", json.dumps(setup).encode("utf-8"), instructions, starter_name, starter_blob)); setup_id = cursor.lastrowid; mc.commit(); mc.close()
                    cursor = conn.cursor(); cursor.execute("INSERT INTO tasks (subject_id,name,assign_date,created_by,created_at,marking_script,marking_setup_id,task_type,is_active,sample_file,sample_file_name,allow_multiple,max_attempts,question_text,practical_mode) VALUES (?, ?, ?, ?, ?, 'marking_experiment_adapter', ?, 'practical', ?, ?, ?, 0, 1, ?, 'upload')", (subject_id,title,request.form.get("assign_date"),username,now,setup_id,1 if request.form.get("is_active") else 0,starter_blob,starter_name,instructions)); task_id=cursor.lastrowid
                    conn.executemany("INSERT INTO task_groups (task_id, group_name) VALUES (?, ?)", [(task_id, group) for group in request.form.getlist("groups")]); conn.executemany("INSERT INTO task_teachers (task_id, teacher_username) VALUES (?, ?)", [(task_id, teacher) for teacher in request.form.getlist("teachers")])
                    if paper_blob: conn.execute("INSERT INTO task_resources (task_id,file_name,file_blob,created_at) VALUES (?, ?, ?, ?)", (task_id,paper_name,paper_blob,now))
                    conn.commit()
                log_activity(username, f"saved no-code HTML practical task {title}")
                return redirect(url_for("manage_tasks", subject_id=subject_id))
            except Exception as exc:
                error = str(exc)
        editing = None
        if existing:
            editing = {
                "name": existing[1], "assign_date": existing[2], "instructions": existing[3], "is_active": existing[4],
                "groups": {row[0] for row in conn.execute("SELECT group_name FROM task_groups WHERE task_id=?", (task_id,))},
                "teachers": {row[0] for row in conn.execute("SELECT teacher_username FROM task_teachers WHERE task_id=?", (task_id,))},
            }
        conn.close()
        return _render(subject_id, subject[0], groups, username, error, editing, criteria)
