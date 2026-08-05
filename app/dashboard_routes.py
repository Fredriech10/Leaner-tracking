from collections import defaultdict
from datetime import datetime, timedelta

from flask import redirect, render_template, session, url_for

from app.database import get_db, get_groups, get_user_role
from app.helpers import (
    auto_exclude_empty_attendance_days,
    build_attendance_history,
    build_attendance_months,
    fetch_attendance_override_statuses,
    fetch_first_login_times,
    fetch_group_excluded_dates,
    fetch_group_late_thresholds,
    fetch_group_practical_averages,
    fetch_group_theory_averages,
    fetch_student_practical_averages,
    fetch_student_theory_averages,
    fetch_theory_module_weaknesses,
    get_active_term_range,
    get_current_year_attendance_days,
    get_last_21_days,
    get_student_message_threads,
    get_student_unread_message_count,
    get_teacher_selected_quick_actions,
    get_low_attendance_learners_filtered as get_low_attendance_learners,
    student_has_fresh_teacher_reply,
    summarize_attendance_history,
)
from app.runtime import TIMEOUT, active_users, lock, update_active_user


def register_dashboard_routes(app):
    @app.route("/student_dashboard")
    def student_dashboard():
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))

        update_active_user(username)
        role = get_user_role(username)

        if role in ["teacher", "admin"]:
            return redirect(url_for("teacher_dashboard"))

        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("SELECT full_name, group_name FROM users WHERE username = ?", (username,))
        user_row = cursor.fetchone()
        display_name = user_row[0] if user_row and user_row[0] else username
        user_group = user_row[1] if user_row else None

        cursor.execute(
            """
            SELECT subject, ROUND(AVG(best_score),1)
            FROM (SELECT subject, task, MAX(score) as best_score FROM results WHERE username = ? GROUP BY subject, task)
            GROUP BY subject
            """,
            (username,),
        )
        subject_avgs = cursor.fetchall()

        cursor.execute(
            """
            SELECT ROUND(AVG(best_score),1)
            FROM (SELECT subject, task, MAX(score) as best_score FROM results WHERE username = ? GROUP BY subject, task)
            """,
            (username,),
        )
        overall_row = cursor.fetchone()
        practical_avg = overall_row[0] if overall_row and overall_row[0] else 0

        cursor.execute(
            """
            SELECT ROUND(AVG(best_pct),1)
            FROM (SELECT test_id, MAX(percentage) as best_pct FROM theory_submissions WHERE username = ? GROUP BY test_id)
            """,
            (username,),
        )
        theory_avg_row = cursor.fetchone()
        theory_avg = theory_avg_row[0] if theory_avg_row and theory_avg_row[0] else None

        if practical_avg and theory_avg:
            overall_avg = round((practical_avg + theory_avg) / 2, 1)
        else:
            overall_avg = practical_avg or theory_avg or 0

        cursor.execute(
            """
            SELECT subject, task, MAX(score) as score, feedback, MAX(timestamp) as timestamp
            FROM results WHERE username = ? GROUP BY subject, task ORDER BY timestamp DESC LIMIT 5
            """,
            (username,),
        )
        recent_results = cursor.fetchall()

        cursor.execute(
            """
            SELECT tt.subject, tt.title, MAX(ts.percentage) as best_pct, MAX(ts.submitted_at) as latest
            FROM theory_submissions ts
            JOIN theory_tests tt ON ts.test_id = tt.id
            WHERE ts.username = ? GROUP BY ts.test_id ORDER BY latest DESC LIMIT 5
            """,
            (username,),
        )
        recent_theory_results = cursor.fetchall()

        cursor.execute(
            """
            SELECT tt.subject, ROUND(AVG(best_pct),1)
            FROM (SELECT test_id, MAX(percentage) as best_pct FROM theory_submissions WHERE username = ? GROUP BY test_id) b
            JOIN theory_tests tt ON b.test_id = tt.id
            WHERE tt.subject IS NOT NULL AND tt.subject != ''
            GROUP BY tt.subject
            """,
            (username,),
        )
        theory_subject_avgs = cursor.fetchall()

        attendance_year = datetime.now().year
        attendance_days = get_current_year_attendance_days()
        auto_exclude_empty_attendance_days(cursor, [user_group], created_by=username, days=attendance_days)
        cursor.execute("SELECT date FROM excluded_dates WHERE group_name IS NULL OR group_name = ?", (user_group,))
        excluded_dates = {row[0] for row in cursor.fetchall()}
        login_map = fetch_first_login_times(cursor, [username], attendance_days)
        override_map = fetch_attendance_override_statuses(cursor, [username], attendance_days)
        late_cutoffs = fetch_group_late_thresholds(cursor, user_group, attendance_days) if user_group else {}
        cursor.execute(
            """
            SELECT DISTINCT lh.date
            FROM login_history lh
            JOIN users u ON u.username = lh.username
            WHERE u.group_name = ? AND u.role = 'student' AND lh.username != ?
            """,
            (user_group, username),
        )
        class_checked_dates = {row[0] for row in cursor.fetchall()}
        att_history = build_attendance_history(
            cursor,
            username,
            user_group,
            attendance_days,
            login_map=login_map,
            override_map=override_map,
            late_cutoffs=late_cutoffs,
            class_checked_dates=class_checked_dates,
            excluded_dates=excluded_dates,
        )
        attendance_months = build_attendance_months(att_history)
        attendance_summary = summarize_attendance_history(att_history)
        att_pct = attendance_summary["attendance_pct"]

        today = datetime.now().date().isoformat()
        cursor.execute("SELECT id, name FROM subjects ORDER BY name")
        all_subjects = cursor.fetchall()
        subjects_with_tasks = []
        for subj_id, subj_name in all_subjects:
            cursor.execute(
                """
                SELECT t.id, t.name
                FROM tasks t
                JOIN task_groups tg ON t.id = tg.task_id
                WHERE t.subject_id = ? AND tg.group_name = ? AND t.assign_date <= ?
                AND t.task_type = 'practical' AND t.is_active = 1
                ORDER BY t.name
                """,
                (subj_id, user_group, today),
            )
            tasks_for_subj = cursor.fetchall()
            if tasks_for_subj:
                subjects_with_tasks.append({"id": subj_id, "name": subj_name, "tasks": tasks_for_subj})

        cursor.execute(
            """
            SELECT t.id,
                   s.name AS subject_name,
                   t.name AS task_name,
                   t.assign_date,
                   t.marking_script
            FROM tasks t
            JOIN subjects s ON t.subject_id = s.id
            JOIN task_groups tg ON t.id = tg.task_id
            WHERE tg.group_name = ?
              AND t.assign_date <= ?
              AND t.task_type = 'practical'
              AND t.is_active = 1
              AND NOT EXISTS (
                  SELECT 1 FROM results r
                  WHERE r.username = ? AND r.subject = s.name AND r.task = t.name
              )
            ORDER BY t.assign_date, t.name
            LIMIT 10
            """,
            (user_group, today, username),
        )
        practical_missing = cursor.fetchall()

        practical_missing_assignments = [
            {
                "type": "practical",
                "subject": row[1],
                "activity": row[2],
                "due": row[3],
                "task_id": row[0],
                "subject_id": None,
                "start_url": None,
            }
            for row in practical_missing
        ]

        if practical_missing_assignments:
            task_ids = [assignment["task_id"] for assignment in practical_missing_assignments]
            placeholders = ",".join(["?"] * len(task_ids))
            cursor.execute(
                f"""
                SELECT id, subject_id
                FROM tasks
                WHERE id IN ({placeholders})
                """,
                task_ids,
            )
            id_to_subject = {row[0]: row[1] for row in cursor.fetchall()}
            for assignment in practical_missing_assignments:
                assignment["subject_id"] = id_to_subject.get(assignment["task_id"])
                if assignment["subject_id"] is not None:
                    assignment["start_url"] = f"/upload/{username}/{assignment['subject_id']}/{assignment['task_id']}"

        cursor.execute(
            """
            SELECT tt.id,
                   tt.subject,
                   tt.title,
                   tt.time_limit,
                   tt.allow_multiple,
                   tt.max_attempts
            FROM theory_tests tt
            JOIN theory_test_groups ttg ON tt.id = ttg.test_id
            WHERE tt.is_active = 1
              AND ttg.group_name = ?
              AND NOT EXISTS (
                  SELECT 1 FROM theory_submissions ts
                  WHERE ts.username = ? AND ts.test_id = tt.id
              )
            ORDER BY tt.subject, tt.title
            LIMIT 10
            """,
            (user_group, username),
        )
        theory_missing = cursor.fetchall()

        theory_missing_assignments = [
            {
                "type": "theory",
                "subject": row[1] or "Theory",
                "activity": row[2],
                "due": None,
                "test_id": row[0],
                "start_url": f"/take_test/{row[0]}",
            }
            for row in theory_missing
        ]

        missing_assignments = practical_missing_assignments + theory_missing_assignments
        missing_tasks = [
            (None, assignment["subject"], assignment["activity"], assignment["due"] or "")
            for assignment in missing_assignments
            if assignment["type"] == "practical"
        ]
        missing_assignments = practical_missing_assignments + theory_missing_assignments

        cursor.execute(
            "SELECT skill, count FROM weaknesses WHERE username = ? ORDER BY count DESC LIMIT 5",
            (username,),
        )
        weaknesses = cursor.fetchall()

        cursor.execute(
            """
            SELECT subject, task, feedback, timestamp
            FROM results WHERE username = ? AND feedback IS NOT NULL AND feedback != ''
            ORDER BY timestamp DESC LIMIT 3
            """,
            (username,),
        )
        recent_feedback = cursor.fetchall()

        message_threads = get_student_message_threads(username)
        unread_teacher_messages = get_student_unread_message_count(username)
        auto_open_chat = student_has_fresh_teacher_reply(username)

        conn.close()
        return render_template(
            "student_dashboard.html",
            username=username,
            display_name=display_name,
            overall_avg=overall_avg,
            practical_avg=practical_avg,
            theory_avg=theory_avg,
            subject_avgs=subject_avgs,
            theory_subject_avgs=theory_subject_avgs,
            recent_results=recent_results,
            recent_theory_results=recent_theory_results,
            att_history=att_history,
            attendance_months=attendance_months,
            attendance_year=attendance_year,
            att_pct=att_pct,
            present_days=attendance_summary["present_days"],
            absent_days=attendance_summary["absent_days"],
            late_days=attendance_summary["late_days"],
            total_attendance_days=attendance_summary["total_days"],
            subjects_with_tasks=subjects_with_tasks,
            missing_assignments=missing_assignments,
            missing_tasks=missing_tasks,
            weaknesses=weaknesses,
            recent_feedback=recent_feedback,
            message_threads=message_threads,
            unread_teacher_messages=unread_teacher_messages,
            auto_open_chat=auto_open_chat,
        )

    @app.route("/active")
    def active():
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))

        role = get_user_role(username)
        if role not in ["teacher", "admin"]:
            return "Access denied", 403

        now = datetime.now()
        with lock:
            active_list = []
            to_remove = []
            for user, last_seen in list(active_users.items()):
                if now - last_seen < timedelta(seconds=TIMEOUT):
                    active_list.append(user)
                else:
                    to_remove.append(user)
            for user in to_remove:
                del active_users[user]

        return render_template("active.html", users=active_list)

    @app.route("/view_as_student/<group_name>")
    def view_as_student(group_name):
        admin_user = session.get("username")
        if not admin_user:
            return redirect(url_for("login"))
        if get_user_role(admin_user) not in ["teacher", "admin"]:
            return "Access denied", 403

        conn = get_db()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT username, full_name, group_name FROM users
            WHERE group_name = ? AND role = 'student' LIMIT 1
            """,
            (group_name,),
        )
        rep = cursor.fetchone()

        cursor.execute("SELECT COUNT(*) FROM users WHERE group_name = ? AND role = 'student'", (group_name,))
        student_count = cursor.fetchone()[0]

        cursor.execute(
            """
            SELECT username, full_name FROM users
            WHERE group_name = ? AND role = 'student' ORDER BY full_name
            """,
            (group_name,),
        )
        students = cursor.fetchall()

        practical_group_avg = fetch_group_practical_averages(cursor, [group_name]).get(group_name)
        theory_group_avg = fetch_group_theory_averages(cursor, [group_name]).get(group_name)
        if practical_group_avg is not None and theory_group_avg is not None:
            overall_avg = round((practical_group_avg + theory_group_avg) / 2, 1)
        else:
            overall_avg = practical_group_avg if practical_group_avg is not None else (theory_group_avg or 0)

        cursor.execute(
            """
            SELECT u.full_name, r.subject, r.task, r.score, r.timestamp
            FROM results r
            JOIN users u ON r.username = u.username
            WHERE u.group_name = ?
            ORDER BY r.timestamp DESC LIMIT 10
            """,
            (group_name,),
        )
        recent_results = cursor.fetchall()

        attendance_year = datetime.now().year
        days = get_current_year_attendance_days()
        auto_exclude_empty_attendance_days(cursor, [group_name], created_by=admin_user, days=days)
        excluded = fetch_group_excluded_dates(cursor, [group_name]).get(group_name, set())
        student_usernames = [student_username for student_username, _full_name in students]
        login_times = fetch_first_login_times(cursor, student_usernames, days)
        overrides = fetch_attendance_override_statuses(cursor, student_usernames, days)
        late_cutoffs = fetch_group_late_thresholds(cursor, group_name, days)
        cursor.execute(
            """
            SELECT DISTINCT lh.date
            FROM login_history lh
            JOIN users u ON u.username = lh.username
            WHERE u.group_name = ? AND u.role = 'student'
            """,
            (group_name,),
        )
        class_checked_dates = {row[0] for row in cursor.fetchall()}

        att_summary = []
        for day in days:
            present = 0
            absent = 0
            for student_username in student_usernames:
                history = build_attendance_history(
                    cursor,
                    student_username,
                    group_name,
                    [day],
                    login_map=login_times,
                    override_map=overrides,
                    late_cutoffs=late_cutoffs,
                    class_checked_dates=class_checked_dates,
                    excluded_dates=excluded,
                )
                summary = summarize_attendance_history(history)
                present += summary["present_days"]
                absent += summary["absent_days"]
            total_counted = present + absent
            pct = round((present / total_counted) * 100) if total_counted else 0
            att_summary.append({"date": day, "present": present, "total": total_counted, "pct": pct})

        att_summary_map = {item["date"]: item for item in att_summary}
        attendance_history = []
        for day in days:
            weekday = datetime.strptime(day, "%Y-%m-%d").weekday()
            summary = att_summary_map.get(day, {"pct": 0, "present": 0, "total": 0})
            if day in excluded or summary["total"] == 0:
                status = "Normal"
            elif summary["pct"] > 0:
                status = "Present"
            else:
                status = "Absent"
            attendance_history.append(
                {
                    "date": day,
                    "status": status,
                    "time": f"{summary['pct']}% class" if summary["total"] else "",
                    "late": False,
                    "note": "",
                    "weekday": weekday,
                    "class_pct": summary["pct"],
                    "present": summary["present"],
                    "total": summary["total"],
                }
            )
        attendance_months = build_attendance_months(attendance_history)

        today = datetime.now().date().isoformat()
        cursor.execute(
            """
            SELECT s.name, t.name, t.assign_date,
                   COUNT(DISTINCT u.username) as missing_count
            FROM tasks t
            JOIN subjects s ON s.id = t.subject_id
            JOIN task_groups tg ON tg.task_id = t.id
            JOIN users u ON u.group_name = tg.group_name AND u.role = 'student'
            WHERE tg.group_name = ? AND t.assign_date <= ? AND t.task_type = 'practical'
              AND NOT EXISTS (
                  SELECT 1 FROM results r
                  WHERE r.username = u.username AND r.subject = s.name AND r.task = t.name
              )
            GROUP BY t.id
            ORDER BY t.assign_date
            """,
            (group_name, today),
        )
        missing_tasks = cursor.fetchall()

        cursor.execute(
            """
            SELECT w.skill, SUM(w.count) as total
            FROM weaknesses w
            JOIN users u ON w.username = u.username
            WHERE u.group_name = ?
            GROUP BY w.skill ORDER BY total DESC LIMIT 5
            """,
            (group_name,),
        )
        weaknesses = cursor.fetchall()
        theory_module_weaknesses = fetch_theory_module_weaknesses(cursor, group_name=group_name, limit=10)

        cursor.execute(
            """
            SELECT t.title, ROUND(AVG(s.percentage), 1), COUNT(DISTINCT s.username)
            FROM theory_submissions s
            JOIN theory_tests t ON s.test_id = t.id
            JOIN users u ON s.username = u.username
            WHERE u.group_name = ?
            GROUP BY t.id ORDER BY s.submitted_at DESC LIMIT 5
            """,
            (group_name,),
        )
        theory_avgs = cursor.fetchall()

        practical_avg_map = fetch_student_practical_averages(cursor)
        theory_avg_map = fetch_student_theory_averages(cursor)
        class_rankings = []
        for student_username, full_name in students:
            practical_avg = practical_avg_map.get(student_username)
            theory_avg = theory_avg_map.get(student_username)
            if practical_avg is not None and theory_avg is not None:
                combined_avg = round((practical_avg + theory_avg) / 2, 1)
            else:
                combined_avg = practical_avg if practical_avg is not None else theory_avg
            combined_avg = combined_avg if combined_avg is not None else 0
            class_rankings.append((student_username, full_name or student_username, combined_avg))
        class_rankings.sort(key=lambda item: item[2], reverse=True)
        top_performers = class_rankings[:5]

        conn.close()
        return render_template(
            "view_as_student.html",
            group_name=group_name,
            student_count=student_count,
            students=students,
            overall_avg=overall_avg,
            recent_results=recent_results,
            att_summary=att_summary,
            attendance_months=attendance_months,
            attendance_year=attendance_year,
            top_performers=top_performers,
            class_rankings=class_rankings,
            missing_tasks=missing_tasks,
            weaknesses=weaknesses,
            theory_module_weaknesses=theory_module_weaknesses,
            theory_avgs=theory_avgs,
        )

    @app.route("/teacher_dashboard")
    def teacher_dashboard():
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))

        role = get_user_role(username)
        if role not in ["teacher", "admin"]:
            return "Access denied", 403

        conn = get_db()
        cursor = conn.cursor()
        today = datetime.now().strftime("%Y-%m-%d")
        groups = get_groups(username)
        quick_actions, available_quick_actions = get_teacher_selected_quick_actions(username)

        if role == "teacher":
            cursor.execute(
                """
                SELECT username, full_name, group_name
                FROM users
                WHERE role = 'student' AND teacher_username = ?
                ORDER BY group_name, full_name, username
                """,
                (username,),
            )
        else:
            cursor.execute(
                """
                SELECT username, full_name, group_name
                FROM users
                WHERE role = 'student'
                ORDER BY group_name, full_name, username
                """
            )
        student_rows = cursor.fetchall()
        total_students = len(student_rows)
        student_usernames = [row[0] for row in student_rows]
        student_groups = sorted({row[2] for row in student_rows if row[2]})
        groups = student_groups or groups
        group_filter_clause = "AND u.teacher_username = ?" if role == "teacher" else ""
        group_filter_params = [username] if role == "teacher" else []

        cursor.execute(
            """
            SELECT COUNT(DISTINCT lh.username)
            FROM login_history lh
            JOIN users u ON u.username = lh.username
            WHERE lh.date = ? AND u.role = 'student'
            """
            + (" AND u.teacher_username = ?" if role == "teacher" else ""),
            ((today, username) if role == "teacher" else (today,)),
        )
        active_today = cursor.fetchone()[0] or 0

        days_21 = get_last_21_days()
        excluded_days = fetch_group_excluded_dates(cursor, groups)
        filtered_days = [day for day in days_21 if day not in excluded_days]
        login_times = fetch_first_login_times(cursor, student_usernames, filtered_days)
        overrides = fetch_attendance_override_statuses(cursor, student_usernames, filtered_days)

        group_members = defaultdict(list)
        for uname, full_name, group_name in student_rows:
            if group_name:
                group_members[group_name].append((uname, full_name or uname))

        group_att = []
        total_present_all = 0
        total_slots_all = 0
        for group_name in groups:
            members = group_members.get(group_name, [])
            group_days = [day for day in filtered_days if day not in excluded_days.get(group_name, set())]
            total_present = 0
            total_absent = 0
            for student_username, _student_name in members:
                history = build_attendance_history(
                    cursor,
                    student_username,
                    group_name,
                    group_days,
                    login_map=login_times,
                    override_map=overrides,
                    excluded_dates=excluded_days.get(group_name, set()),
                )
                summary = summarize_attendance_history(history)
                total_present += summary["present_days"]
                total_absent += summary["absent_days"]
            total_counted = total_present + total_absent
            total_present_all += total_present
            total_slots_all += total_counted
            group_att.append(
                {
                    "group": group_name,
                    "students": len(members),
                    "att_pct": round((total_present / total_counted) * 100) if total_counted else 0,
                }
            )
        avg_att_pct = round((total_present_all / total_slots_all) * 100) if total_slots_all else 0

        low_attendance = get_low_attendance_learners(10, groups, username if role == "teacher" else None)
        practical_avg_map = fetch_student_practical_averages(cursor, username if role == "teacher" else None)
        theory_avg_map = fetch_student_theory_averages(cursor, username if role == "teacher" else None)
        practical_group_avg_map = fetch_group_practical_averages(cursor, groups)
        theory_group_avg_map = fetch_group_theory_averages(cursor, groups)

        missing_practical_map = {}
        missing_theory_map = {}
        if student_usernames:
            placeholders = ",".join("?" for _ in student_usernames)
            cursor.execute(
                f"""
                SELECT u.username, COUNT(*)
                FROM users u
                JOIN task_groups tg ON tg.group_name = u.group_name
                JOIN tasks t ON t.id = tg.task_id
                JOIN subjects s ON s.id = t.subject_id
                WHERE u.username IN ({placeholders})
                  AND t.assign_date <= ?
                  AND t.task_type = 'practical'
                  AND t.is_active = 1
                  AND NOT EXISTS (
                      SELECT 1 FROM results r
                      WHERE r.username = u.username AND r.subject = s.name AND r.task = t.name
                  )
                GROUP BY u.username
                """,
                (*student_usernames, today),
            )
            missing_practical_map = {row[0]: row[1] for row in cursor.fetchall()}

            cursor.execute(
                f"""
                SELECT u.username, COUNT(DISTINCT tt.id)
                FROM users u
                JOIN theory_tests tt ON tt.is_active = 1 AND tt.assign_date <= ?
                LEFT JOIN theory_test_groups ttg ON tt.id = ttg.test_id
                WHERE u.username IN ({placeholders})
                  AND (ttg.group_name = u.group_name OR ttg.group_name IS NULL)
                  AND NOT EXISTS (
                      SELECT 1 FROM theory_submissions ts
                      WHERE ts.username = u.username AND ts.test_id = tt.id
                  )
                GROUP BY u.username
                """,
                (today, *student_usernames),
            )
            missing_theory_map = {row[0]: row[1] for row in cursor.fetchall()}

        at_risk_students = []
        combined_students = []
        for uname, full_name, group_name in student_rows:
            group_days = [day for day in filtered_days if day not in excluded_days.get(group_name, set())]
            attendance_history = build_attendance_history(
                cursor,
                uname,
                group_name,
                group_days,
                login_map=login_times,
                override_map=overrides,
                excluded_dates=excluded_days.get(group_name, set()),
            )
            attendance_pct = summarize_attendance_history(attendance_history)["attendance_pct"]

            practical_avg = practical_avg_map.get(uname)
            theory_avg = theory_avg_map.get(uname)
            if practical_avg is not None and theory_avg is not None:
                combined_avg = round((practical_avg + theory_avg) / 2, 1)
            else:
                combined_avg = practical_avg if practical_avg is not None else theory_avg
            combined_avg = combined_avg if combined_avg is not None else 0

            missing_total = (missing_practical_map.get(uname, 0) or 0) + (missing_theory_map.get(uname, 0) or 0)
            assigned_total = missing_total
            if practical_avg is not None or theory_avg is not None:
                assigned_total = max(assigned_total, 1)
            missing_pct = round((missing_total / assigned_total) * 100) if assigned_total else 0

            risk_score = round((100 - attendance_pct) * 0.4 + (100 - combined_avg) * 0.4 + missing_pct * 0.2)
            reasons = []
            if attendance_pct < 60:
                reasons.append(f"Attendance {attendance_pct}%")
            if combined_avg < 40:
                reasons.append(f"Average {combined_avg}%")
            if missing_total > 0:
                reasons.append(f"Missing {missing_total}")
            if risk_score > 40:
                at_risk_students.append(
                    {
                        "username": uname,
                        "name": full_name or uname,
                        "group": group_name or "—",
                        "score": risk_score,
                        "status": "High Risk" if risk_score > 70 else "At Risk",
                        "reason": " | ".join(reasons) if reasons else "Multiple factors",
                    }
                )
            combined_students.append((full_name or uname, group_name or "—", combined_avg))

        at_risk_students.sort(key=lambda item: item["score"], reverse=True)
        at_risk_students = at_risk_students[:10]
        combined_students = [row for row in combined_students if row[2] is not None]
        top_performers = sorted(combined_students, key=lambda item: item[2], reverse=True)[:5]
        bottom_performers = sorted(combined_students, key=lambda item: item[2])[:5]

        if role == "teacher":
            cursor.execute(
                """
                SELECT a.username, a.action, a.timestamp
                FROM activities a
                LEFT JOIN users u ON u.username = a.username
                WHERE a.username = ?
                  OR (u.role = 'student' AND u.teacher_username = ?)
                ORDER BY a.timestamp DESC LIMIT 20
                """,
                (username, username),
            )
        else:
            cursor.execute(
                """
                SELECT username, action, timestamp FROM activities
                ORDER BY timestamp DESC LIMIT 20
                """
            )
        recent_activities = cursor.fetchall()

        if role == "teacher":
            cursor.execute(
                f"""
                SELECT u.full_name, u.group_name, b.subject, b.task, b.best_score, MAX(r.timestamp)
                FROM (
                    SELECT username, subject, task, MAX(score) as best_score
                    FROM results GROUP BY username, subject, task
                ) b
                JOIN results r ON r.username = b.username AND r.subject = b.subject AND r.task = b.task AND r.score = b.best_score
                JOIN users u ON u.username = b.username
                WHERE u.role = 'student' {group_filter_clause}
                GROUP BY b.username, b.subject, b.task
                ORDER BY MAX(r.timestamp) DESC LIMIT 15
                """,
                group_filter_params,
            )
        else:
            cursor.execute(
                """
                SELECT u.full_name, u.group_name, b.subject, b.task, b.best_score, MAX(r.timestamp)
                FROM (
                    SELECT username, subject, task, MAX(score) as best_score
                    FROM results GROUP BY username, subject, task
                ) b
                JOIN results r ON r.username = b.username AND r.subject = b.subject AND r.task = b.task AND r.score = b.best_score
                JOIN users u ON u.username = b.username
                GROUP BY b.username, b.subject, b.task
                ORDER BY MAX(r.timestamp) DESC LIMIT 15
                """
            )
        recent_submissions = cursor.fetchall()

        practical_subjects = defaultdict(set)
        if role == "teacher" and groups:
            placeholders = ",".join("?" for _ in groups)
            cursor.execute(
                f"""
                SELECT tg.group_name, s.name
                FROM task_groups tg
                JOIN tasks t ON t.id = tg.task_id
                JOIN subjects s ON s.id = t.subject_id
                WHERE t.task_type = 'practical' AND tg.group_name IN ({placeholders})
                """,
                groups,
            )
        else:
            cursor.execute(
                """
                SELECT tg.group_name, s.name
                FROM task_groups tg
                JOIN tasks t ON t.id = tg.task_id
                JOIN subjects s ON s.id = t.subject_id
                WHERE t.task_type = 'practical'
                """
            )
        for group_name, subject in cursor.fetchall():
            practical_subjects[group_name].add(subject)

        if role == "teacher":
            cursor.execute(
                f"""
                SELECT u.group_name, b.subject, ROUND(AVG(b.best_score),1), COUNT(*)
                FROM (
                    SELECT username, subject, task, MAX(score) as best_score
                    FROM results GROUP BY username, subject, task
                ) b
                JOIN users u ON u.username = b.username
                WHERE u.group_name IS NOT NULL AND u.role = 'student' {group_filter_clause}
                GROUP BY u.group_name, b.subject
                ORDER BY u.group_name, b.subject
                """,
                group_filter_params,
            )
        else:
            cursor.execute(
                """
                SELECT u.group_name, b.subject, ROUND(AVG(b.best_score),1), COUNT(*)
                FROM (
                    SELECT username, subject, task, MAX(score) as best_score
                    FROM results GROUP BY username, subject, task
                ) b
                JOIN users u ON u.username = b.username
                WHERE u.group_name IS NOT NULL AND u.role = 'student'
                GROUP BY u.group_name, b.subject
                ORDER BY u.group_name, b.subject
                """
            )
        practical_avgs_raw = cursor.fetchall()
        practical_avgs = {(group_name, subject): (avg, cnt) for group_name, subject, avg, cnt in practical_avgs_raw}

        subject_avgs = defaultdict(list)
        for group_name, subjects in practical_subjects.items():
            for subject in sorted(subjects):
                avg, cnt = practical_avgs.get((group_name, subject), (None, 0))
                subject_avgs[group_name].append((subject, avg, cnt, "Practical"))

        for group_name, subject, avg, cnt in practical_avgs_raw:
            if subject not in practical_subjects.get(group_name, set()):
                subject_avgs[group_name].append((subject, avg, cnt, "Practical"))

        if role == "teacher":
            cursor.execute(
                f"""
                SELECT u.group_name, ROUND(AVG(b.best_pct),1), COUNT(*)
                FROM (
                    SELECT username, test_id, MAX(percentage) as best_pct
                    FROM theory_submissions GROUP BY username, test_id
                ) b
                JOIN theory_tests tt ON b.test_id = tt.id
                JOIN users u ON u.username = b.username
                WHERE u.group_name IS NOT NULL AND u.role = 'student' {group_filter_clause}
                GROUP BY u.group_name
                ORDER BY u.group_name
                """,
                group_filter_params,
            )
        else:
            cursor.execute(
                """
                SELECT u.group_name, ROUND(AVG(b.best_pct),1), COUNT(*)
                FROM (
                    SELECT username, test_id, MAX(percentage) as best_pct
                    FROM theory_submissions GROUP BY username, test_id
                ) b
                JOIN theory_tests tt ON b.test_id = tt.id
                JOIN users u ON u.username = b.username
                WHERE u.group_name IS NOT NULL AND u.role = 'student'
                GROUP BY u.group_name
                ORDER BY u.group_name
                """
            )
        theory_avgs_raw = cursor.fetchall()
        theory_avgs = {group_name: (avg, cnt) for group_name, avg, cnt in theory_avgs_raw}

        theory_groups = set()
        if role == "teacher" and groups:
            placeholders = ",".join("?" for _ in groups)
            cursor.execute(
                f"""
                SELECT DISTINCT ttg.group_name
                FROM theory_tests tt
                JOIN theory_test_groups ttg ON tt.id = ttg.test_id
                WHERE tt.assign_date IS NOT NULL AND ttg.group_name IN ({placeholders})
                """,
                groups,
            )
            theory_groups.update(row[0] for row in cursor.fetchall() if row[0])
            cursor.execute(
                """
                SELECT 1
                FROM theory_tests tt
                LEFT JOIN theory_test_groups ttg ON tt.id = ttg.test_id
                WHERE tt.assign_date IS NOT NULL AND ttg.group_name IS NULL
                LIMIT 1
                """
            )
            if cursor.fetchone():
                theory_groups.update(groups)
        else:
            cursor.execute(
                """
                SELECT DISTINCT ttg.group_name
                FROM theory_tests tt
                JOIN theory_test_groups ttg ON tt.id = ttg.test_id
                WHERE tt.assign_date IS NOT NULL AND ttg.group_name IS NOT NULL
                """
            )
            theory_groups.update(row[0] for row in cursor.fetchall() if row[0])
            cursor.execute(
                """
                SELECT 1
                FROM theory_tests tt
                LEFT JOIN theory_test_groups ttg ON tt.id = ttg.test_id
                WHERE tt.assign_date IS NOT NULL AND ttg.group_name IS NULL
                LIMIT 1
                """
            )
            if cursor.fetchone():
                cursor.execute("SELECT DISTINCT group_name FROM users WHERE group_name IS NOT NULL")
                theory_groups.update(row[0] for row in cursor.fetchall() if row[0])

        for group_name in sorted(theory_groups):
            avg, cnt = theory_avgs.get(group_name, (None, 0))
            subject_avgs[group_name].append(("Theory", avg, cnt, "Theory"))

        subject_avgs = dict(subject_avgs)

        if role == "teacher":
            cursor.execute(
                f"""
                SELECT u.full_name, u.group_name, tt.subject, tt.title, b.best_pct, MAX(ts.submitted_at)
                FROM (
                    SELECT username, test_id, MAX(percentage) as best_pct
                    FROM theory_submissions GROUP BY username, test_id
                ) b
                JOIN theory_submissions ts ON ts.username = b.username AND ts.test_id = b.test_id AND ts.percentage = b.best_pct
                JOIN theory_tests tt ON b.test_id = tt.id
                JOIN users u ON u.username = b.username
                WHERE u.role = 'student' {group_filter_clause}
                GROUP BY b.username, b.test_id
                ORDER BY MAX(ts.submitted_at) DESC LIMIT 15
                """,
                group_filter_params,
            )
        else:
            cursor.execute(
                """
                SELECT u.full_name, u.group_name, tt.subject, tt.title, b.best_pct, MAX(ts.submitted_at)
                FROM (
                    SELECT username, test_id, MAX(percentage) as best_pct
                    FROM theory_submissions GROUP BY username, test_id
                ) b
                JOIN theory_submissions ts ON ts.username = b.username AND ts.test_id = b.test_id AND ts.percentage = b.best_pct
                JOIN theory_tests tt ON b.test_id = tt.id
                JOIN users u ON u.username = b.username
                GROUP BY b.username, b.test_id
                ORDER BY MAX(ts.submitted_at) DESC LIMIT 15
                """
            )
        recent_theory_submissions = cursor.fetchall()

        cursor.execute(
            """
            SELECT username, full_name
            FROM users
            WHERE role = 'student' AND (
                (group_name IS NULL OR group_name = '') OR
                (teacher_username IS NULL OR teacher_username = '')
            )
            ORDER BY full_name, username
            """
        )
        students_without_classes = cursor.fetchall()

        if role == "teacher":
            cursor.execute(
                f"""
                SELECT u.group_name, COUNT(*) as missing
                FROM users u
                JOIN task_groups tg ON tg.group_name = u.group_name
                JOIN tasks t ON t.id = tg.task_id
                JOIN subjects s ON s.id = t.subject_id
                WHERE u.role = 'student'
                  AND u.group_name IS NOT NULL
                  AND t.assign_date <= ?
                  AND t.task_type = 'practical'
                  AND NOT EXISTS (
                      SELECT 1 FROM results r
                      WHERE r.username = u.username AND r.subject = s.name AND r.task = t.name
                  )
                  {group_filter_clause}
                GROUP BY u.group_name
                """,
                (today, *group_filter_params),
            )
        else:
            cursor.execute(
                """
                SELECT u.group_name, COUNT(*) as missing
                FROM users u
                JOIN task_groups tg ON tg.group_name = u.group_name
                JOIN tasks t ON t.id = tg.task_id
                JOIN subjects s ON s.id = t.subject_id
                WHERE u.role = 'student'
                  AND t.assign_date <= ?
                  AND t.task_type = 'practical'
                  AND NOT EXISTS (
                      SELECT 1 FROM results r
                      WHERE r.username = u.username AND r.subject = s.name AND r.task = t.name
                  )
                GROUP BY u.group_name
                """,
                (today,),
            )
        missing_by_group = cursor.fetchall()

        group_att_summary = []
        for item in group_att:
            practical_group_avg = practical_group_avg_map.get(item["group"])
            theory_group_avg = theory_group_avg_map.get(item["group"])
            if practical_group_avg is not None and theory_group_avg is not None:
                combined_group_avg = round((practical_group_avg + theory_group_avg) / 2, 1)
            else:
                combined_group_avg = practical_group_avg if practical_group_avg is not None else theory_group_avg
            group_att_summary.append(
                {
                    **item,
                    "practical_pct": practical_group_avg,
                    "theory_pct": theory_group_avg,
                    "combined_pct": combined_group_avg,
                }
            )

        conn.close()
        return render_template(
            "teacher_dashboard.html",
            username=username,
            total_students=total_students,
            active_today=active_today,
            avg_att_pct=avg_att_pct,
            groups=groups,
            group_att=group_att_summary,
            low_attendance=low_attendance,
            recent_activities=recent_activities,
            recent_submissions=recent_submissions,
            recent_theory_submissions=recent_theory_submissions,
            subject_avgs=subject_avgs,
            top_performers=top_performers,
            bottom_performers=bottom_performers,
            at_risk_students=at_risk_students,
            students_without_classes=students_without_classes,
            missing_by_group=missing_by_group,
            quick_actions=quick_actions,
            available_quick_actions=available_quick_actions,
            active_term=get_active_term_range(),
            days_in_period=len(days_21),
        )

    @app.route("/dashboard")
    def legacy_dashboard():
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))
        role = get_user_role(username)
        if role in ["teacher", "admin"]:
            return redirect(url_for("teacher_dashboard"))
        return redirect(url_for("student_dashboard"))
