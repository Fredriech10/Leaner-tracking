import sqlite3
from datetime import datetime

from flask import flash, jsonify, redirect, render_template, request, session, url_for

from app.database import get_db, get_groups, get_user_role
from app.helpers import (
    add_communication_message,
    create_communication_thread,
    get_student_unread_message_count,
    get_teacher_quick_action_catalog,
    get_teacher_unread_message_count,
    mark_student_threads_read,
    student_has_fresh_teacher_reply,
)


def register_communication_routes(app):
    @app.route("/teacher_dashboard/quick_actions", methods=["POST"])
    def update_teacher_quick_actions():
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))
        role = get_user_role(username)
        if role not in ["teacher", "admin"]:
            return "Access denied", 403

        selected = request.form.getlist("quick_actions")
        valid_ids = {action["key"] for action in get_teacher_quick_action_catalog()}
        selected = [action_id for action_id in selected if action_id in valid_ids]

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM teacher_quick_actions WHERE username = ?", (username,))
        for action_id in selected:
            cursor.execute(
                """
                INSERT INTO teacher_quick_actions (username, action_key)
                VALUES (?, ?)
                """,
                (username, action_id),
            )
        conn.commit()
        conn.close()
        return redirect(url_for("teacher_dashboard"))

    @app.route("/student/attendance_review_request", methods=["POST"])
    def student_attendance_review_request():
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))
        if get_user_role(username) != "student":
            return "Access denied", 403

        attendance_date = request.form.get("attendance_date", "").strip()
        message = request.form.get("message", "").strip()
        if not attendance_date:
            flash("Attendance date is required.", "error")
            return redirect(url_for("student_dashboard"))

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT teacher_username, full_name
            FROM users
            WHERE username = ?
            """,
            (username,),
        )
        row = cursor.fetchone()
        if not row or not row[0]:
            conn.close()
            flash("No teacher is assigned to this learner.", "error")
            return redirect(url_for("student_dashboard"))

        teacher_username = row[0]
        thread_id = create_communication_thread(
            cursor,
            username,
            "attendance_review",
            subject_line="Attendance review request",
            attendance_date=attendance_date,
            initial_message=message or f"Please review my attendance for {attendance_date}.",
            chat_session_id=session.get("chat_session_id", ""),
        )
        cursor.execute(
            """
            UPDATE communication_threads
            SET teacher_username = ?
            WHERE id = ?
            """,
            (teacher_username, thread_id),
        )
        conn.commit()
        conn.close()
        flash("Attendance review request submitted.", "success")
        return redirect(url_for("student_dashboard"))

    @app.route("/student/send_message", methods=["POST"])
    def student_send_message():
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))
        if get_user_role(username) != "student":
            return "Access denied", 403

        topic = (request.form.get("topic") or "chat").strip() or "chat"
        message = (request.form.get("message") or "").strip()
        if not message:
            flash("Message cannot be empty.", "error")
            return redirect(url_for("student_dashboard"))

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT teacher_username
            FROM users
            WHERE username = ?
            """,
            (username,),
        )
        row = cursor.fetchone()
        if not row or not row[0]:
            conn.close()
            flash("No teacher is assigned to this learner.", "error")
            return redirect(url_for("student_dashboard"))

        teacher_username = row[0]
        chat_session_id = request.form.get("chat_session_id", "").strip() or session.get("chat_session_id", "")
        if not chat_session_id:
            chat_session_id = datetime.now().strftime("%Y%m%d%H%M%S")
            session["chat_session_id"] = chat_session_id

        cursor.execute(
            """
            SELECT id
            FROM communication_threads
            WHERE student_username = ? AND topic = ? AND status = 'open' AND chat_session_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (username, topic, chat_session_id),
        )
        existing = cursor.fetchone()
        if existing:
            add_communication_message(cursor, existing[0], username, "student", message)
        else:
            thread_id = create_communication_thread(
                cursor,
                username,
                topic,
                subject_line="Chat" if topic == "chat" else topic.replace("_", " ").title(),
                initial_message=message,
                chat_session_id=chat_session_id,
            )
            cursor.execute(
                """
                UPDATE communication_threads
                SET teacher_username = ?
                WHERE id = ?
                """,
                (teacher_username, thread_id),
            )
        conn.commit()
        conn.close()
        flash("Message sent.", "success")
        return redirect(url_for("student_dashboard"))

    @app.route("/communications")
    def communications():
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))
        role = get_user_role(username)
        if role not in ["teacher", "admin"]:
            return "Access denied", 403

        selected_group = (request.args.get("group") or "").strip()
        selected_topic = (request.args.get("topic") or "").strip()
        selected_date = (request.args.get("date") or "").strip()
        groups = get_groups(username)

        conn = get_db()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        query = """
            SELECT t.*,
                   u.full_name AS student_name,
                   u.group_name
            FROM communication_threads t
            JOIN users u ON u.username = t.student_username
            WHERE 1=1
        """
        params = []
        if role == "teacher":
            query += " AND (t.teacher_username = ? OR u.teacher_username = ?)"
            params.extend([username, username])
        if selected_group:
            query += " AND u.group_name = ?"
            params.append(selected_group)
        if selected_topic:
            query += " AND t.topic = ?"
            params.append(selected_topic)
        if selected_date:
            query += " AND (t.attendance_date = ? OR substr(COALESCE(t.updated_at, t.created_at), 1, 10) = ?)"
            params.extend([selected_date, selected_date])
        query += " ORDER BY COALESCE(t.updated_at, t.created_at) DESC, t.id DESC"
        cursor.execute(query, params)

        threads = []
        for row in cursor.fetchall():
            thread = dict(row)
            cursor.execute(
                """
                SELECT *
                FROM communication_messages
                WHERE thread_id = ?
                ORDER BY COALESCE(created_at, '') ASC, id ASC
                """,
                (thread["id"],),
            )
            thread["messages"] = [dict(message_row) for message_row in cursor.fetchall()]
            threads.append(thread)

        conn.close()
        return render_template(
            "communications.html",
            threads=threads,
            groups=groups,
            selected_group=selected_group,
            selected_topic=selected_topic,
            selected_date=selected_date,
        )

    @app.route("/communications/reply", methods=["POST"])
    def communications_reply():
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))
        role = get_user_role(username)
        if role not in ["teacher", "admin"]:
            return "Access denied", 403

        thread_id = request.form.get("thread_id", type=int)
        message = (request.form.get("message") or "").strip()
        if not thread_id or not message:
            flash("Reply could not be sent.", "error")
            return redirect(url_for("communications"))

        conn = get_db()
        cursor = conn.cursor()
        add_communication_message(cursor, thread_id, username, role, message)
        conn.commit()
        conn.close()
        flash("Reply sent.", "success")
        return redirect(
            url_for(
                "communications",
                group=request.form.get("group", ""),
                topic=request.form.get("topic", ""),
                date=request.form.get("date", ""),
            )
        )

    @app.route("/communications/mark_read", methods=["POST"])
    def communications_mark_read():
        username = session.get("username")
        if not username:
            return jsonify({"ok": False}), 401
        role = get_user_role(username)
        if role not in ["teacher", "admin"]:
            return jsonify({"ok": False}), 403

        thread_id = request.form.get("thread_id", type=int)
        if not thread_id:
            return jsonify({"ok": False}), 400

        now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE communication_threads
            SET teacher_read_at = ?
            WHERE id = ?
            """,
            (now_text, thread_id),
        )
        conn.commit()
        conn.close()
        return jsonify({"ok": True})

    @app.route("/communications/attendance_action", methods=["POST"])
    def communications_attendance_action():
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))
        role = get_user_role(username)
        if role not in ["teacher", "admin"]:
            return "Access denied", 403

        thread_id = request.form.get("thread_id", type=int)
        student_username = (request.form.get("student_username") or "").strip()
        attendance_date = (request.form.get("attendance_date") or "").strip()
        action = (request.form.get("action") or "").strip()
        status_map = {
            "mark_present": "present",
            "mark_late": "late",
            "mark_absent": "absent",
        }
        status = status_map.get(action)
        if not (thread_id and student_username and attendance_date and status):
            flash("Attendance action could not be completed.", "error")
            return redirect(url_for("communications"))

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO attendance_override (username, date, status)
            VALUES (?, ?, ?)
            ON CONFLICT(username, date) DO UPDATE SET status = excluded.status
            """,
            (student_username, attendance_date, status),
        )
        add_communication_message(
            cursor,
            thread_id,
            username,
            role,
            f"Attendance updated to {status.title()} for {attendance_date}.",
        )
        conn.commit()
        conn.close()
        flash(f"Attendance marked {status}.", "success")
        return redirect(
            url_for(
                "communications",
                group=request.form.get("group", ""),
                topic=request.form.get("topic", ""),
                date=request.form.get("date", ""),
            )
        )

    @app.route("/api/message_status")
    def api_message_status():
        username = session.get("username")
        if not username:
            return jsonify({"ok": False}), 401
        role = get_user_role(username)
        if role == "student":
            if request.args.get("mark_read") == "1":
                mark_student_threads_read(username)
            return jsonify(
                {
                    "ok": True,
                    "unread": get_student_unread_message_count(username),
                    "auto_open": student_has_fresh_teacher_reply(username),
                }
            )
        if role in ["teacher", "admin"]:
            return jsonify({"ok": True, "unread": get_teacher_unread_message_count(username)})
        return jsonify({"ok": False}), 403
