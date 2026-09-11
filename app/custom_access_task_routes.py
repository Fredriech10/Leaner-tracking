"""Teacher-facing no-code builder for Microsoft Access upload tasks."""

import json
from datetime import datetime

from flask import redirect, render_template, request, session, url_for
from werkzeug.utils import secure_filename

from app.database import get_db, get_marking_db, get_teachers, get_user_role, log_activity


RULES = {
    "table_exists": ("Tables", "Table exists", "table_exists"),
    "field_exists": ("Fields", "Field exists", "field_exists"),
    "field_size": ("Fields", "Field size", "field_size"),
    "field_data_type": ("Fields", "Field data type", "field_data_type"),
    "field_required": ("Fields", "Field is required", "field_required"),
    "field_default": ("Fields", "Field default value", "field_default"),
    "field_validation_rule": ("Fields", "Validation rule contains", "field_validation_rule"),
    "field_validation_text": ("Fields", "Validation text contains", "field_validation_text"),
    "field_input_mask": ("Fields", "Input mask contains", "field_input_mask"),
    "field_format": ("Fields", "Field format contains", "field_format"),
    "field_lookup_present": ("Fields", "Lookup field is configured", "field_lookup_present"),
    "field_lookup_type": ("Fields", "Lookup type", "field_lookup_type"),
    "field_lookup_values": ("Fields", "Lookup value list contains", "field_lookup_values"),
    "field_display_control": ("Fields", "Lookup display control", "field_display_control"),
    "primary_key": ("Keys", "Primary key includes field", "primary_key"),
    "query_exists": ("Queries", "Query exists", "query_exists"),
    "query_source_contains": ("Queries", "Query source table/query", "query_source_contains"),
    "query_fields": ("Queries", "Query includes fields", "query_fields"),
    "query_criteria_contains": ("Queries", "Query criterion contains", "query_criteria_contains"),
    "query_group_by": ("Queries", "Query groups by fields", "query_group_by"),
    "query_aggregate": ("Queries", "Query aggregate", "query_aggregate"),
    "query_sort_order": ("Queries", "Query sort order contains", "query_sort_order"),
    "form_exists": ("Forms", "Form exists", "form_exists"),
    "form_record_source": ("Forms", "Form record source", "form_record_source"),
    "form_control_source": ("Forms", "Form contains bound control", "form_control_source"),
    "form_caption_contains": ("Forms", "Form caption contains", "form_caption_contains"),
    "form_caption_style": ("Forms", "Form caption alignment/style", "form_caption_style"),
    "form_image_contains": ("Forms", "Form image file contains", "form_image_contains"),
    "form_expression_contains": ("Forms", "Form expression contains", "form_expression_contains"),
    "form_footer_control_source": ("Forms", "Form footer control source", "form_footer_control_source"),
    "form_footer_expression_contains": ("Forms", "Form footer expression contains", "form_footer_expression_contains"),
    "form_control_order": ("Forms", "Form control order", "form_control_order"),
    "report_exists": ("Reports", "Report exists", "report_exists"),
    "report_record_source": ("Reports", "Report record source", "report_record_source"),
    "report_control_source": ("Reports", "Report contains bound control", "report_control_source"),
    "report_caption_contains": ("Reports", "Report caption contains", "report_caption_contains"),
    "report_group_control": ("Reports", "Report grouped field", "report_group_control"),
    "report_group_order": ("Reports", "Report grouping order", "report_group_order"),
    "report_control_order": ("Reports", "Report control order", "report_control_order"),
    "report_expression_contains": ("Reports", "Report expression contains", "report_expression_contains"),
}

_FIELD_RULES = {key for key, value in RULES.items() if value[0] == "Fields"}
_TABLE_RULES = {"table_exists", "primary_key"}
_QUERY_RULES = {key for key, value in RULES.items() if value[0] == "Queries"}
_FORM_RULES = {key for key, value in RULES.items() if value[0] == "Forms"}
_REPORT_RULES = {key for key, value in RULES.items() if value[0] == "Reports"}
_AUTO_VALUE_RULES = {"field_exists", "field_lookup_present"}


def _rule_from_form(index: int):
    key = request.form.get(f"rule_{index}", "")
    description = request.form.get(f"description_{index}", "").strip()
    if key not in RULES or not description:
        return None

    table = request.form.get(f"table_{index}", "").strip()
    field = request.form.get(f"field_{index}", "").strip()
    query = request.form.get(f"query_{index}", "").strip()
    object_name = request.form.get(f"object_{index}", "").strip()
    value = request.form.get(f"value_{index}", "").strip()
    check_type = RULES[key][2]

    if check_type in _FIELD_RULES and (not table or not field):
        raise ValueError(f"Criterion {index + 1} needs a table and field name.")
    if check_type == "primary_key" and (not table or not field):
        raise ValueError(f"Criterion {index + 1} needs a table and key field.")
    if check_type == "table_exists" and not table:
        raise ValueError(f"Criterion {index + 1} needs a table name.")
    if check_type in _QUERY_RULES and not query:
        raise ValueError(f"Criterion {index + 1} needs a query name.")
    if check_type in _FORM_RULES | _REPORT_RULES and not object_name:
        raise ValueError(f"Criterion {index + 1} needs a form or report name.")

    if check_type in _AUTO_VALUE_RULES:
        value = "true"
    elif check_type == "table_exists":
        value = table
    elif check_type == "primary_key":
        value = field
    elif check_type in {"query_exists", "form_exists", "report_exists"}:
        value = query or object_name
    elif not value:
        raise ValueError(f"Criterion {index + 1} needs an expected value.")

    target = {key: value for key, value in {
        "table": table, "field": field, "query": query, "object": object_name,
    }.items() if value}
    return {
        "question_number": str(index + 1),
        "description": description,
        "domain": "access",
        "type": check_type,
        "target": target,
        "expected": value,
        "marks": 1,
        "builder_rule": key,
        "builder_values": {"table": table, "field": field, "query": query, "object": object_name, "value": value},
        "builder_target": "",
    }


