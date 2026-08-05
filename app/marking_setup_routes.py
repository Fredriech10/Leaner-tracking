import io
import json
import tempfile
from datetime import datetime
from pathlib import Path

from flask import redirect, render_template, request, send_file, session, url_for
from werkzeug.utils import secure_filename

from app.database import get_marking_db, get_user_role
from app.helper_common import safe_int


def register_marking_setup_routes(app):
    @app.route("/marking_setup", methods=["GET", "POST"])
    def marking_setup():
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))
        if get_user_role(username) not in ["teacher", "admin"]:
            return "Access denied", 403

        error = None
        message = None
        generated_json_preview = ""
        llm_output_preview = ""
        llm_normalized_output_preview = ""
        generation_warnings_preview = []
        llm_status = ""

        conn = get_marking_db()
        cursor = conn.cursor()

        if request.method == "POST":
            action = request.form.get("action")
            if action == "delete_one":
                setup_id = request.form.get("setup_id")
                cursor.execute("DELETE FROM marking_setups WHERE id = ?", (setup_id,))
                conn.commit()
                message = "Marking setup deleted."
            elif action == "delete_selected":
                setup_ids = [sid for sid in request.form.getlist("setup_ids") if sid.strip()]
                if setup_ids:
                    placeholders = ",".join("?" for _ in setup_ids)
                    cursor.execute(f"DELETE FROM marking_setups WHERE id IN ({placeholders})", setup_ids)
                    conn.commit()
                    message = f"Deleted {len(setup_ids)} marking setup(s)."
                else:
                    error = "Select at least one marking setup to delete."
            else:
                title = (request.form.get("title") or "").strip()
                notes = (request.form.get("notes") or "").strip()
                llm_model = (request.form.get("llm_model") or "").strip() or None
                question_paper_file = request.files.get("question_paper_file")
                memo_file = request.files.get("memo_file")

                if not title or not question_paper_file or not question_paper_file.filename or not memo_file or not memo_file.filename:
                    error = "Title, question paper, and memo are required."
                else:
                    from Marking_Experiment.generation_service import generate_marking_task_json

                    qp_suffix = Path(question_paper_file.filename).suffix or ".docx"
                    memo_suffix = Path(memo_file.filename).suffix or ".docx"
                    qp_temp = None
                    memo_temp = None
                    try:
                        with tempfile.NamedTemporaryFile(delete=False, suffix=qp_suffix) as qp_handle:
                            question_paper_blob = question_paper_file.read()
                            qp_handle.write(question_paper_blob)
                            qp_temp = Path(qp_handle.name)
                        with tempfile.NamedTemporaryFile(delete=False, suffix=memo_suffix) as memo_handle:
                            memo_blob = memo_file.read()
                            memo_handle.write(memo_blob)
                            memo_temp = Path(memo_handle.name)

                        generated = generate_marking_task_json(qp_temp, memo_temp, title, model=llm_model)
                        task_definition = generated["task_definition"]
                        generated_json_text = json.dumps(task_definition, indent=2, ensure_ascii=False)
                        generated_json_preview = generated_json_text
                        llm_output_preview = generated.get("llm_output") or ""
                        llm_normalized_output_preview = generated.get("llm_normalized_output") or ""
                        generation_warnings_preview = generated.get("warnings") or []
                        llm_status = generated.get("llm_status") or ""

                        now = datetime.now().isoformat()
                        cursor.execute(
                            """
                            INSERT INTO marking_setups (
                                title, created_by, created_at, updated_at,
                                question_paper_filename, question_paper_blob,
                                memo_filename, memo_blob,
                                json_script_filename, json_script_blob,
                                llm_model, generation_warnings, generation_error, notes
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                title,
                                username,
                                now,
                                now,
                                secure_filename(question_paper_file.filename),
                                question_paper_blob,
                                secure_filename(memo_file.filename),
                                memo_blob,
                                f"{secure_filename(title) or 'marking_setup'}.json",
                                generated_json_text.encode("utf-8"),
                                llm_model,
                                json.dumps(generation_warnings_preview, ensure_ascii=False),
                                None,
                                notes,
                            ),
                        )
                        conn.commit()
                        message = "Marking setup generated and saved."
                    except Exception as exc:
                        error = f"Failed to generate marking setup: {exc}"
                    finally:
                        for temp_path in (qp_temp, memo_temp):
                            if temp_path and temp_path.exists():
                                temp_path.unlink()

        cursor.execute(
            """
            SELECT id, title, created_by, created_at,
                   question_paper_filename, memo_filename, json_script_filename, notes
            FROM marking_setups
            ORDER BY created_at DESC, id DESC
            """
        )
        setups = cursor.fetchall()
        conn.close()

        return render_template(
            "marking_setup.html",
            setups=setups,
            error=error,
            message=message,
            generated_json_preview=generated_json_preview,
            llm_output_preview=llm_output_preview,
            llm_normalized_output_preview=llm_normalized_output_preview,
            generation_warnings_preview=generation_warnings_preview,
            llm_status=llm_status,
        )

    @app.route("/marking_setup/<int:setup_id>/download/<field>")
    def download_marking_blob(setup_id, field):
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))
        if get_user_role(username) not in ["teacher", "admin"]:
            return "Access denied", 403

        field_map = {
            "question_paper": ("question_paper_filename", "question_paper_blob"),
            "memo": ("memo_filename", "memo_blob"),
            "json_script": ("json_script_filename", "json_script_blob"),
        }
        if field not in field_map:
            return "File type not found", 404

        filename_field, blob_field = field_map[field]
        conn = get_marking_db()
        cursor = conn.cursor()
        cursor.execute(f"SELECT {filename_field}, {blob_field} FROM marking_setups WHERE id = ?", (setup_id,))
        row = cursor.fetchone()
        conn.close()
        if not row or not row[1]:
            return "File not found", 404

        return send_file(
            io.BytesIO(row[1]),
            as_attachment=True,
            download_name=row[0] or f"{field}_{setup_id}",
            mimetype="application/octet-stream",
        )

    @app.route("/marking_setup/<int:setup_id>/edit", methods=["GET", "POST"])
    def edit_marking_setup(setup_id):
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))
        if get_user_role(username) not in ["teacher", "admin"]:
            return "Access denied", 403

        conn = get_marking_db()
        cursor = conn.cursor()
        cursor.execute("SELECT title, notes, json_script_blob FROM marking_setups WHERE id = ?", (setup_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return "Marking setup not found", 404

        title, notes, json_blob = row
        error = None
        message = None
        try:
            task_definition = json.loads((json_blob or b"{}").decode("utf-8") if isinstance(json_blob, bytes) else (json_blob or "{}"))
        except Exception:
            task_definition = {}
        questions = task_definition.get("questions", []) if isinstance(task_definition, dict) else []

        if request.method == "POST":
            try:
                row_count = safe_int(request.form.get("row_count"), len(questions))
                updated_questions = []
                for idx in range(row_count):
                    if not request.form.get(f"enabled_{idx}"):
                        continue
                    target_json = request.form.get(f"target_{idx}", "{}").strip() or "{}"
                    expected_json = request.form.get(f"expected_{idx}", "true").strip() or "true"
                    updated_questions.append(
                        {
                            "question_number": request.form.get(f"question_number_{idx}", "").strip(),
                            "description": request.form.get(f"description_{idx}", "").strip(),
                            "domain": request.form.get(f"domain_{idx}", "").strip(),
                            "type": request.form.get(f"type_{idx}", "").strip(),
                            "target": json.loads(target_json),
                            "expected": json.loads(expected_json),
                            "marks": safe_int(request.form.get(f"marks_{idx}"), 1),
                        }
                    )

                task_definition["task_name"] = (request.form.get("task_name") or title).strip()
                task_definition["program"] = (request.form.get("program") or task_definition.get("program") or "word").strip()
                task_definition["file"] = (request.form.get("file") or task_definition.get("file") or "student_file.docx").strip()
                task_definition["questions"] = updated_questions
                task_definition["total_marks"] = sum(int(question.get("marks", 1)) for question in updated_questions)

                encoded = json.dumps(task_definition, indent=2, ensure_ascii=False).encode("utf-8")
                notes = request.form.get("notes", "")
                cursor.execute(
                    "UPDATE marking_setups SET title = ?, notes = ?, json_script_blob = ?, updated_at = ? WHERE id = ?",
                    (task_definition["task_name"], notes, encoded, datetime.now().isoformat(), setup_id),
                )
                conn.commit()
                title = task_definition["task_name"]
                questions = updated_questions
                message = "Marking setup saved."
            except Exception as exc:
                error = f"Could not save marking setup: {exc}"

        conn.close()
        return render_template(
            "edit_marking_setup.html",
            title=title,
            notes=notes,
            task_definition=task_definition,
            questions=questions,
            error=error,
            message=message,
        )
