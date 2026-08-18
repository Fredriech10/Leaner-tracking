import json
import os
import uuid
from datetime import datetime

from flask import jsonify, redirect, render_template, request, send_file, session, url_for

from app.database import get_db, get_user_role
from werkzeug.utils import secure_filename

RECORDINGS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "uploads", "screen_recordings")
POSTERS_DIR = os.path.join(RECORDINGS_DIR, "posters")


def _utc_now():
    return datetime.now().isoformat()


def _get_active_teacher_session(cursor, teacher_username):
    cursor.execute(
        """
        SELECT id, teacher_username, COALESCE(title, ''), status, created_at, ended_at
        FROM screen_share_sessions
        WHERE teacher_username = ? AND status = 'active'
        ORDER BY id DESC
        LIMIT 1
        """,
        (teacher_username,),
    )
    return cursor.fetchone()


def _session_dict(row):
    if not row:
        return None
    return {
        "id": row[0],
        "teacher_username": row[1],
        "title": row[2],
        "status": row[3],
        "created_at": row[4],
        "ended_at": row[5],
    }


def _teacher_students(cursor, teacher_username):
    cursor.execute(
        """
        SELECT username, COALESCE(full_name, username), COALESCE(group_name, '')
        FROM users
        WHERE role = 'student' AND teacher_username = ?
        ORDER BY group_name, full_name, username
        """,
        (teacher_username,),
    )
    return cursor.fetchall()


def _get_teacher_recordings(cursor, teacher_username):
    cursor.execute(
        """
        SELECT id, session_id, title, file_name, file_path, poster_file_name, poster_file_path, COALESCE(mime_type, 'video/webm'),
               COALESCE(file_size, 0), created_at
        FROM screen_share_recordings
        WHERE teacher_username = ?
        ORDER BY created_at DESC, id DESC
        """,
        (teacher_username,),
    )
    return [
        {
            "id": row[0],
            "session_id": row[1],
            "title": row[2],
            "file_name": row[3],
            "file_path": row[4],
            "poster_file_name": row[5],
            "poster_file_path": row[6],
            "mime_type": row[7],
            "file_size": row[8],
            "created_at": row[9],
            "watch_href": f"/screen_share/recordings/{row[0]}/watch",
            "poster_href": f"/screen_share/recordings/{row[0]}/poster" if row[6] else "",
        }
        for row in cursor.fetchall()
    ]


def _get_recording_by_id(cursor, recording_id):
    cursor.execute(
        """
        SELECT id, session_id, teacher_username, title, file_name, file_path, poster_file_name, poster_file_path,
               COALESCE(mime_type, 'video/webm'), COALESCE(file_size, 0), created_at
        FROM screen_share_recordings
        WHERE id = ?
        """,
        (recording_id,),
    )
    row = cursor.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "session_id": row[1],
        "teacher_username": row[2],
        "title": row[3],
        "file_name": row[4],
        "file_path": row[5],
        "poster_file_name": row[6],
        "poster_file_path": row[7],
        "mime_type": row[8],
        "file_size": row[9],
        "created_at": row[10],
        "watch_href": f"/screen_share/recordings/{row[0]}/watch",
        "poster_href": f"/screen_share/recordings/{row[0]}/poster" if row[7] else "",
        "stream_href": f"/screen_share/recordings/{row[0]}/file",
    }


def _recording_access_allowed(cursor, recording, username, role):
    if role in ["teacher", "admin"] and recording["teacher_username"] == username:
        return True
    if role == "student":
        cursor.execute("SELECT 1 FROM users WHERE username = ? AND teacher_username = ?", (username, recording["teacher_username"]))
        return cursor.fetchone() is not None
    return False


def _get_session_with_access(cursor, session_id, username, role):
    cursor.execute(
        """
        SELECT id, teacher_username, COALESCE(title, ''), status, created_at, ended_at
        FROM screen_share_sessions
        WHERE id = ?
        """,
        (session_id,),
    )
    row = cursor.fetchone()
    if not row:
        return None
    if role in ["teacher", "admin"] and row[1] == username:
        return row
    if role == "student":
        cursor.execute(
            """
            SELECT 1
            FROM users
            WHERE username = ? AND teacher_username = ?
            """,
            (username, row[1]),
        )
        if cursor.fetchone():
            return row
    return None