def register_custom_access_task_routes(app):
    @app.route("/subjects/<int:subject_id>/custom_access_task", methods=["GET", "POST"])
    @app.route("/tasks/<int:task_id>/access_builder/edit", methods=["GET", "POST"])
    def custom_access_task(subject_id=None, task_id=None):
        username = session.get("username")
        if not username or get_user_role(username) not in {"teacher", "admin"}:
            return "Access denied", 403

        conn = get_db()
        existing = None
        if task_id:
            existing = conn.execute(
                "SELECT subject_id,name,assign_date,question_text,is_active,marking_setup_id FROM tasks WHERE id=? AND task_type='practical'",
                (task_id,),
            ).fetchone()
            if not existing or not existing[5]:
                conn.close()
                return "This task does not have a no-code Access marking setup.", 404
            subject_id = existing[0]

        subject = conn.execute("SELECT name FROM subjects WHERE id=?", (subject_id,)).fetchone()
        groups = [row[0] for row in conn.execute("SELECT DISTINCT group_name FROM users WHERE group_name IS NOT NULL ORDER BY group_name")]
        if not subject:
            conn.close()
            return "Subject not found", 404

        criteria = []
        if existing:
            marking_conn = get_marking_db()
            row = marking_conn.execute("SELECT json_script_blob FROM marking_setups WHERE id=?", (existing[5],)).fetchone()
            marking_conn.close()
            setup = json.loads((row[0] or b"{}").decode()) if row else {}
            if setup.get("program") != "access":
                conn.close()
                return "This is not an Access builder setup.", 400
            criteria = setup.get("builder_criteria", [])

        error = None
        if request.method == "POST":
            try:
                title = request.form.get("title", "").strip()
                count = int(request.form.get("criterion_count", "0") or 0)
                rules = [rule for index in range(count) if (rule := _rule_from_form(index))]
                if not title or not rules:
                    raise ValueError("Task name and at least one marking criterion are required.")
                instructions = request.form.get("instructions", "").strip()
                now = datetime.now().isoformat()
                setup = {"task_name": title, "program": "access", "file": "student_file.accdb", "questions": rules, "builder_criteria": rules, "total_marks": len(rules)}

                if existing:
                    setup_id = existing[5]
                    marking_conn = get_marking_db()
                    marking_conn.execute("UPDATE marking_setups SET title=?,notes=?,json_script_blob=?,updated_at=? WHERE id=?", (title, instructions, json.dumps(setup).encode(), now, setup_id))
                    marking_conn.commit()
                    marking_conn.close()
                    conn.execute("UPDATE tasks SET name=?,assign_date=?,question_text=?,is_active=? WHERE id=?", (title, request.form.get("assign_date"), instructions, 1 if request.form.get("is_active") else 0, task_id))
                    conn.execute("DELETE FROM task_groups WHERE task_id=?", (task_id,))
                    conn.executemany("INSERT INTO task_groups (task_id,group_name) VALUES (?,?)", [(task_id, group) for group in request.form.getlist("groups")])
                    conn.execute("DELETE FROM task_teachers WHERE task_id=?", (task_id,))
                    conn.executemany("INSERT INTO task_teachers (task_id,teacher_username) VALUES (?,?)", [(task_id, teacher) for teacher in request.form.getlist("teachers")])
                    conn.commit()
                else:
                    starter = request.files.get("starter_file")
                    if not starter or not starter.filename or not starter.filename.lower().endswith((".accdb", ".mdb")):
                        raise ValueError("An Access starter database (.accdb or .mdb) is required.")
                    blob, name = starter.read(), secure_filename(starter.filename)
                    marking_conn = get_marking_db()
                    cursor = marking_conn.cursor()
                    cursor.execute(
                        "INSERT INTO marking_setups (title,created_by,created_at,updated_at,json_script_filename,json_script_blob,notes,starter_file_filename,starter_file_blob) VALUES (?,?,?,?,?,?,?,?,?)",
                        (title, username, now, now, "access_builder.json", json.dumps(setup).encode(), instructions, name, blob),
                    )
                    setup_id = cursor.lastrowid
                    marking_conn.commit()
                    marking_conn.close()
                    cursor = conn.cursor()
                    cursor.execute(
                        "INSERT INTO tasks (subject_id,name,assign_date,created_by,created_at,marking_script,marking_setup_id,task_type,is_active,sample_file,sample_file_name,allow_multiple,max_attempts,question_text,practical_mode) VALUES (?,?,?,?,?,'marking_experiment_adapter',?,'practical',?,?,?,0,1,?,'upload')",
                        (subject_id, title, request.form.get("assign_date"), username, now, setup_id, 1 if request.form.get("is_active") else 0, blob, name, instructions),
                    )
                    task_id = cursor.lastrowid
                    conn.executemany("INSERT INTO task_groups (task_id,group_name) VALUES (?,?)", [(task_id, group) for group in request.form.getlist("groups")])
                    conn.executemany("INSERT INTO task_teachers (task_id,teacher_username) VALUES (?,?)", [(task_id, teacher) for teacher in request.form.getlist("teachers")])
                    conn.commit()

                log_activity(username, f"saved no-code Access practical task {title}")
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
        return render_template("custom_access_task.html", subject_id=subject_id, subject_name=subject[0], groups=groups, teachers=get_teachers(), rules=RULES, username=username, today=datetime.now().date().isoformat(), error=error, editing_task=editing, initial_criteria=criteria)
