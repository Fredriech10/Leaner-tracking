from datetime import datetime

import pandas as pd
from flask import redirect, render_template, request, send_file, session, url_for

from app.database import get_db, get_groups, get_user_role, log_activity
from app.helper_attendance import (
    auto_exclude_empty_attendance_days,
    build_attendance_group_summary,
    build_attendance_history,
    build_attendance_months,
    fetch_class_checked_dates,
    fetch_attendance_override_statuses,
    fetch_first_login_times,
    fetch_group_excluded_dates,
    fetch_group_late_thresholds,
    get_current_year_attendance_days,
    get_last_21_days,
    summarize_attendance_history,
)
from app.helper_results import (
    fetch_group_practical_averages,
    fetch_group_theory_averages,
    fetch_student_practical_averages,
    fetch_student_theory_averages,
    fetch_theory_module_weaknesses,
)


def register_results_routes(app):
    @app.route("/learner_record/<username>")
    def learner_record(username):
        admin_user = session.get("username")
        if not admin_user:
            return redirect(url_for("login"))
        admin_role = get_user_role(admin_user)
        if admin_role not in ["teacher", "admin"]:
            return "Access denied", 403

        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("SELECT username, full_name, group_name, role, last_active FROM users WHERE username = ?", (username,))
        user = cursor.fetchone()
        if not user:
            conn.close()
            return "User not found", 404

        if admin_role == "teacher":
            cursor.execute("SELECT teacher_username FROM users WHERE username = ?", (username,))
            row = cursor.fetchone()
            if not row or row[0] != admin_user:
                conn.close()
                return "Access denied", 403

        attendance_year = datetime.now().year
        days = get_current_year_attendance_days()
        cursor.execute("SELECT group_name, teacher_username FROM users WHERE username = ?", (username,))
        group_row = cursor.fetchone()
        user_group = group_row[0] if group_row else None
        learner_teacher = group_row[1] if group_row else None
        auto_exclude_empty_attendance_days(cursor, [user_group], created_by=admin_user, days=days)
        cursor.execute(
            """
            SELECT date FROM excluded_dates
            WHERE group_name IS NULL OR group_name = ?
            """,
            (user_group,),
        )
        excluded_dates = {row[0] for row in cursor.fetchall()}
        class_checked_dates = fetch_class_checked_dates(cursor, user_group, teacher_username=learner_teacher, exclude_username=username)

        login_map = fetch_first_login_times(cursor, [username], days)
        override_map = fetch_attendance_override_statuses(cursor, [username], days)
        late_cutoffs = fetch_group_late_thresholds(cursor, user_group, days, teacher_username=learner_teacher) if user_group else {}
        history = build_attendance_history(
            cursor,
            username,
            user_group,
            days,
            login_map=login_map,
            override_map=override_map,
            late_cutoffs=late_cutoffs,
            class_checked_dates=class_checked_dates,
            excluded_dates=excluded_dates,
        )
        attendance_summary = summarize_attendance_history(history)
        total_days = attendance_summary["total_days"]
        present_days = attendance_summary["present_days"]
        absent_days = attendance_summary["absent_days"]
        late_days = attendance_summary["late_days"]
        attendance_pct = attendance_summary["attendance_pct"]
        recent_history = history[-10:]
        attendance_months = build_attendance_months(history)

        cursor.execute(
            """
            SELECT subject, task, MAX(score) as score, feedback, MAX(timestamp) as timestamp
            FROM results WHERE username = ? GROUP BY subject, task ORDER BY timestamp DESC
            """,
            (username,),
        )
        all_results = cursor.fetchall()

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
        overall_avg_row = cursor.fetchone()
        practical_avg = overall_avg_row[0] if overall_avg_row and overall_avg_row[0] else 0

        cursor.execute(
            """
            SELECT ROUND(AVG(best_pct),1)
            FROM (SELECT test_id, MAX(percentage) as best_pct FROM theory_submissions WHERE username = ? GROUP BY test_id)
            """,
            (username,),
        )
        theory_avg_row = cursor.fetchone()
        theory_avg = theory_avg_row[0] if theory_avg_row and theory_avg_row[0] else None

        overall_avg = round((practical_avg + theory_avg) / 2, 1) if practical_avg and theory_avg else (practical_avg or theory_avg or 0)
        recent_results = all_results[:10]

        scores = [r[2] for r in all_results if r[2] is not None]
        if len(scores) >= 6:
            recent_avg = sum(scores[:3]) / 3
            older_avg = sum(scores[3:6]) / 3
            if recent_avg > older_avg + 2:
                trend = "improving"
            elif recent_avg < older_avg - 2:
                trend = "dropping"
            else:
                trend = "stable"
        else:
            trend = "not enough data"

        cursor.execute("SELECT group_name FROM users WHERE username = ?", (username,))
        user_group_row = cursor.fetchone()
        user_group = user_group_row[0] if user_group_row else None

        cursor.execute(
            """
            SELECT DISTINCT s.name as subject, t.name as task_name
            FROM tasks t
            JOIN subjects s ON t.subject_id = s.id
            JOIN task_groups tg ON t.id = tg.task_id
            WHERE tg.group_name = ? AND t.task_type = 'practical'
            ORDER BY s.name, t.name
            """,
            (user_group,),
        )
        assigned_practical_tasks = cursor.fetchall()

        cursor.execute(
            """
            SELECT DISTINCT tt.id, tt.title, COALESCE(tt.subject, ''),
                   COALESCE(q_stats.total_items, 0),
                   COALESCE(q_stats.test_questions, 0)
            FROM theory_tests tt
            LEFT JOIN theory_test_groups ttg ON tt.id = ttg.test_id
            LEFT JOIN (
                SELECT test_id,
                       COUNT(*) as total_items,
                       SUM(CASE WHEN question_type IN ('content_slide', 'title_slide', 'heading_slide') THEN 0 ELSE 1 END) as test_questions
                FROM theory_questions
                GROUP BY test_id
            ) q_stats ON q_stats.test_id = tt.id
            WHERE (ttg.group_name = ? OR ttg.group_name IS NULL)
            ORDER BY tt.title
            """,
            (user_group,),
        )
        assigned_theory_tests = cursor.fetchall()

        results_map = {(r[0], r[1]): {"score": r[2], "feedback": r[3], "timestamp": r[4]} for r in all_results}
        task_rows = []
        for subject, task in assigned_practical_tasks:
            row = results_map.get((subject, task))
            task_rows.append(
                {
                    "subject": subject,
                    "task": task,
                    "score": row["score"] if row else None,
                    "feedback": row["feedback"] if row else None,
                    "timestamp": row["timestamp"] if row else None,
                    "status": "Submitted" if row else "Not submitted",
                    "type": "practical",
                }
            )

        theory_submissions_map = {}
        for test_id, title, subject, total_items, test_questions in assigned_theory_tests:
            cursor.execute(
                """
                SELECT MAX(percentage), MAX(submitted_at), COUNT(*), COALESCE(SUM(time_spent_seconds), 0),
                       COALESCE(MAX(submission_type), 'test')
                FROM theory_submissions
                WHERE username = ? AND test_id = ?
                """,
                (username, test_id),
            )
            result = cursor.fetchone()
            if result and result[0] is not None:
                theory_submissions_map[test_id] = {
                    "score": result[0],
                    "timestamp": result[1],
                    "attempts": result[2] or 0,
                    "time_spent": result[3] or 0,
                    "submission_type": result[4] or "test",
                }

        for test_id, title, subject, total_items, test_questions in assigned_theory_tests:
            row = theory_submissions_map.get(test_id)
            task_rows.append(
                {
                    "subject": "Theory",
                    "task": title,
                    "score": row["score"] if row else None,
                    "feedback": "",
                    "timestamp": row["timestamp"] if row else None,
                    "status": "Submitted" if row else "Not submitted",
                    "type": "theory",
                }
            )

        average = round(sum(t["score"] for t in task_rows if t["score"] is not None) / max(1, sum(1 for t in task_rows if t["score"] is not None)), 1) if any(t["score"] is not None for t in task_rows) else 0

        cursor.execute(
            """
            SELECT tt.title, ts.score, ts.total, ts.percentage, ts.submitted_at,
                   COALESCE(ts.time_spent_seconds, 0), COALESCE(ts.submission_type, 'test')
            FROM theory_submissions ts
            JOIN theory_tests tt ON ts.test_id = tt.id
            JOIN (
                SELECT test_id, MAX(submitted_at) as latest
                FROM theory_submissions
                WHERE username = ?
                GROUP BY test_id
            ) latest ON latest.test_id = ts.test_id AND latest.latest = ts.submitted_at
            WHERE ts.username = ?
            ORDER BY ts.submitted_at DESC LIMIT 10
            """,
            (username, username),
        )
        theory_results = cursor.fetchall()

        cursor.execute(
            """
            SELECT test_id, current_slide, max_slide, COALESCE(time_spent_seconds, 0),
                   COALESCE(completed, 0), updated_at
            FROM theory_progress
            WHERE username = ?
            """,
            (username,),
        )
        theory_progress_map = {
            row[0]: {
                "current_slide": row[1] or 0,
                "max_slide": row[2] or 0,
                "time_spent": row[3] or 0,
                "completed": bool(row[4]),
                "updated_at": row[5],
            }
            for row in cursor.fetchall()
        }

        practical_total = len(assigned_practical_tasks)
        practical_done = sum(1 for row in task_rows if row["type"] == "practical" and row["score"] is not None)
        theory_total = len(assigned_theory_tests)
        theory_done = 0
        theory_in_progress = 0
        missing_items = []
        learning_progress = []
        theory_time_seconds = 0

        for test_id, title, subject, total_items, test_questions in assigned_theory_tests:
            total_items = total_items or 0
            test_questions = test_questions or 0
            is_lesson = total_items > 0 and test_questions == 0
            submission = theory_submissions_map.get(test_id)
            progress = theory_progress_map.get(test_id, {})
            completed = bool(submission) or bool(progress.get("completed"))
            has_progress = test_id in theory_progress_map
            viewed = min(total_items, (progress.get("max_slide", 0) + 1) if has_progress and total_items else 0)
            progress_pct = 100 if completed else (round((viewed / total_items) * 100) if total_items else 0)
            time_spent = submission["time_spent"] if submission else progress.get("time_spent", 0)
            theory_time_seconds += time_spent or 0

            if completed:
                theory_done += 1
                status = "Completed"
            elif progress_pct > 0:
                theory_in_progress += 1
                status = "In progress"
            else:
                status = "Not started"
                missing_items.append({"type": "Lesson" if is_lesson else "Test", "title": title})

            learning_progress.append(
                {
                    "id": test_id,
                    "title": title,
                    "subject": subject or "Theory",
                    "kind": "Lesson" if is_lesson else "Test",
                    "status": status,
                    "progress_pct": progress_pct,
                    "viewed": viewed,
                    "has_progress": has_progress,
                    "total": total_items,
                    "score": submission["score"] if submission else None,
                    "attempts": submission["attempts"] if submission else 0,
                    "time_spent": time_spent or 0,
                    "updated_at": (submission["timestamp"] if submission else progress.get("updated_at")),
                }
            )

        practical_missing = [{"type": "Practical", "title": f"{row['subject']} - {row['task']}"} for row in task_rows if row["type"] == "practical" and row["score"] is None]
        missing_items = practical_missing + missing_items
        learning_summary = {
            "practical_total": practical_total,
            "practical_done": practical_done,
            "theory_total": theory_total,
            "theory_done": theory_done,
            "theory_in_progress": theory_in_progress,
            "missing_total": len(missing_items),
            "theory_time_seconds": theory_time_seconds,
            "overall_completion": round(((practical_done + theory_done) / max(1, practical_total + theory_total)) * 100, 1),
        }

        cursor.execute(
            """
            SELECT skill, count FROM weaknesses
            WHERE username = ? ORDER BY count DESC LIMIT 10
            """,
            (username,),
        )
        weaknesses = cursor.fetchall()
        theory_module_weaknesses = fetch_theory_module_weaknesses(cursor, username=username, limit=10)

        cursor.execute(
            """
            SELECT action, timestamp FROM activities
            WHERE username = ? ORDER BY timestamp DESC LIMIT 10
            """,
            (username,),
        )
        recent_activity = cursor.fetchall()

        cursor.execute("SELECT id, note, flag, created_by, created_at FROM learner_notes WHERE username = ? ORDER BY created_at DESC", (username,))
        notes = cursor.fetchall()

        conn.close()
        return render_template(
            "learner_record.html",
            user=user,
            history=recent_history,
            attendance_calendar=history,
            attendance_months=attendance_months,
            attendance_year=attendance_year,
            attendance_pct=attendance_pct,
            present_days=present_days,
            absent_days=absent_days,
            late_days=late_days,
            total_days=total_days,
            task_rows=task_rows,
            average=average,
            overall_avg=overall_avg,
            practical_avg=practical_avg,
            theory_avg=theory_avg,
            subject_avgs=subject_avgs,
            recent_results=recent_results,
            theory_results=theory_results,
            learning_summary=learning_summary,
            learning_progress=learning_progress,
            missing_items=missing_items[:12],
            trend=trend,
            weaknesses=weaknesses,
            theory_module_weaknesses=theory_module_weaknesses,
            recent_activity=recent_activity,
            notes=notes,
        )

    @app.route("/learner_record/<username>/add_note", methods=["POST"])
    def add_learner_note(username):
        admin_user = session.get("username")
        if not admin_user:
            return redirect(url_for("login"))
        if get_user_role(admin_user) not in ["teacher", "admin"]:
            return "Access denied", 403
        note = request.form.get("note", "").strip()
        flag = request.form.get("flag", "").strip()
        if note:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO learner_notes (username, note, flag, created_by, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (username, note, flag, admin_user, datetime.now().isoformat()),
            )
            conn.commit()
            conn.close()
        return redirect(url_for("learner_record", username=username))

    @app.route("/learner_record/<username>/delete_note/<int:note_id>", methods=["POST"])
    def delete_learner_note(username, note_id):
        admin_user = session.get("username")
        if not admin_user:
            return redirect(url_for("login"))
        if get_user_role(admin_user) not in ["teacher", "admin"]:
            return "Access denied", 403
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM learner_notes WHERE id = ? AND username = ?", (note_id, username))
        conn.commit()
        conn.close()
        return redirect(url_for("learner_record", username=username))

    @app.route("/remove_results", methods=["POST"])
    def remove_results():
        teacher = session.get("username")
        if not teacher or get_user_role(teacher) not in ["teacher", "admin"]:
            return "Access denied", 403

        task_type = request.form.get("task_type")
        subject = request.form.get("subject", "")
        task_name = request.form.get("task_name", "")
        test_id = request.form.get("test_id", "")
        target = request.form.get("target")
        reason = request.form.get("reason", "").strip()
        group = request.form.get("group", "")

        if not reason:
            reason = "Removed by teacher"

        conn = get_db()
        cursor = conn.cursor()

        if target == "all":
            if task_type == "practical":
                cursor.execute("SELECT DISTINCT username FROM results WHERE subject = ? AND task = ?", (subject, task_name))
            else:
                cursor.execute("SELECT DISTINCT username FROM theory_submissions WHERE test_id = ?", (test_id,))
            affected = [row[0] for row in cursor.fetchall()]
        else:
            affected = [target]

        now = datetime.now().isoformat()
        for username in affected:
            cursor.execute(
                """
                INSERT INTO result_removals
                    (username, task_type, subject, task_name, test_id, removed_by, reason, removed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (username, task_type, subject, task_name, test_id if task_type == "theory" else None, teacher, reason, now),
            )
            note_text = (
                f"⚠️ Marks removed by {teacher}: "
                f"{'[Theory] ' + task_name if task_type == 'theory' else subject + ' - ' + task_name}. "
                f"Reason: {reason}"
            )
            cursor.execute(
                """
                INSERT INTO learner_notes (username, note, flag, created_by, created_at)
                VALUES (?, ?, 'warning', ?, ?)
                """,
                (username, note_text, teacher, now),
            )

            if task_type == "practical":
                cursor.execute("DELETE FROM results WHERE username = ? AND subject = ? AND task = ?", (username, subject, task_name))
            else:
                cursor.execute(
                    """
                    DELETE FROM theory_answers WHERE submission_id IN
                        (SELECT id FROM theory_submissions WHERE username = ? AND test_id = ?)
                    """,
                    (username, test_id),
                )
                cursor.execute("DELETE FROM theory_submissions WHERE username = ? AND test_id = ?", (username, test_id))

        conn.commit()
        log_activity(
            teacher,
            f"removed {'all' if target == 'all' else target}'s results for "
            f"{'[Theory] ' + task_name if task_type == 'theory' else subject + ' - ' + task_name}. "
            f"Reason: {reason}",
        )
        conn.close()
        return redirect(url_for("group_results", group=group))

    @app.route("/export/results")
    def export_results():
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))
        role = get_user_role(username)
        if role not in ["teacher", "admin"]:
            return "Access denied", 403
        all_groups = get_groups(username) if role == "teacher" else get_groups()
        return render_template("export_results.html", all_groups=all_groups)

    @app.route("/export_results_multi", methods=["POST"])
    def export_results_multi():
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))
        if get_user_role(username) not in ["teacher", "admin"]:
            return "Access denied", 403

        selected_groups = request.form.getlist("groups")
        if not selected_groups:
            return "No groups selected", 400

        conn = get_db()
        cursor = conn.cursor()
        file_path = "multi_group_results_export.xlsx"

        with pd.ExcelWriter(file_path, engine="openpyxl") as writer:
            for group in selected_groups:
                cursor.execute(
                    """
                    SELECT username, full_name FROM users
                    WHERE group_name = ? AND role = 'student'
                    ORDER BY full_name
                    """,
                    (group,),
                )
                students_raw = cursor.fetchall()

                cursor.execute(
                    """
                    SELECT DISTINCT s.name as subject, t.name as task_name, t.id
                    FROM tasks t
                    JOIN subjects s ON t.subject_id = s.id
                    JOIN task_groups tg ON t.id = tg.task_id
                    WHERE tg.group_name = ? AND t.task_type = 'practical'
                    ORDER BY s.name, t.name
                    """,
                    (group,),
                )
                practical_tasks = cursor.fetchall()

                cursor.execute(
                    """
                    SELECT DISTINCT tt.id, tt.title, tt.subject
                    FROM theory_tests tt
                    LEFT JOIN theory_test_groups ttg ON tt.id = ttg.test_id
                    WHERE (ttg.group_name = ? OR ttg.group_name IS NULL)
                    ORDER BY tt.subject, tt.title
                    """,
                    (group,),
                )
                theory_tasks = cursor.fetchall()

                rows = []
                for student_username, full_name in students_raw:
                    row = {"Username": student_username, "Name": full_name or student_username, "Group": group}

                    for subject, task_name, task_id in practical_tasks:
                        cursor.execute(
                            """
                            SELECT MAX(score)
                            FROM results
                            WHERE username = ? AND subject = ? AND task = ?
                            """,
                            (student_username, subject, task_name),
                        )
                        result = cursor.fetchone()
                        col_name = f"{subject} - {task_name}"
                        row[col_name] = result[0] if result and result[0] is not None else ""

                    for test_id, title, subject in theory_tasks:
                        cursor.execute(
                            """
                            SELECT MAX(percentage)
                            FROM theory_submissions
                            WHERE username = ? AND test_id = ?
                            """,
                            (student_username, test_id),
                        )
                        result = cursor.fetchone()
                        col_name = f"[Theory] {title}"
                        row[col_name] = result[0] if result and result[0] is not None else ""

                    all_scores = []
                    for subject, task_name, task_id in practical_tasks:
                        cursor.execute(
                            """
                            SELECT MAX(score)
                            FROM results
                            WHERE username = ? AND subject = ? AND task = ?
                            """,
                            (student_username, subject, task_name),
                        )
                        result = cursor.fetchone()
                        if result and result[0] is not None:
                            all_scores.append(result[0])

                    for test_id, title, subject in theory_tasks:
                        cursor.execute(
                            """
                            SELECT MAX(percentage)
                            FROM theory_submissions
                            WHERE username = ? AND test_id = ?
                            """,
                            (student_username, test_id),
                        )
                        result = cursor.fetchone()
                        if result and result[0] is not None:
                            all_scores.append(result[0])

                    row["Overall Average"] = round(sum(all_scores) / len(all_scores), 1) if all_scores else ""
                    rows.append(row)

                df = pd.DataFrame(rows)
                sheet_name = group.replace("/", "_").replace("\\", "_")[:31]
                df.to_excel(writer, sheet_name=sheet_name, index=False)

        log_activity(username, "exported results by group")
        conn.close()
        response = send_file(file_path, as_attachment=True)
        response.headers["HX-Redirect"] = url_for("teacher_dashboard")
        return response

    @app.route("/risk_learners")
    def risk_learners():
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))

        role = get_user_role(username)
        if role not in ["teacher", "admin"]:
            return "Access denied", 403

        selected_group = request.args.get("group")
        conn = get_db()
        cursor = conn.cursor()
        selected_teacher = (request.args.get("teacher") or "").strip() or None
        teacher_options = []
        class_scopes = []

        if role == "teacher":
            groups = get_groups(username)
            selected_teacher = username
        else:
            cursor.execute(
                """
                SELECT DISTINCT teacher_username
                FROM users
                WHERE role = 'student'
                  AND teacher_username IS NOT NULL
                  AND teacher_username != ''
                ORDER BY teacher_username
                """
            )
            teacher_options = [row[0] for row in cursor.fetchall()]
            if selected_teacher and selected_teacher not in teacher_options:
                selected_teacher = None
            if selected_teacher:
                cursor.execute(
                    """
                    SELECT DISTINCT group_name
                    FROM users
                    WHERE role = 'student'
                      AND teacher_username = ?
                      AND group_name IS NOT NULL
                      AND group_name != ''
                    ORDER BY group_name
                    """,
                    (selected_teacher,),
                )
                groups = [row[0] for row in cursor.fetchall()]
            else:
                groups = []
                cursor.execute(
                    """
                    SELECT DISTINCT teacher_username, group_name
                    FROM users
                    WHERE role = 'student'
                      AND teacher_username IS NOT NULL
                      AND teacher_username != ''
                      AND group_name IS NOT NULL
                      AND group_name != ''
                    ORDER BY teacher_username, group_name
                    """
                )
                class_scopes = [
                    {"teacher_username": row[0], "group": row[1], "label": f"{row[1]} ({row[0]})"}
                    for row in cursor.fetchall()
                ]

        if selected_group and selected_group not in groups:
            selected_group = None

        if not selected_group:
            practical_avg_map = fetch_student_practical_averages(cursor, username if role == "teacher" else None)
            theory_avg_map = fetch_student_theory_averages(cursor, username if role == "teacher" else None)
            group_summaries = []
            if role == "admin" and not selected_teacher:
                summary_rows = []
                for scope in class_scopes:
                    scope_summary = build_attendance_group_summary(
                        cursor,
                        [scope["group"]],
                        teacher_username=scope["teacher_username"],
                        days=get_last_21_days(),
                    )
                    if scope_summary:
                        item = scope_summary[0]
                        item["teacher_username"] = scope["teacher_username"]
                        item["label"] = scope["label"]
                        summary_rows.append(item)
            else:
                summary_rows = build_attendance_group_summary(
                    cursor,
                    groups,
                    teacher_username=selected_teacher,
                    days=get_last_21_days(),
                )
                for item in summary_rows:
                    item["teacher_username"] = selected_teacher
                    item["label"] = item["group"] if role == "teacher" else f"{item['group']} ({selected_teacher})"

            for item in summary_rows:
                group_name = item["group"]
                teacher_scope = item.get("teacher_username")
                if teacher_scope:
                    cursor.execute(
                        """
                        SELECT username
                        FROM users
                        WHERE group_name = ? AND role = 'student' AND teacher_username = ?
                        """,
                        (group_name, teacher_scope),
                    )
                else:
                    cursor.execute(
                        """
                        SELECT username
                        FROM users
                        WHERE group_name = ? AND role = 'student'
                        """,
                        (group_name,),
                    )
                usernames = [row[0] for row in cursor.fetchall()]
                combined_scores = []
                for uname in usernames:
                    practical_avg = practical_avg_map.get(uname)
                    theory_avg = theory_avg_map.get(uname)
                    if practical_avg is not None and theory_avg is not None:
                        combined_scores.append(round((practical_avg + theory_avg) / 2, 1))
                    elif practical_avg is not None:
                        combined_scores.append(practical_avg)
                    elif theory_avg is not None:
                        combined_scores.append(theory_avg)
                avg_combined = round(sum(combined_scores) / len(combined_scores), 1) if combined_scores else 0
                risk_value = round((100 - item["attendance_pct"]) * 0.4 + (100 - avg_combined) * 0.4)
                group_summaries.append(
                    {
                        "group": group_name,
                        "label": item.get("label", group_name),
                        "teacher_username": teacher_scope,
                        "students": item["students"],
                        "attendance_pct": item["attendance_pct"],
                        "avg_combined": avg_combined,
                        "risk_score": risk_value,
                    }
                )
            conn.close()
            return render_template(
                "Riks_learners.html",
                groups=groups,
                teacher_options=teacher_options,
                selected_teacher=selected_teacher,
                selected_group=None,
                summary_cards=[],
                group_summaries=group_summaries,
            )

        if selected_teacher:
            cursor.execute(
                """
                SELECT username, full_name
                FROM users
                WHERE group_name = ? AND role = 'student' AND teacher_username = ?
                ORDER BY full_name
                """,
                (selected_group, selected_teacher),
            )
        else:
            cursor.execute(
                """
                SELECT username, full_name
                FROM users
                WHERE group_name = ? AND role = 'student'
                ORDER BY full_name
                """,
                (selected_group,),
            )
        students_raw = cursor.fetchall()

        days_21 = get_last_21_days()
        auto_exclude_empty_attendance_days(cursor, [selected_group], created_by=username, days=get_current_year_attendance_days())
        excluded_days = fetch_group_excluded_dates(cursor, [selected_group]).get(selected_group, set())
        filtered_days = [day for day in days_21 if day not in excluded_days]
        student_usernames = [student_username for student_username, _ in students_raw]
        login_times = fetch_first_login_times(cursor, student_usernames, filtered_days)
        overrides = fetch_attendance_override_statuses(cursor, student_usernames, filtered_days)
        practical_avg_map = fetch_student_practical_averages(cursor, selected_teacher)
        theory_avg_map = fetch_student_theory_averages(cursor, selected_teacher)
        late_cutoffs = fetch_group_late_thresholds(cursor, selected_group, filtered_days, teacher_username=selected_teacher)
        class_checked_dates = fetch_class_checked_dates(cursor, selected_group, teacher_username=selected_teacher)
        today = datetime.now().strftime("%Y-%m-%d")
        risk_students = []

        for student_username, full_name in students_raw:
            practical_avg = practical_avg_map.get(student_username)
            theory_avg = theory_avg_map.get(student_username)
            if practical_avg is not None and theory_avg is not None:
                avg_score = round((practical_avg + theory_avg) / 2, 1)
            else:
                avg_score = practical_avg if practical_avg is not None else theory_avg
            avg_score = avg_score if avg_score is not None else 0

            history = build_attendance_history(
                cursor,
                student_username,
                selected_group,
                filtered_days,
                login_map=login_times,
                override_map=overrides,
                late_cutoffs=late_cutoffs,
                class_checked_dates=class_checked_dates,
                excluded_dates=excluded_days,
            )
            attendance_pct = summarize_attendance_history(history)["attendance_pct"]

            cursor.execute(
                """
                SELECT COUNT(DISTINCT t.id)
                FROM task_groups tg
                JOIN tasks t ON t.id = tg.task_id
                WHERE tg.group_name = ?
                  AND t.assign_date <= ?
                """,
                (selected_group, today),
            )
            total_assigned = cursor.fetchone()[0] or 0

            cursor.execute(
                """
                SELECT COUNT(DISTINCT t.id)
                FROM task_groups tg
                JOIN tasks t ON t.id = tg.task_id
                JOIN subjects s ON s.id = t.subject_id
                WHERE tg.group_name = ?
                  AND t.assign_date <= ?
                  AND NOT EXISTS (
                      SELECT 1 FROM results r
                      WHERE r.username = ?
                        AND r.subject = s.name
                        AND r.task = t.name
                  )
                """,
                (selected_group, today, student_username),
            )
            missing_practical = cursor.fetchone()[0] or 0

            cursor.execute(
                """
                SELECT COUNT(DISTINCT tt.id)
                FROM theory_tests tt
                LEFT JOIN theory_test_groups ttg ON tt.id = ttg.test_id
                WHERE (ttg.group_name = ? OR ttg.group_name IS NULL)
                  AND tt.assign_date <= ?
                """,
                (selected_group, today),
            )
            total_theory = cursor.fetchone()[0] or 0

            cursor.execute(
                """
                SELECT COUNT(DISTINCT tt.id)
                FROM theory_tests tt
                LEFT JOIN theory_test_groups ttg ON tt.id = ttg.test_id
                WHERE (ttg.group_name = ? OR ttg.group_name IS NULL)
                  AND tt.assign_date <= ?
                  AND NOT EXISTS (
                      SELECT 1 FROM theory_submissions ts
                      WHERE ts.username = ?
                        AND ts.test_id = tt.id
                  )
                """,
                (selected_group, today, student_username),
            )
            missing_theory = cursor.fetchone()[0] or 0

            total_tasks = total_assigned + total_theory
            missing_pct = round((missing_practical + missing_theory) / total_tasks * 100) if total_tasks else 0
            risk_score = round((100 - attendance_pct) * 0.4 + (100 - avg_score) * 0.4 + missing_pct * 0.2)
            if risk_score <= 40:
                status = "Safe"
            elif risk_score <= 70:
                status = "At Risk"
            else:
                status = "High Risk"

            reasons = []
            if attendance_pct < 60:
                reasons.append(f"A {attendance_pct}%")
            if avg_score < 40:
                reasons.append(f"AVG{avg_score}%")
            if missing_pct > 70:
                reasons.append(f"Missing {missing_pct}%")
            if not reasons:
                reasons.append("balanced risk factors")

            risk_students.append(
                {
                    "username": student_username,
                    "name": full_name or student_username,
                    "group": selected_group,
                    "attendance_pct": attendance_pct,
                    "avg_score": avg_score,
                    "missing_pct": missing_pct,
                    "score": risk_score,
                    "status": status,
                    "reason": " + ".join(reasons),
                }
            )

        safe_count = sum(1 for student in risk_students if student["status"] == "Safe")
        at_risk_count = sum(1 for student in risk_students if student["status"] == "At Risk")
        high_risk_count = sum(1 for student in risk_students if student["status"] == "High Risk")
        avg_attendance = round(sum(student["attendance_pct"] for student in risk_students) / len(risk_students), 1) if risk_students else 0
        avg_combined = round(sum(student["avg_score"] for student in risk_students) / len(risk_students), 1) if risk_students else 0
        summary_cards = [
            {"label": "Safe", "value": safe_count, "tone": "ok"},
            {"label": "At Risk", "value": at_risk_count, "tone": "mid"},
            {"label": "High Risk", "value": high_risk_count, "tone": "risk"},
            {"label": "Avg Attendance", "value": f"{avg_attendance}%", "tone": "info"},
            {"label": "Avg Combined", "value": f"{avg_combined}%", "tone": "info"},
        ]

        conn.commit()
        conn.close()
        return render_template(
            "Riks_learners.html",
            groups=groups,
            teacher_options=teacher_options,
            selected_teacher=selected_teacher,
            selected_group=selected_group,
            risk_students=risk_students,
            summary_cards=summary_cards,
            group_summaries=[],
        )

    @app.route("/group_results")
    def group_results():
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))

        role = get_user_role(username)
        if role not in ["teacher", "admin"]:
            return "Access denied", 403

        conn = get_db()
        cursor = conn.cursor()
        selected_group = request.args.get("group")
        selected_teacher = (request.args.get("teacher") or "").strip() or None
        teacher_options = []
        class_scopes = []

        if role == "teacher":
            groups = get_groups(username)
            selected_teacher = username
        else:
            cursor.execute(
                """
                SELECT DISTINCT teacher_username
                FROM users
                WHERE role = 'student'
                  AND teacher_username IS NOT NULL
                  AND teacher_username != ''
                ORDER BY teacher_username
                """
            )
            teacher_options = [row[0] for row in cursor.fetchall()]
            if selected_teacher and selected_teacher not in teacher_options:
                selected_teacher = None
            if selected_teacher:
                cursor.execute(
                    """
                    SELECT DISTINCT group_name
                    FROM users
                    WHERE role = 'student'
                      AND teacher_username = ?
                      AND group_name IS NOT NULL
                      AND group_name != ''
                    ORDER BY group_name
                    """,
                    (selected_teacher,),
                )
                groups = [row[0] for row in cursor.fetchall()]
            else:
                groups = []
                cursor.execute(
                    """
                    SELECT DISTINCT teacher_username, group_name
                    FROM users
                    WHERE role = 'student'
                      AND teacher_username IS NOT NULL
                      AND teacher_username != ''
                      AND group_name IS NOT NULL
                      AND group_name != ''
                    ORDER BY teacher_username, group_name
                    """
                )
                class_scopes = [
                    {"teacher_username": row[0], "group": row[1], "label": f"{row[1]} ({row[0]})"}
                    for row in cursor.fetchall()
                ]

        if selected_group and selected_group not in groups:
            selected_group = None

        if not selected_group:
            result_summaries = []
            if role == "admin" and not selected_teacher:
                for scope in class_scopes:
                    cursor.execute(
                        """
                        SELECT username
                        FROM users
                        WHERE group_name = ? AND role = 'student' AND teacher_username = ?
                        """,
                        (scope["group"], scope["teacher_username"]),
                    )
                    usernames = [row[0] for row in cursor.fetchall()]
                    student_count = len(usernames)
                    practical_avg_map = fetch_student_practical_averages(cursor, scope["teacher_username"])
                    theory_avg_map = fetch_student_theory_averages(cursor, scope["teacher_username"])
                    practical_scores = [practical_avg_map.get(uname) for uname in usernames if practical_avg_map.get(uname) is not None]
                    theory_scores = [theory_avg_map.get(uname) for uname in usernames if theory_avg_map.get(uname) is not None]
                    practical_avg = round(sum(practical_scores) / len(practical_scores), 1) if practical_scores else None
                    theory_avg = round(sum(theory_scores) / len(theory_scores), 1) if theory_scores else None
                    if practical_avg is not None and theory_avg is not None:
                        combined_avg = round((practical_avg + theory_avg) / 2, 1)
                    else:
                        combined_avg = practical_avg if practical_avg is not None else theory_avg
                    result_summaries.append(
                        {
                            "group": scope["group"],
                            "label": scope["label"],
                            "teacher_username": scope["teacher_username"],
                            "students": student_count,
                            "practical_avg": practical_avg,
                            "theory_avg": theory_avg,
                            "combined_avg": combined_avg or 0,
                        }
                    )
            else:
                practical_group_avg_map = fetch_group_practical_averages(cursor, groups, teacher_username=selected_teacher)
                theory_group_avg_map = fetch_group_theory_averages(cursor, groups, teacher_username=selected_teacher)
                for group_name in groups:
                    cursor.execute(
                        """
                        SELECT COUNT(*)
                        FROM users
                        WHERE group_name = ? AND role = 'student' AND teacher_username = ?
                        """,
                        (group_name, selected_teacher),
                    )
                    student_count = cursor.fetchone()[0] or 0
                    practical_avg = practical_group_avg_map.get(group_name)
                    theory_avg = theory_group_avg_map.get(group_name)
                    if practical_avg is not None and theory_avg is not None:
                        combined_avg = round((practical_avg + theory_avg) / 2, 1)
                    else:
                        combined_avg = practical_avg if practical_avg is not None else theory_avg
                    result_summaries.append(
                        {
                            "group": group_name,
                            "label": group_name if role == "teacher" else f"{group_name} ({selected_teacher})",
                            "teacher_username": selected_teacher,
                            "students": student_count,
                            "practical_avg": practical_avg,
                            "theory_avg": theory_avg,
                            "combined_avg": combined_avg or 0,
                        }
                    )
            conn.close()
            return render_template(
                "group_results.html",
                groups=groups,
                teacher_options=teacher_options,
                selected_teacher=selected_teacher,
                selected_group=None,
                result_summaries=result_summaries,
            )

        if selected_teacher:
            cursor.execute(
                """
                SELECT username, full_name FROM users
                WHERE group_name = ? AND role = 'student' AND teacher_username = ?
                ORDER BY full_name
                """,
                (selected_group, selected_teacher),
            )
        else:
            cursor.execute(
                """
                SELECT username, full_name FROM users
                WHERE group_name = ? AND role = 'student'
                ORDER BY full_name
                """,
                (selected_group,),
            )
        students_raw = cursor.fetchall()

        cursor.execute(
            """
            SELECT DISTINCT s.name as subject, t.name as task_name, t.id
            FROM tasks t
            JOIN subjects s ON t.subject_id = s.id
            JOIN task_groups tg ON t.id = tg.task_id
            WHERE tg.group_name = ? AND t.task_type = 'practical'
            ORDER BY s.name, t.name
            """,
            (selected_group,),
        )
        practical_tasks = [{"subject": row[0], "name": row[1], "id": row[2]} for row in cursor.fetchall()]

        cursor.execute(
            """
            SELECT DISTINCT tt.id, tt.title, tt.subject
            FROM theory_tests tt
            LEFT JOIN theory_test_groups ttg ON tt.id = ttg.test_id
            WHERE (ttg.group_name = ? OR ttg.group_name IS NULL)
            ORDER BY tt.subject, tt.title
            """,
            (selected_group,),
        )
        theory_tasks = [{"test_id": row[0], "title": row[1], "subject": row[2]} for row in cursor.fetchall()]

        students = []
        total_averages = []
        for username, full_name in students_raw:
            student = {
                "username": username,
                "full_name": full_name,
                "practical_results": {},
                "theory_results": {},
                "overall_avg": None,
            }

            for task in practical_tasks:
                cursor.execute(
                    """
                    SELECT score, timestamp
                    FROM results
                    WHERE username = ? AND subject = ? AND task = ?
                    ORDER BY timestamp DESC
                    """,
                    (username, task["subject"], task["name"]),
                )
                scores = cursor.fetchall()
                if scores:
                    all_scores = [s[0] for s in scores]
                    best_score = max(all_scores)
                    student["practical_results"][(task["subject"], task["name"])] = {
                        "best_score": best_score,
                        "attempts": len(scores),
                        "all_scores": all_scores,
                    }

            for task in theory_tasks:
                cursor.execute(
                    """
                    SELECT percentage, submitted_at
                    FROM theory_submissions
                    WHERE username = ? AND test_id = ?
                    ORDER BY submitted_at DESC
                    """,
                    (username, task["test_id"]),
                )
                scores = cursor.fetchall()
                if scores:
                    all_scores = [s[0] for s in scores]
                    best_score = max(all_scores)
                    student["theory_results"][task["test_id"]] = {
                        "best_score": best_score,
                        "attempts": len(scores),
                        "all_scores": all_scores,
                    }

            all_best_scores = []
            all_best_scores.extend([r["best_score"] for r in student["practical_results"].values()])
            all_best_scores.extend([r["best_score"] for r in student["theory_results"].values()])
            if all_best_scores:
                student["overall_avg"] = round(sum(all_best_scores) / len(all_best_scores), 1)
                total_averages.append(student["overall_avg"])

            students.append(student)

        group_average = round(sum(total_averages) / len(total_averages), 1) if total_averages else 0
        conn.close()
        return render_template(
            "group_results.html",
            groups=groups,
            teacher_options=teacher_options,
            selected_teacher=selected_teacher,
            selected_group=selected_group,
            students=students,
            practical_tasks=practical_tasks,
            theory_tasks=theory_tasks,
            group_average=group_average,
            result_summaries=[],
        )