def register_screen_share_routes(app):
    @app.route("/screen_share")
    def screen_share_teacher():
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))
        if get_user_role(username) not in ["teacher", "admin"]:
            return "Access denied", 403

        conn = get_db()
        cursor = conn.cursor()
        active_session = _session_dict(_get_active_teacher_session(cursor, username))
        learners = _teacher_students(cursor, username)
        recordings = _get_teacher_recordings(cursor, username)
        conn.close()
        return render_template(
            "screen_share_teacher.html",
            active_session=active_session,
            learners=learners,
            recordings=recordings,
        )

    @app.route("/student/screen_share")
    def screen_share_student():
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))
        if get_user_role(username) != "student":
            return "Access denied", 403

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
        teacher_username = row[0] if row else None
        active_session = None
        recordings = []
        if teacher_username:
            active_session = _session_dict(_get_active_teacher_session(cursor, teacher_username))
            if active_session:
                cursor.execute(
                    """
                    SELECT status
                    FROM screen_share_viewers
                    WHERE session_id = ? AND viewer_username = ?
                    """,
                    (active_session["id"], username),
                )
                status_row = cursor.fetchone()
                active_session["viewer_status"] = status_row[0] if status_row else "pending"
            recordings = _get_teacher_recordings(cursor, teacher_username)
        conn.close()
        return render_template("screen_share_student.html", active_session=active_session, recordings=recordings)

    @app.route("/screen_share/start", methods=["POST"])
    def screen_share_start():
        username = session.get("username")
        if not username:
            return jsonify({"ok": False, "error": "login_required"}), 401
        if get_user_role(username) not in ["teacher", "admin"]:
            return jsonify({"ok": False, "error": "forbidden"}), 403

        title = (request.form.get("title") or "Live lesson screen share").strip()
        conn = get_db()
        cursor = conn.cursor()
        current = _get_active_teacher_session(cursor, username)
        if current:
            session_row = current
        else:
            cursor.execute(
                """
                INSERT INTO screen_share_sessions (teacher_username, title, status, created_at)
                VALUES (?, ?, 'active', ?)
                """,
                (username, title, _utc_now()),
            )
            conn.commit()
            cursor.execute(
                """
                SELECT id, teacher_username, COALESCE(title, ''), status, created_at, ended_at
                FROM screen_share_sessions
                WHERE id = ?
                """,
                (cursor.lastrowid,),
            )
            session_row = cursor.fetchone()
        conn.close()
        return jsonify({"ok": True, "session": _session_dict(session_row)})

    @app.route("/screen_share/stop", methods=["POST"])
    def screen_share_stop():
        username = session.get("username")
        if not username:
            return jsonify({"ok": False, "error": "login_required"}), 401
        if get_user_role(username) not in ["teacher", "admin"]:
            return jsonify({"ok": False, "error": "forbidden"}), 403

        conn = get_db()
        cursor = conn.cursor()
        active = _get_active_teacher_session(cursor, username)
        if active:
            cursor.execute(
                """
                UPDATE screen_share_sessions
                SET status = 'ended', ended_at = ?
                WHERE id = ?
                """,
                (_utc_now(), active[0]),
            )
            cursor.execute(
                """
                UPDATE screen_share_viewers
                SET status = 'ended', left_at = ?
                WHERE session_id = ? AND status != 'ended'
                """,
                (_utc_now(), active[0]),
            )
            conn.commit()
        conn.close()
        return jsonify({"ok": True})

    @app.route("/screen_share/<int:session_id>/join", methods=["POST"])
    def screen_share_join(session_id):
        username = session.get("username")
        if not username:
            return jsonify({"ok": False, "error": "login_required"}), 401
        if get_user_role(username) != "student":
            return jsonify({"ok": False, "error": "forbidden"}), 403

        conn = get_db()
        cursor = conn.cursor()
        session_row = _get_session_with_access(cursor, session_id, username, "student")
        if not session_row or session_row[3] != "active":
            conn.close()
            return jsonify({"ok": False, "error": "session_unavailable"}), 404

        now_text = _utc_now()
        cursor.execute(
            """
            INSERT INTO screen_share_viewers (session_id, viewer_username, status, joined_at, left_at)
            VALUES (?, ?, 'accepted', ?, NULL)
            ON CONFLICT(session_id, viewer_username)
            DO UPDATE SET status = 'accepted', joined_at = excluded.joined_at, left_at = NULL
            """,
            (session_id, username, now_text),
        )
        conn.commit()
        conn.close()
        return jsonify({"ok": True})

    @app.route("/screen_share/<int:session_id>/status")
    def screen_share_status(session_id):
        username = session.get("username")
        if not username:
            return jsonify({"ok": False, "error": "login_required"}), 401
        role = get_user_role(username)

        conn = get_db()
        cursor = conn.cursor()
        session_row = _get_session_with_access(cursor, session_id, username, role)
        if not session_row:
            conn.close()
            return jsonify({"ok": False, "error": "session_not_found"}), 404

        payload = {"ok": True, "session": _session_dict(session_row)}
        if role in ["teacher", "admin"] and session_row[1] == username:
            cursor.execute(
                """
                SELECT viewer_username, status, COALESCE(joined_at, '')
                FROM screen_share_viewers
                WHERE session_id = ?
                ORDER BY CASE WHEN status = 'accepted' THEN 0 WHEN status = 'pending' THEN 1 ELSE 2 END,
                         COALESCE(joined_at, ''),
                         viewer_username
                """,
                (session_id,),
            )
            payload["viewers"] = [
                {"viewer_username": row[0], "status": row[1], "joined_at": row[2]}
                for row in cursor.fetchall()
            ]
        elif role == "student":
            cursor.execute(
                """
                SELECT status
                FROM screen_share_viewers
                WHERE session_id = ? AND viewer_username = ?
                """,
                (session_id, username),
            )
            viewer_row = cursor.fetchone()
            payload["viewer_status"] = viewer_row[0] if viewer_row else "pending"
        conn.close()
        return jsonify(payload)

    @app.route("/screen_share/<int:session_id>/signal", methods=["POST"])
    def screen_share_signal(session_id):
        username = session.get("username")
        if not username:
            return jsonify({"ok": False, "error": "login_required"}), 401
        role = get_user_role(username)

        conn = get_db()
        cursor = conn.cursor()
        session_row = _get_session_with_access(cursor, session_id, username, role)
        if not session_row or session_row[3] != "active":
            conn.close()
            return jsonify({"ok": False, "error": "session_unavailable"}), 404

        recipient_username = (request.form.get("recipient_username") or "").strip().upper()
        signal_type = (request.form.get("signal_type") or "").strip()
        payload = request.form.get("payload") or ""
        if not recipient_username or not signal_type or not payload:
            conn.close()
            return jsonify({"ok": False, "error": "invalid_payload"}), 400

        cursor.execute(
            """
            INSERT INTO screen_share_signals (session_id, sender_username, recipient_username, signal_type, payload, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session_id, username, recipient_username, signal_type, payload, _utc_now()),
        )
        conn.commit()
        conn.close()
        return jsonify({"ok": True})

    @app.route("/screen_share/<int:session_id>/events")
    def screen_share_events(session_id):
        username = session.get("username")
        if not username:
            return jsonify({"ok": False, "error": "login_required"}), 401
        role = get_user_role(username)

        conn = get_db()
        cursor = conn.cursor()
        session_row = _get_session_with_access(cursor, session_id, username, role)
        if not session_row:
            conn.close()
            return jsonify({"ok": False, "error": "session_not_found"}), 404

        cursor.execute(
            """
            SELECT id, sender_username, signal_type, payload, created_at
            FROM screen_share_signals
            WHERE session_id = ?
              AND recipient_username = ?
              AND delivered_at IS NULL
            ORDER BY id ASC
            """,
            (session_id, username),
        )
        rows = cursor.fetchall()
        if rows:
            cursor.execute(
                f"""
                UPDATE screen_share_signals
                SET delivered_at = ?
                WHERE id IN ({",".join("?" for _ in rows)})
                """,
                [_utc_now(), *[row[0] for row in rows]],
            )
            conn.commit()
        conn.close()
        return jsonify(
            {
                "ok": True,
                "events": [
                    {
                        "id": row[0],
                        "sender_username": row[1],
                        "signal_type": row[2],
                        "payload": json.loads(row[3]),
                        "created_at": row[4],
                    }
                    for row in rows
                ],
            }
        )

    @app.route("/screen_share/upload_recording", methods=["POST"])
    def screen_share_upload_recording():
        username = session.get("username")
        if not username:
            return jsonify({"ok": False, "error": "login_required"}), 401
        if get_user_role(username) not in ["teacher", "admin"]:
            return jsonify({"ok": False, "error": "forbidden"}), 403

        recording_file = request.files.get("recording")
        if not recording_file or not recording_file.filename:
            return jsonify({"ok": False, "error": "missing_file"}), 400

        os.makedirs(RECORDINGS_DIR, exist_ok=True)
        os.makedirs(POSTERS_DIR, exist_ok=True)
        title = (request.form.get("title") or "Screen recording").strip() or "Screen recording"
        session_id = request.form.get("session_id", type=int)
        original_name = secure_filename(recording_file.filename) or "recording.webm"
        extension = os.path.splitext(original_name)[1] or ".webm"
        stored_name = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}{extension}"
        file_path = os.path.join(RECORDINGS_DIR, stored_name)
        recording_file.save(file_path)
        file_size = os.path.getsize(file_path)
        mime_type = (recording_file.mimetype or "video/webm").strip()
        poster_file = request.files.get("poster")
        poster_name = None
        poster_path = None
        if poster_file and poster_file.filename:
            poster_extension = os.path.splitext(secure_filename(poster_file.filename) or "poster.png")[1] or ".png"
            poster_name = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}{poster_extension}"
            poster_path = os.path.join(POSTERS_DIR, poster_name)
            poster_file.save(poster_path)

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO screen_share_recordings (
                session_id, teacher_username, title, file_name, file_path, poster_file_name, poster_file_path, mime_type, file_size, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, username, title, stored_name, file_path, poster_name, poster_path, mime_type, file_size, _utc_now()),
        )
        recording_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return jsonify({"ok": True, "recording_id": recording_id, "file_name": stored_name, "watch_href": f"/screen_share/recordings/{recording_id}/watch"})

    @app.route("/screen_share/recordings")
    def screen_share_recordings():
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))
        role = get_user_role(username)

        conn = get_db()
        cursor = conn.cursor()
        if role in ["teacher", "admin"]:
            recordings = _get_teacher_recordings(cursor, username)
        elif role == "student":
            cursor.execute("SELECT teacher_username FROM users WHERE username = ?", (username,))
            row = cursor.fetchone()
            recordings = _get_teacher_recordings(cursor, row[0]) if row and row[0] else []
        else:
            conn.close()
            return "Access denied", 403
        conn.close()
        return render_template("screen_share_library.html", recordings=recordings, role=role)

    @app.route("/screen_share/recordings/<int:recording_id>/watch")
    def screen_share_recording_watch(recording_id):
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))
        role = get_user_role(username)

        conn = get_db()
        cursor = conn.cursor()
        recording = _get_recording_by_id(cursor, recording_id)
        if not recording:
            conn.close()
            return "Not found", 404
        allowed = _recording_access_allowed(cursor, recording, username, role)
        conn.close()
        if not allowed:
            return "Access denied", 403
        return render_template("screen_share_watch.html", recording=recording, role=role)

    @app.route("/screen_share/recordings/<int:recording_id>/file")
    def screen_share_recording_file(recording_id):
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))
        role = get_user_role(username)

        conn = get_db()
        cursor = conn.cursor()
        recording = _get_recording_by_id(cursor, recording_id)
        if not recording:
            conn.close()
            return "Not found", 404
        allowed = _recording_access_allowed(cursor, recording, username, role)
        conn.close()

        if not allowed or not os.path.exists(recording["file_path"]):
            return "Access denied", 403
        return send_file(recording["file_path"], mimetype=recording["mime_type"], as_attachment=False, download_name=recording["file_name"])

    @app.route("/screen_share/recordings/<int:recording_id>/poster")
    def screen_share_recording_poster(recording_id):
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))
        role = get_user_role(username)
        conn = get_db()
        cursor = conn.cursor()
        recording = _get_recording_by_id(cursor, recording_id)
        if not recording:
            conn.close()
            return "Not found", 404
        allowed = _recording_access_allowed(cursor, recording, username, role)
        conn.close()
        if not allowed or not recording["poster_file_path"] or not os.path.exists(recording["poster_file_path"]):
            return "Not found", 404
        return send_file(recording["poster_file_path"], mimetype="image/png", as_attachment=False, download_name=recording["poster_file_name"] or "poster.png")

    @app.route("/screen_share/recordings/<int:recording_id>/rename", methods=["POST"])
    def screen_share_recording_rename(recording_id):
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))
        role = get_user_role(username)
        if role not in ["teacher", "admin"]:
            return "Access denied", 403
        new_title = (request.form.get("title") or "").strip()
        if not new_title:
            return redirect(url_for("screen_share_recordings"))
        conn = get_db()
        cursor = conn.cursor()
        recording = _get_recording_by_id(cursor, recording_id)
        if not recording or recording["teacher_username"] != username:
            conn.close()
            return "Access denied", 403
        cursor.execute("UPDATE screen_share_recordings SET title = ? WHERE id = ?", (new_title, recording_id))
        conn.commit()
        conn.close()
        return redirect(request.form.get("next") or url_for("screen_share_recordings"))

    @app.route("/screen_share/recordings/<int:recording_id>/delete", methods=["POST"])
    def screen_share_recording_delete(recording_id):
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))
        role = get_user_role(username)
        if role not in ["teacher", "admin"]:
            return "Access denied", 403
        conn = get_db()
        cursor = conn.cursor()
        recording = _get_recording_by_id(cursor, recording_id)
        if not recording or recording["teacher_username"] != username:
            conn.close()
            return "Access denied", 403
        cursor.execute("DELETE FROM screen_share_recordings WHERE id = ?", (recording_id,))
        conn.commit()
        conn.close()
        for path in (recording["file_path"], recording["poster_file_path"]):
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except PermissionError:
                    pass
        return redirect(request.form.get("next") or url_for("screen_share_recordings"))
