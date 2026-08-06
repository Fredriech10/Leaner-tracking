from io import BytesIO

import pandas as pd
from flask import flash, jsonify, redirect, render_template, request, send_file, session, url_for

from app.database import get_db, get_groups, get_teachers, get_user_role, log_activity


def register_admin_routes(app):
    @app.route("/promote/<username>")
    def promote(username):
        admin_user = session.get("username")
        if not admin_user:
            return redirect(url_for("login"))

        admin_role = get_user_role(admin_user)
        if admin_role not in ["teacher", "admin"]:
            return "Access denied", 403

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE users SET role = 'teacher' WHERE username = ?
            """,
            (username,),
        )
        conn.commit()
        conn.close()
        log_activity(admin_user, f"promoted {username} to teacher")
        return redirect(url_for("admin_panel"))

    @app.route("/demote/<username>")
    def demote(username):
        admin_user = session.get("username")
        if not admin_user:
            return redirect(url_for("login"))

        admin_role = get_user_role(admin_user)
        if admin_role not in ["teacher", "admin"]:
            return "Access denied", 403

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE users SET role = 'student' WHERE username = ?
            """,
            (username,),
        )
        conn.commit()
        conn.close()
        log_activity(admin_user, f"demoted {username} to student")
        return redirect(url_for("admin_panel"))

    @app.route("/delete_user/<username>", methods=["POST"])
    def delete_user(username):
        admin_user = session.get("username")
        if not admin_user:
            return redirect(url_for("login"))
        if get_user_role(admin_user) not in ["teacher", "admin"]:
            return "Access denied", 403
        if username == admin_user:
            return "Cannot delete your own account", 400

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM results WHERE username = ?", (username,))
        cursor.execute("DELETE FROM weaknesses WHERE username = ?", (username,))
        cursor.execute("DELETE FROM login_history WHERE username = ?", (username,))
        cursor.execute("DELETE FROM attendance_override WHERE username = ?", (username,))
        cursor.execute("DELETE FROM activities WHERE username = ?", (username,))
        cursor.execute("DELETE FROM learner_notes WHERE username = ?", (username,))
        cursor.execute("DELETE FROM result_removals WHERE username = ?", (username,))
        cursor.execute(
            """
            DELETE FROM theory_answers WHERE submission_id IN
                (SELECT id FROM theory_submissions WHERE username = ?)
            """,
            (username,),
        )
        cursor.execute("DELETE FROM theory_submissions WHERE username = ?", (username,))
        cursor.execute("DELETE FROM users WHERE username = ?", (username,))
        conn.commit()
        conn.close()
        log_activity(admin_user, f"deleted user {username}")
        return redirect(url_for("admin_panel"))

    @app.route("/admin_panel")
    @app.route("/admin")
    def admin_panel():
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))

        role = get_user_role(username)
        if role not in ["teacher", "admin"]:
            return "Access denied", 403

        search = request.args.get("search", "").strip()
        group = request.args.get("group", "").strip()
        sort = request.args.get("sort", "last_active").strip()
        order = request.args.get("order", "desc").lower()

        valid_sorts = {
            "username": "username",
            "full_name": "full_name",
            "group_name": "group_name",
            "teacher_username": "teacher_username",
            "role": "role",
            "last_active": "last_active",
        }

        if sort not in valid_sorts:
            sort = "last_active"
        if order not in ["asc", "desc"]:
            order = "desc"

        conn = get_db()
        cursor = conn.cursor()

        query = """
        SELECT username, full_name, group_name, teacher_username, role, last_active
        FROM users
        WHERE 1=1
        """
        params = []

        if role == "teacher":
            query += " AND (teacher_username = ? OR username = ?)"
            params.extend([username, username])

        if group:
            query += " AND group_name = ?"
            params.append(group)

        query += f" ORDER BY {valid_sorts[sort]} {order.upper()}"
        cursor.execute(query, params)
        users = cursor.fetchall()

        if role == "teacher":
            groups = get_groups(username)
        else:
            cursor.execute("SELECT DISTINCT group_name FROM users WHERE group_name IS NOT NULL")
            groups = [g[0] for g in cursor.fetchall()]

        conn.close()
        teacher_options = [
            {"username": teacher[0], "full_name": teacher[1] or teacher[0]}
            for teacher in get_teachers()
        ]
        return render_template(
            "admin.html",
            users=users,
            groups=groups,
            all_teachers=teacher_options,
            search=search,
            selected_group=group,
            sort=sort,
            order=order,
        )

    @app.route("/admin/update_user_field", methods=["POST"])
    def update_user_field():
        admin_user = session.get("username")
        if not admin_user:
            return jsonify({"ok": False, "error": "Not logged in"}), 401

        admin_role = get_user_role(admin_user)
        if admin_role not in ["teacher", "admin"]:
            return jsonify({"ok": False, "error": "Access denied"}), 403

        payload = request.get_json(silent=True) or {}
        username = (payload.get("username") or "").strip()
        field = (payload.get("field") or "").strip()
        value = payload.get("value")

        allowed_fields = {"full_name", "group_name", "teacher_username"}
        if not username or field not in allowed_fields:
            return jsonify({"ok": False, "error": "Invalid request"}), 400

        if value is None:
            value = ""
        value = str(value).strip()
        if field in {"group_name", "teacher_username"} and value == "":
            value = None

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT username, full_name, group_name, teacher_username, role FROM users WHERE username = ?",
            (username,),
        )
        user = cursor.fetchone()
        if not user:
            conn.close()
            return jsonify({"ok": False, "error": "User not found"}), 404

        if admin_role == "teacher":
            assigned_teacher = user[3] or ""
            if assigned_teacher and assigned_teacher != admin_user:
                conn.close()
                return jsonify({"ok": False, "error": "Access denied"}), 403
            if field == "teacher_username" and value not in {None, admin_user}:
                conn.close()
                return jsonify({"ok": False, "error": "Teachers can only assign themselves"}), 403

        if field == "teacher_username" and value is not None:
            teachers = {teacher[0] for teacher in get_teachers()}
            if value not in teachers:
                conn.close()
                return jsonify({"ok": False, "error": "Teacher not found"}), 400

        if field == "group_name" and value is not None:
            existing_groups = set(get_groups())
            if value not in existing_groups:
                conn.close()
                return jsonify({"ok": False, "error": "Group not found"}), 400

        cursor.execute(f"UPDATE users SET {field} = ? WHERE username = ?", (value, username))
        conn.commit()
        conn.close()
        log_activity(admin_user, f"updated {field} for {username}")
        return jsonify({"ok": True, "value": value or ""})

    @app.route("/import_users", methods=["POST"])
    def import_users():
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))

        role = get_user_role(username)
        if role not in ["teacher", "admin"]:
            return "Access denied", 403

        if "excel_file" not in request.files:
            flash("No file uploaded", "error")
            return redirect(url_for("admin_panel"))

        file = request.files["excel_file"]
        if file.filename == "":
            flash("No file selected", "error")
            return redirect(url_for("admin_panel"))

        filename = file.filename or ""
        if not filename.lower().endswith((".xlsx", ".xls")):
            flash("Please upload an Excel file (.xlsx or .xls)", "error")
            return redirect(url_for("admin_panel"))

        try:
            df = pd.read_excel(file)
            required_columns = ["username", "full_name", "group"]
            missing_columns = [col for col in required_columns if col not in df.columns]
            if missing_columns:
                flash(f"Missing required columns: {', '.join(missing_columns)}", "error")
                return redirect(url_for("admin_panel"))

            conn = get_db()
            cursor = conn.cursor()
            imported_count = 0
            updated_count = 0
            teacher_username_present = "teacher_username" in df.columns
            role_present = "role" in df.columns

            for _, row in df.iterrows():
                username_val = str(row["username"]).strip().upper()
                full_name = str(row["full_name"]).strip()
                group_name = str(row["group"]).strip()

                teacher_username = str(row["teacher_username"]).strip() if teacher_username_present else None
                if teacher_username == "":
                    teacher_username = None

                role_value = str(row["role"]).strip().lower() if role_present else "student"
                if role_value == "" or role_value not in ["student", "teacher", "admin"]:
                    role_value = "student"

                cursor.execute("SELECT username FROM users WHERE username = ?", (username_val,))
                existing = cursor.fetchone()

                columns = ["username", "full_name", "group_name", "teacher_username", "role"]
                values = [username_val, full_name, group_name, teacher_username, role_value]
                update_parts = ["full_name = excluded.full_name", "group_name = excluded.group_name"]

                if teacher_username_present:
                    update_parts.append("teacher_username = excluded.teacher_username")

                if role_present:
                    update_parts.append("role = excluded.role")

                update_clause = ", ".join(update_parts)
                cursor.execute(
                    f"""
                    INSERT INTO users ({', '.join(columns)})
                    VALUES ({', '.join(['?'] * len(columns))})
                    ON CONFLICT(username) DO UPDATE SET
                        {update_clause}
                    """,
                    values,
                )

                if existing:
                    updated_count += 1
                else:
                    imported_count += 1

            conn.commit()
            conn.close()
            log_activity(username, "imported users from Excel")
            flash(
                f"Successfully imported {imported_count} new users and updated {updated_count} existing users.",
                "success",
            )
        except Exception as exc:
            flash(f"Error importing users: {str(exc)}", "error")

        return redirect(url_for("admin_panel"))

    @app.route("/download_user_template")
    def download_user_template():
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))
        if get_user_role(username) not in ["teacher", "admin"]:
            return "Access denied", 403

        sample_data = {
            "username": ["STUDENT001", "STUDENT002", "STUDENT003"],
            "full_name": ["Smith, John", "Doe, Jane", "Johnson, Bob"],
            "group": ["12A", "12A", "12B"],
            "teacher_username": ["TEACHER1", "TEACHER1", "TEACHER2"],
            "role": ["student", "student", "student"],
        }
        df = pd.DataFrame(sample_data)

        buffer = BytesIO()
        df.to_excel(buffer, index=False)
        buffer.seek(0)

        return send_file(
            buffer,
            as_attachment=True,
            download_name="user_import_template.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    @app.route("/recent_activity")
    def recent_activity():
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))
        role = get_user_role(username)
        if role not in ["teacher", "admin"]:
            return "Access denied", 403

        conn = get_db()
        cursor = conn.cursor()
        if role == "teacher":
            cursor.execute(
                """
                SELECT a.username, a.action, strftime('%Y-%m-%d %H:%M:%S', a.timestamp)
                FROM activities a
                LEFT JOIN users u ON u.username = a.username
                WHERE a.username = ?
                  OR (u.role = 'student' AND u.teacher_username = ?)
                ORDER BY a.timestamp DESC LIMIT 100
                """,
                (username, username),
            )
        else:
            cursor.execute(
                """
                SELECT username, action, strftime('%Y-%m-%d %H:%M:%S', timestamp)
                FROM activities ORDER BY timestamp DESC LIMIT 100
                """
            )
        activities = cursor.fetchall()
        conn.close()
        return render_template("recent_activity.html", activities=activities)

    @app.route("/edit_user/<username>", methods=["GET", "POST"])
    def edit_user(username):
        admin_user = session.get("username")
        if not admin_user:
            return redirect(url_for("login"))

        if get_user_role(admin_user) not in ["teacher", "admin"]:
            return "Access denied", 403

        next_url = request.args.get("next") or request.form.get("next")
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT username, full_name, group_name, teacher_username, role FROM users WHERE username = ?",
            (username,),
        )
        user = cursor.fetchone()
        if not user:
            conn.close()
            return "User not found", 404

        if get_user_role(admin_user) == "teacher":
            assigned_teacher = user[3] or ""
            if assigned_teacher and assigned_teacher != admin_user:
                conn.close()
                return "Access denied", 403
            if not assigned_teacher and user[4] != "student":
                conn.close()
                return "Access denied", 403

        if request.method == "POST":
            full_name = request.form.get("full_name")
            group_name = request.form.get("group_name")
            teacher_username = request.form.get("teacher_username") or None
            role_value = request.form.get("role") or "student"

            if role_value == "admin" and get_user_role(admin_user) != "admin":
                return "Access denied", 403

            cursor.execute(
                """
                UPDATE users
                SET full_name = ?, group_name = ?, teacher_username = ?, role = ?
                WHERE username = ?
                """,
                (full_name, group_name, teacher_username, role_value, username),
            )
            conn.commit()
            log_activity(admin_user, f"edited user {username}")
            conn.close()
            if next_url:
                return redirect(next_url)
            return redirect(url_for("admin_panel"))

        all_teachers = get_teachers()
        current_role = get_user_role(admin_user)
        conn.close()
        return render_template("edit_user.html", user=user, next_url=next_url, all_teachers=all_teachers, current_role=current_role)
