from datetime import datetime, timedelta

import pandas as pd
from flask import redirect, render_template, request, send_file, session, url_for

from app.database import get_db, get_groups, get_user_role, log_activity
from app.helper_attendance import (
    add_learner_note_entry,
    build_attendance_group_summary,
    get_attendance_data,
    get_last_21_days,
    get_term_dates,
)


def register_attendance_routes(app):
    @app.route("/term_dates", methods=["GET", "POST"])
    def term_dates():
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))
        if get_user_role(username) not in ["teacher", "admin"]:
            return "Access denied", 403

        if request.method == "POST":
            conn = get_db()
            cursor = conn.cursor()
            for term_num in range(1, 5):
                start = request.form.get(f"term{term_num}_start", "").strip()
                end = request.form.get(f"term{term_num}_end", "").strip()
                if start and end:
                    cursor.execute(
                        """
                        INSERT INTO term_dates (term, start_date, end_date)
                        VALUES (?, ?, ?)
                        ON CONFLICT(term) DO UPDATE SET start_date = excluded.start_date, end_date = excluded.end_date
                        """,
                        (term_num, start, end),
                    )
                else:
                    cursor.execute("DELETE FROM term_dates WHERE term = ?", (term_num,))
            conn.commit()
            conn.close()
            log_activity(username, "updated term dates")
            return redirect(url_for("attendance"))

        return redirect(url_for("attendance"))

    @app.route("/attendance")
    def attendance():
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))

        role = get_user_role(username)
        if role not in ["teacher", "admin"]:
            return "Access denied", 403

        selected_group = request.args.get("group")
        edit_mode = request.args.get("edit") == "1"
        range_param = request.args.get("range", "week")

        today = datetime.now().strftime("%Y-%m-%d")
        if range_param == "week":
            start_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
            end_date = today
        elif range_param == "2weeks":
            start_date = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")
            end_date = today
        elif range_param == "month":
            start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
            end_date = today
        else:
            start_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
            end_date = today

        groups = get_groups(username) if role == "teacher" else get_groups()

        if role == "teacher" and selected_group and selected_group not in groups:
            selected_group = None

        days = []
        data = []
        daily_present_counts = {}
        daily_absent_counts = {}
        attendance_summary = []

        if selected_group:
            days, data = get_attendance_data(
                selected_group,
                start_date,
                end_date,
                teacher_username=username if role == "teacher" else None,
            )
            daily_present_counts = {day: sum(1 for row in data if row["days"].get(day)) for day in days}
            daily_absent_counts = {day: len(data) - daily_present_counts[day] for day in days}
        else:
            conn = get_db()
            cursor = conn.cursor()
            attendance_summary = build_attendance_group_summary(
                cursor,
                groups,
                teacher_username=username if role == "teacher" else None,
                days=get_last_21_days(),
            )
            conn.close()

        conn = get_db()
        cursor = conn.cursor()
        if selected_group:
            cursor.execute(
                """
                SELECT date, group_name, reason, created_by, created_at
                FROM excluded_dates
                WHERE group_name IS NULL OR group_name = ?
                ORDER BY date DESC
                """,
                (selected_group,),
            )
        else:
            cursor.execute(
                """
                SELECT date, group_name, reason, created_by, created_at
                FROM excluded_dates
                ORDER BY date DESC
                """
            )
        excluded_dates = cursor.fetchall()
        conn.close()

        terms = get_term_dates()

        return render_template(
            "attendance.html",
            groups=groups,
            selected_group=selected_group,
            days=days,
            data=data,
            daily_present_counts=daily_present_counts,
            daily_absent_counts=daily_absent_counts,
            edit_mode=edit_mode,
            today=datetime.now().strftime("%Y-%m-%d"),
            excluded_dates=excluded_dates,
            terms=terms,
            attendance_summary=attendance_summary,
        )

    @app.route("/export/attendance")
    def export_attendance():
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))

        if get_user_role(username) not in ["teacher", "admin"]:
            return "Access denied", 403

        conn = get_db()
        group = request.args.get("group")
        role = get_user_role(username)
        days, data = get_attendance_data(group, teacher_username=username if role == "teacher" else None)

        rows = []
        for row in data:
            base = {
                "Username": row["username"],
                "Name": row["name"],
                "Group": row["group"],
                "Attendance %": row["attendance_pct"],
            }
            for day in days:
                val = row["days"].get(day)
                base[day] = val["time"] if val else "A"
            rows.append(base)

        df = pd.DataFrame(rows)
        file_path = "attendance_export.xlsx"
        df.to_excel(file_path, index=False)
        log_activity(username, "exported attendance")
        conn.close()
        return send_file(file_path, as_attachment=True)

    @app.route("/export_attendance_form")
    def export_attendance_form():
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))
        role = get_user_role(username)
        if role not in ["teacher", "admin"]:
            return "Access denied", 403
        all_groups = get_groups(username) if role == "teacher" else get_groups()
        return render_template("export_attendance.html", all_groups=all_groups)

    @app.route("/export_attendance_multi", methods=["POST"])
    def export_attendance_multi():
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))

        if get_user_role(username) not in ["teacher", "admin"]:
            return "Access denied", 403

        selected_groups = request.form.getlist("groups")
        start_date = request.form.get("start_date")
        end_date = request.form.get("end_date")

        if not selected_groups:
            return "No groups selected", 400

        if not start_date or not end_date:
            return "Date range is required", 400

        conn = get_db()
        file_path = "multi_group_attendance_export.xlsx"
        role = get_user_role(username)
        with pd.ExcelWriter(file_path, engine="openpyxl") as writer:
            for group in selected_groups:
                days, data = get_attendance_data(
                    group,
                    start_date,
                    end_date,
                    teacher_username=username if role == "teacher" else None,
                )
                filtered_days = [day for day in days if start_date <= day <= end_date]
                rows = []
                for row in data:
                    base = {
                        "Username": row["username"],
                        "Name": row["name"],
                        "Group": row["group"],
                        "Attendance %": row["attendance_pct"],
                    }
                    for day in filtered_days:
                        val = row["days"].get(day)
                        base[day] = val["time"] if val else "A"
                    rows.append(base)
                df = pd.DataFrame(rows)
                sheet_name = group.replace("/", "_").replace("\\", "_")[:31]
                df.to_excel(writer, sheet_name=sheet_name, index=False)

        log_activity(username, "exported attendance by group")
        conn.close()
        response = send_file(file_path, as_attachment=True)
        response.headers["HX-Redirect"] = url_for("teacher_dashboard")
        return response

    @app.route("/reset_attendance", methods=["POST"])
    def reset_attendance():
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))

        if get_user_role(username) not in ["teacher", "admin"]:
            return "Access denied", 403

        group = request.form.get("group")
        date = request.form.get("date")

        if not group or not date:
            return "Missing data", 400

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT username FROM users WHERE group_name = ? AND role = 'student'
            """,
            (group,),
        )
        users = [u[0] for u in cursor.fetchall()]

        if users:
            placeholders = ",".join(["?"] * len(users))
            cursor.execute(
                f"""
                DELETE FROM login_history
                WHERE username IN ({placeholders}) AND date = ?
                """,
                (*users, date),
            )
            cursor.execute(
                f"""
                DELETE FROM attendance_override
                WHERE username IN ({placeholders}) AND date = ?
                """,
                (*users, date),
            )
            for user in users:
                add_learner_note_entry(cursor, user, f"Attendance reset for {date} in group {group}.", username)

        conn.commit()
        conn.close()
        return redirect(url_for("attendance", group=group))

    @app.route("/mark_all_present", methods=["POST"])
    def mark_all_present():
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))

        if get_user_role(username) not in ["teacher", "admin"]:
            return "Access denied", 403

        group = request.form.get("group")
        date = request.form.get("date")

        if not group or not date:
            return "Missing data", 400

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT username FROM users WHERE group_name = ? AND role = 'student'
            """,
            (group,),
        )
        users = [u[0] for u in cursor.fetchall()]

        if users:
            for user in users:
                cursor.execute("SELECT status FROM attendance_override WHERE username = ? AND date = ?", (user, date))
                previous = cursor.fetchone()
                cursor.execute(
                    """
                    INSERT INTO attendance_override (username, date, status)
                    VALUES (?, ?, ?)
                    ON CONFLICT(username, date)
                    DO UPDATE SET status = excluded.status
                    """,
                    (user, date, "present"),
                )
                if previous is None or previous[0] != "present":
                    add_learner_note_entry(cursor, user, f"Marked present for {date} in group {group}.", username)

        conn.commit()
        log_activity(username, f"marked all in {group} present on {date}")
        conn.close()
        return redirect(url_for("attendance", group=group))

    @app.route("/save_attendance", methods=["POST"])
    def save_attendance():
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))

        if get_user_role(username) not in ["teacher", "admin"]:
            return "Access denied", 403

        group = request.form.get("group")

        conn = get_db()
        cursor = conn.cursor()

        for key, value in request.form.items():
            if not key.startswith("att_"):
                continue
            try:
                _, data = key.split("att_")
                user, day = data.split("|")
            except ValueError:
                continue

            value = value.strip().lower()
            if value == "":
                continue

            if value == "x":
                status = "absent"
            else:
                status = "present"

            cursor.execute("SELECT status FROM attendance_override WHERE username = ? AND date = ?", (user, day))
            previous = cursor.fetchone()
            cursor.execute(
                """
                INSERT INTO attendance_override (username, date, status)
                VALUES (?, ?, ?)
                ON CONFLICT(username, date)
                DO UPDATE SET status = excluded.status
                """,
                (user, day, status),
            )
            if previous is None or previous[0] != status:
                add_learner_note_entry(cursor, user, f"Attendance manually set to {status.upper()} for {day}.", username)

        conn.commit()
        log_activity(username, f"saved attendance for {group}")
        conn.close()
        return redirect(url_for("attendance", group=group))

    @app.route("/exclude_date", methods=["POST"])
    def exclude_date():
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))

        if get_user_role(username) not in ["teacher", "admin"]:
            return "Access denied", 403

        date = request.form.get("date")
        group = request.form.get("group")
        reason = request.form.get("reason", "")

        if not date:
            return "Missing date", 400

        if group == "":
            group = None

        conn = get_db()
        cursor = conn.cursor()

        timestamp = datetime.now().isoformat()
        if group is None:
            cursor.execute(
                """
                SELECT rowid
                FROM excluded_dates
                WHERE date = ? AND group_name IS NULL
                ORDER BY rowid
                LIMIT 1
                """,
                (date,),
            )
            existing = cursor.fetchone()
            if existing:
                cursor.execute(
                    """
                    UPDATE excluded_dates
                    SET reason = ?, created_by = ?, created_at = ?
                    WHERE rowid = ?
                    """,
                    (reason, username, timestamp, existing[0]),
                )
                cursor.execute(
                    """
                    DELETE FROM excluded_dates
                    WHERE date = ? AND group_name IS NULL AND rowid != ?
                    """,
                    (date, existing[0]),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO excluded_dates (date, group_name, reason, created_by, created_at)
                    VALUES (?, NULL, ?, ?, ?)
                    """,
                    (date, reason, username, timestamp),
                )
        else:
            cursor.execute(
                """
                INSERT INTO excluded_dates (date, group_name, reason, created_by, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(date, group_name)
                DO UPDATE SET reason = excluded.reason, created_by = excluded.created_by, created_at = excluded.created_at
                """,
                (date, group, reason, username, timestamp),
            )

        conn.commit()
        log_activity(username, f"excluded date {date} for group {group or 'all groups'} ({reason})")
        conn.close()
        return redirect(url_for("attendance", group=request.form.get("selected_group")))

    @app.route("/include_date", methods=["POST"])
    def include_date():
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))

        if get_user_role(username) not in ["teacher", "admin"]:
            return "Access denied", 403

        date = request.form.get("date")
        group = request.form.get("group")

        if not date:
            return "Missing date", 400

        if group == "":
            group = None

        conn = get_db()
        cursor = conn.cursor()
        if group:
            cursor.execute("DELETE FROM excluded_dates WHERE date = ? AND group_name = ?", (date, group))
        else:
            cursor.execute("DELETE FROM excluded_dates WHERE date = ? AND group_name IS NULL", (date,))

        conn.commit()
        log_activity(username, f"included date {date} for group {group or 'all groups'}")
        conn.close()
        return redirect(url_for("attendance", group=request.form.get("selected_group")))

    @app.route("/mark_all_absent", methods=["POST"])
    def mark_all_absent():
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))

        if get_user_role(username) not in ["teacher", "admin"]:
            return "Access denied", 403

        group = request.form.get("group")
        date = request.form.get("date")

        if not group or not date:
            return "Missing data", 400

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT username FROM users WHERE group_name = ? AND role = 'student'
            """,
            (group,),
        )
        users = [u[0] for u in cursor.fetchall()]

        if users:
            for user in users:
                cursor.execute("SELECT status FROM attendance_override WHERE username = ? AND date = ?", (user, date))
                previous = cursor.fetchone()
                cursor.execute(
                    """
                    INSERT INTO attendance_override (username, date, status)
                    VALUES (?, ?, ?)
                    ON CONFLICT(username, date)
                    DO UPDATE SET status = excluded.status
                    """,
                    (user, date, "absent"),
                )
                if previous is None or previous[0] != "absent":
                    add_learner_note_entry(cursor, user, f"Marked absent for {date} in group {group}.", username)

        conn.commit()
        log_activity(username, f"marked all in {group} absent on {date}")
        conn.close()
        return redirect(url_for("attendance", group=group))

    @app.route("/api/excluded_dates", methods=["GET"])
    def api_excluded_dates():
        username = session.get("username")
        if not username:
            return {"error": "Unauthorized"}, 401

        role = get_user_role(username)
        if role not in ["teacher", "admin"]:
            return {"error": "Access denied"}, 403

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT date, group_name, reason, created_by, created_at
            FROM excluded_dates
            ORDER BY date DESC
            """
        )
        excluded_dates = [
            {
                "date": row[0],
                "group_name": row[1],
                "reason": row[2],
                "created_by": row[3],
                "created_at": row[4],
            }
            for row in cursor.fetchall()
        ]
        conn.close()
        return {"excluded_dates": excluded_dates}

    @app.route("/api/attendance_data", methods=["GET"])
    def api_attendance_data():
        username = session.get("username")
        if not username:
            return {"error": "Unauthorized"}, 401

        role = get_user_role(username)
        if role not in ["teacher", "admin"]:
            return {"error": "Access denied"}, 403

        group = request.args.get("group")
        start_date = request.args.get("start_date")
        end_date = request.args.get("end_date")

        if not group:
            return {"error": "Group required"}, 400

        days, data = get_attendance_data(group, start_date, end_date, teacher_username=username if role == "teacher" else None)
        return {"days": days, "data": data, "success": True}
