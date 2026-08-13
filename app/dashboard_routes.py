from collections import defaultdict
from datetime import datetime, timedelta

from flask import flash, redirect, render_template, request, session, url_for

from app.database import get_db, get_grades, get_groups, get_user_role
from app.helper_attendance import (
    auto_exclude_empty_attendance_days,
    build_attendance_history,
    build_attendance_months,
    fetch_class_checked_dates,
    fetch_attendance_override_statuses,
    fetch_first_login_times,
    fetch_group_excluded_dates,
    fetch_group_late_thresholds,
    get_active_term_range,
    get_all_term_days,
    get_current_year_attendance_days,
    get_last_21_days,
    get_low_attendance_learners_filtered as get_low_attendance_learners,
    summarize_attendance_history,
)
from app.helper_common import parse_module_names
from app.helper_communication import (
    get_student_message_threads,
    get_student_unread_message_count,
    get_teacher_selected_quick_actions,
    student_has_fresh_teacher_reply,
)
from app.helper_results import (
    fetch_group_practical_averages,
    fetch_group_theory_averages,
    fetch_student_practical_averages,
    fetch_student_theory_averages,
    fetch_theory_module_weaknesses,
)
from app.helper_theory import clone_bank_question_to_test, merge_bank_match_rows_into_test
from app.runtime import TIMEOUT, active_users, lock, update_active_user
from app.session_routes import student_needs_registration


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
        if student_needs_registration(username):
            return redirect(url_for("complete_registration"))

        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("SELECT full_name, group_name, teacher_username FROM users WHERE username = ?", (username,))
        user_row = cursor.fetchone()
        display_name = user_row[0] if user_row and user_row[0] else username
        user_group = user_row[1] if user_row else None
        learner_teacher = user_row[2] if user_row else None

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

        results_map = {(r[0], r[1]): {"score": r[2], "feedback": r[3], "timestamp": r[4]} for r in recent_results}
        cursor.execute(
            """
            SELECT subject, task, MAX(score) as score, feedback, MAX(timestamp) as timestamp
            FROM results
            WHERE username = ?
            GROUP BY subject, task
            """,
            (username,),
        )
        results_map = {(r[0], r[1]): {"score": r[2], "feedback": r[3], "timestamp": r[4]} for r in cursor.fetchall()}

        task_rows = []
        for subject, task_name in assigned_practical_tasks:
            row = results_map.get((subject, task_name))
            task_rows.append(
                {
                    "subject": subject,
                    "task": task_name,
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
        learning_progress = []
        theory_time_seconds = 0
        progression_missing_items = []

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
                progression_missing_items.append({"type": "Lesson" if is_lesson else "Test", "title": title})

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

        practical_progression_missing = [{"type": "Practical", "title": f"{row['subject']} - {row['task']}"} for row in task_rows if row["type"] == "practical" and row["score"] is None]
        progression_missing_items = practical_progression_missing + progression_missing_items
        learning_summary = {
            "practical_total": practical_total,
            "practical_done": practical_done,
            "theory_total": theory_total,
            "theory_done": theory_done,
            "theory_in_progress": theory_in_progress,
            "missing_total": len(progression_missing_items),
            "theory_time_seconds": theory_time_seconds,
            "overall_completion": round(((practical_done + theory_done) / max(1, practical_total + theory_total)) * 100, 1),
        }

        attendance_year = datetime.now().year
        attendance_days = get_current_year_attendance_days()
        auto_exclude_empty_attendance_days(cursor, [user_group], created_by=username, days=attendance_days)
        cursor.execute("SELECT date FROM excluded_dates WHERE group_name IS NULL OR group_name = ?", (user_group,))
        excluded_dates = {row[0] for row in cursor.fetchall()}
        login_map = fetch_first_login_times(cursor, [username], attendance_days)
        override_map = fetch_attendance_override_statuses(cursor, [username], attendance_days)
        late_cutoffs = fetch_group_late_thresholds(cursor, user_group, attendance_days, teacher_username=learner_teacher) if user_group else {}
        class_checked_dates = fetch_class_checked_dates(cursor, user_group, teacher_username=learner_teacher, exclude_username=username)
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
        theory_module_weaknesses = fetch_theory_module_weaknesses(cursor, username=username, limit=5)

        cursor.execute(
            """
            SELECT subject, task, feedback, timestamp
            FROM results WHERE username = ? AND feedback IS NOT NULL AND feedback != ''
            ORDER BY timestamp DESC LIMIT 3
            """,
            (username,),
        )
        message_threads = get_student_message_threads(username)
        teacher_feedback_messages = []
        for thread in message_threads:
            topic_label = (thread.get("subject_line") or thread.get("topic") or "Message").replace("_", " ").title()
            for message in thread.get("messages", []):
                if message.get("sender_role") not in ["teacher", "admin"]:
                    continue
                teacher_feedback_messages.append(
                    {
                        "kind": "message",
                        "title": f"Message — {topic_label}",
                        "body": message.get("message") or "",
                        "timestamp": message.get("created_at") or "",
                        "sender": message.get("sender_username") or "Teacher",
                    }
                )
        result_feedback_items = [
            {
                "kind": "feedback",
                "title": f"{subj} — {task}",
                "body": feedback,
                "timestamp": ts or "",
                "sender": "Feedback",
            }
            for subj, task, feedback, ts in cursor.fetchall()
        ]
        recent_feedback = sorted(
            result_feedback_items + teacher_feedback_messages,
            key=lambda item: item["timestamp"] or "",
            reverse=True,
        )[:6]
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
            task_rows=task_rows,
            theory_results=theory_results,
            learning_summary=learning_summary,
            learning_progress=learning_progress,
            missing_items=progression_missing_items[:12],
            weaknesses=weaknesses,
            theory_module_weaknesses=theory_module_weaknesses,
            recent_feedback=recent_feedback,
            message_threads=message_threads,
            unread_teacher_messages=unread_teacher_messages,
            auto_open_chat=auto_open_chat,
        )

    @app.route("/my_weaknesses")
    def my_weaknesses():
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))

        role = get_user_role(username)
        if role in ["teacher", "admin"]:
            return redirect(url_for("teacher_dashboard"))
        if student_needs_registration(username):
            return redirect(url_for("complete_registration"))

        conn = get_db()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT full_name FROM users WHERE username = ?",
            (username,),
        )
        user_row = cursor.fetchone()
        display_name = user_row[0] if user_row and user_row[0] else username

        cursor.execute(
            """
            SELECT skill, count
            FROM weaknesses
            WHERE username = ?
            ORDER BY count DESC, skill ASC
            """,
            (username,),
        )
        weaknesses = cursor.fetchall()
        theory_module_weaknesses = fetch_theory_module_weaknesses(cursor, username=username, limit=100)

        cursor.execute(
            """
            SELECT subject, task, feedback, timestamp
            FROM results
            WHERE username = ? AND feedback IS NOT NULL AND feedback != ''
            ORDER BY timestamp DESC LIMIT 10
            """,
            (username,),
        )
        recent_feedback = [
            {
                "kind": "feedback",
                "title": f"{subj} — {task}",
                "body": feedback,
                "timestamp": ts or "",
                "sender": "Feedback",
            }
            for subj, task, feedback, ts in cursor.fetchall()
        ]

        conn.close()
        return render_template(
            "my_weaknesses.html",
            username=username,
            display_name=display_name,
            weaknesses=weaknesses,
            theory_module_weaknesses=theory_module_weaknesses,
            recent_feedback=recent_feedback,
        )

    @app.route("/my_results")
    def my_results():
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))

        role = get_user_role(username)
        if role in ["teacher", "admin"]:
            return redirect(url_for("teacher_dashboard"))
        if student_needs_registration(username):
            return redirect(url_for("complete_registration"))

        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("SELECT full_name, group_name FROM users WHERE username = ?", (username,))
        user_row = cursor.fetchone()
        display_name = user_row[0] if user_row and user_row[0] else username
        user_group = user_row[1] if user_row else None

        cursor.execute(
            """
            SELECT subject, task, MAX(score) as score, feedback, MAX(timestamp) as timestamp
            FROM results
            WHERE username = ?
            GROUP BY subject, task
            ORDER BY timestamp DESC
            """,
            (username,),
        )
        practical_results = cursor.fetchall()

        cursor.execute(
            """
            SELECT subject, ROUND(AVG(best_score),1)
            FROM (SELECT subject, task, MAX(score) as best_score FROM results WHERE username = ? GROUP BY subject, task)
            GROUP BY subject
            ORDER BY subject
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
        practical_avg_row = cursor.fetchone()
        practical_avg = practical_avg_row[0] if practical_avg_row and practical_avg_row[0] is not None else 0

        cursor.execute(
            """
            SELECT tt.subject, ROUND(AVG(best_pct),1)
            FROM (SELECT test_id, MAX(percentage) as best_pct FROM theory_submissions WHERE username = ? GROUP BY test_id) b
            JOIN theory_tests tt ON b.test_id = tt.id
            WHERE tt.subject IS NOT NULL AND tt.subject != ''
            GROUP BY tt.subject
            ORDER BY tt.subject
            """,
            (username,),
        )
        theory_subject_avgs = cursor.fetchall()

        cursor.execute(
            """
            SELECT ROUND(AVG(best_pct),1)
            FROM (SELECT test_id, MAX(percentage) as best_pct FROM theory_submissions WHERE username = ? GROUP BY test_id)
            """,
            (username,),
        )
        theory_avg_row = cursor.fetchone()
        theory_avg = theory_avg_row[0] if theory_avg_row and theory_avg_row[0] is not None else None

        if practical_avg and theory_avg:
            overall_avg = round((practical_avg + theory_avg) / 2, 1)
        else:
            overall_avg = practical_avg or theory_avg or 0

        cursor.execute(
            """
            SELECT tt.title, ts.score, ts.total, ts.percentage, ts.submitted_at,
                   COALESCE(ts.time_spent_seconds, 0), COALESCE(ts.submission_type, 'test'),
                   COALESCE(tt.subject, 'Theory')
            FROM theory_submissions ts
            JOIN theory_tests tt ON ts.test_id = tt.id
            JOIN (
                SELECT test_id, MAX(submitted_at) as latest
                FROM theory_submissions
                WHERE username = ?
                GROUP BY test_id
            ) latest ON latest.test_id = ts.test_id AND latest.latest = ts.submitted_at
            WHERE ts.username = ?
            ORDER BY ts.submitted_at DESC
            """,
            (username, username),
        )
        theory_results = cursor.fetchall()

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
            SELECT DISTINCT tt.id, tt.title, COALESCE(tt.subject, 'Theory')
            FROM theory_tests tt
            LEFT JOIN theory_test_groups ttg ON tt.id = ttg.test_id
            WHERE (ttg.group_name = ? OR ttg.group_name IS NULL)
            ORDER BY tt.subject, tt.title
            """,
            (user_group,),
        )
        assigned_theory_tests = cursor.fetchall()

        practical_map = {(row[0], row[1]): row for row in practical_results}
        practical_status_rows = []
        for subject, task_name in assigned_practical_tasks:
            result = practical_map.get((subject, task_name))
            practical_status_rows.append(
                {
                    "subject": subject,
                    "title": task_name,
                    "score": result[2] if result else None,
                    "feedback": result[3] if result else "",
                    "timestamp": result[4] if result else None,
                    "status": "Submitted" if result else "Not submitted",
                }
            )

        theory_latest_map = {}
        for title, score, total, percentage, submitted_at, time_spent_seconds, submission_type, subject in theory_results:
            theory_latest_map[title] = {
                "score": score,
                "total": total,
                "percentage": percentage,
                "submitted_at": submitted_at,
                "time_spent_seconds": time_spent_seconds,
                "submission_type": submission_type,
                "subject": subject,
            }

        theory_status_rows = []
        for test_id, title, subject in assigned_theory_tests:
            result = theory_latest_map.get(title)
            theory_status_rows.append(
                {
                    "subject": subject,
                    "title": title,
                    "score": result["percentage"] if result else None,
                    "submitted_at": result["submitted_at"] if result else None,
                    "submission_type": result["submission_type"] if result else "test",
                    "status": "Submitted" if result else "Not submitted",
                }
            )

        conn.close()
        return render_template(
            "my_results.html",
            username=username,
            display_name=display_name,
            overall_avg=overall_avg,
            practical_avg=practical_avg,
            theory_avg=theory_avg,
            subject_avgs=subject_avgs,
            theory_subject_avgs=theory_subject_avgs,
            practical_results=practical_results,
            theory_results=theory_results,
            practical_status_rows=practical_status_rows,
            theory_status_rows=theory_status_rows,
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
        viewer_role = get_user_role(admin_user)
        if viewer_role not in ["teacher", "admin"]:
            return "Access denied", 403

        conn = get_db()
        cursor = conn.cursor()

        requested_teacher = (request.args.get("teacher") or "").strip() or None
        scoped_teacher = admin_user if viewer_role == "teacher" else requested_teacher
        user_filter_clause = " AND teacher_username = ?" if scoped_teacher else ""
        user_filter_params = [scoped_teacher] if scoped_teacher else []

        cursor.execute(
            f"""
            SELECT username, full_name, group_name FROM users
            WHERE group_name = ? AND role = 'student'{user_filter_clause} LIMIT 1
            """,
            [group_name, *user_filter_params],
        )
        rep = cursor.fetchone()

        cursor.execute(
            f"SELECT COUNT(*) FROM users WHERE group_name = ? AND role = 'student'{user_filter_clause}",
            [group_name, *user_filter_params],
        )
        student_count = cursor.fetchone()[0]

        cursor.execute(
            f"""
            SELECT username, full_name FROM users
            WHERE group_name = ? AND role = 'student'{user_filter_clause} ORDER BY full_name
            """,
            [group_name, *user_filter_params],
        )
        students = cursor.fetchall()

        practical_group_avg = fetch_group_practical_averages(cursor, [group_name], teacher_username=scoped_teacher).get(group_name)
        theory_group_avg = fetch_group_theory_averages(cursor, [group_name], teacher_username=scoped_teacher).get(group_name)
        if practical_group_avg is not None and theory_group_avg is not None:
            overall_avg = round((practical_group_avg + theory_group_avg) / 2, 1)
        else:
            overall_avg = practical_group_avg if practical_group_avg is not None else (theory_group_avg or 0)

        cursor.execute(
            f"""
            SELECT u.full_name, r.subject, r.task, r.score, r.timestamp
            FROM results r
            JOIN users u ON r.username = u.username
            WHERE u.group_name = ?{user_filter_clause}
            ORDER BY r.timestamp DESC LIMIT 10
            """,
            [group_name, *user_filter_params],
        )
        recent_results = cursor.fetchall()

        attendance_year = datetime.now().year
        days = get_current_year_attendance_days()
        auto_exclude_empty_attendance_days(cursor, [group_name], created_by=admin_user, days=days)
        excluded = fetch_group_excluded_dates(cursor, [group_name]).get(group_name, set())
        student_usernames = [student_username for student_username, _full_name in students]
        login_times = fetch_first_login_times(cursor, student_usernames, days)
        overrides = fetch_attendance_override_statuses(cursor, student_usernames, days)
        late_cutoffs = fetch_group_late_thresholds(cursor, group_name, days, teacher_username=scoped_teacher)
        class_checked_dates = fetch_class_checked_dates(cursor, group_name, teacher_username=scoped_teacher)

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
            f"""
            SELECT s.name, t.name, t.assign_date,
                   COUNT(DISTINCT u.username) as missing_count
            FROM tasks t
            JOIN subjects s ON s.id = t.subject_id
            JOIN task_groups tg ON tg.task_id = t.id
            JOIN users u ON u.group_name = tg.group_name AND u.role = 'student'{user_filter_clause}
            WHERE tg.group_name = ? AND t.assign_date <= ? AND t.task_type = 'practical'
              AND NOT EXISTS (
                  SELECT 1 FROM results r
                  WHERE r.username = u.username AND r.subject = s.name AND r.task = t.name
              )
            GROUP BY t.id
            ORDER BY t.assign_date
            """,
            [*user_filter_params, group_name, today],
        )
        missing_tasks = cursor.fetchall()

        cursor.execute(
            f"""
            SELECT w.skill, SUM(w.count) as total
            FROM weaknesses w
            JOIN users u ON w.username = u.username
            WHERE u.group_name = ?{user_filter_clause}
            GROUP BY w.skill ORDER BY total DESC LIMIT 5
            """,
            [group_name, *user_filter_params],
        )
        weaknesses = cursor.fetchall()
        theory_module_weaknesses = fetch_theory_module_weaknesses(
            cursor,
            group_name=group_name,
            teacher_username=scoped_teacher,
            limit=10,
        )

        cursor.execute(
            f"""
            SELECT t.title, ROUND(AVG(s.percentage), 1), COUNT(DISTINCT s.username)
            FROM theory_submissions s
            JOIN theory_tests t ON s.test_id = t.id
            JOIN users u ON s.username = u.username
            WHERE u.group_name = ?{user_filter_clause}
            GROUP BY t.id ORDER BY s.submitted_at DESC LIMIT 5
            """,
            [group_name, *user_filter_params],
        )
        theory_avgs = cursor.fetchall()

        if scoped_teacher:
            cursor.execute(
                """
                SELECT note_date, module_name, progress_text, note_text, module_finished, generated_test_id, created_at
                FROM class_module_notes
                WHERE group_name = ? AND teacher_username = ?
                ORDER BY note_date DESC, created_at DESC, id DESC
                """,
                (group_name, scoped_teacher),
            )
        else:
            cursor.execute(
                """
                SELECT note_date, module_name, progress_text, note_text, module_finished, generated_test_id, created_at
                FROM class_module_notes
                WHERE group_name = ? AND teacher_username IS NULL
                ORDER BY note_date DESC, created_at DESC, id DESC
                """,
                (group_name,),
            )
        class_module_notes = cursor.fetchall()

        practical_avg_map = fetch_student_practical_averages(cursor, scoped_teacher)
        theory_avg_map = fetch_student_theory_averages(cursor, scoped_teacher)
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
            selected_teacher=scoped_teacher,
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
            class_module_notes=class_module_notes,
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
        today_date = datetime.now().date()
        quick_actions, available_quick_actions = get_teacher_selected_quick_actions(username)
        selected_teacher = (request.args.get("teacher") or "").strip() or None
        selected_grade = ""
        selected_date_param = (request.args.get("selected_date") or "").strip()
        month_param = (request.args.get("month") or "").strip()
        teacher_options = []
        broad_student_rows = []

        if role == "teacher":
            selected_teacher = username
            cursor.execute(
                """
                SELECT username, full_name, group_name, teacher_username, COALESCE(grade, '')
                FROM users
                WHERE role = 'student' AND teacher_username = ?
                ORDER BY group_name, full_name, username
                """,
                (username,),
            )
            broad_student_rows = cursor.fetchall()
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
            cursor.execute(
                """
                SELECT username, full_name, group_name, teacher_username, COALESCE(grade, '')
                FROM users
                WHERE role = 'student'
                """
                + (" AND teacher_username = ?" if selected_teacher else "")
                + """
                ORDER BY teacher_username, group_name, full_name, username
                """,
                tuple([selected_teacher] if selected_teacher else []),
            )
            broad_student_rows = cursor.fetchall()

        student_rows = list(broad_student_rows)

        total_students = len(student_rows)
        student_usernames = [row[0] for row in student_rows]
        teacher_scope = selected_teacher if role == "admin" else username
        group_filter_clause = "AND u.teacher_username = ?" if teacher_scope else ""
        group_filter_params = [teacher_scope] if teacher_scope else []
        grade_filter_clause = ""
        grade_filter_params = []

        group_options = []
        if role == "admin" and not selected_teacher:
            seen_scopes = set()
            for _uname, _full_name, group_name, teacher_name, _grade in broad_student_rows:
                if not group_name or not teacher_name:
                    continue
                scope_key = (teacher_name, group_name)
                if scope_key in seen_scopes:
                    continue
                seen_scopes.add(scope_key)
                group_options.append(
                    {
                        "group": group_name,
                        "teacher_username": teacher_name,
                        "label": f"{group_name} ({teacher_name})",
                        "href": f"/view_as_student/{group_name}?teacher={teacher_name}",
                    }
                )
            groups = [item["group"] for item in group_options]
        else:
            groups = sorted({row[2] for row in broad_student_rows if row[2]})
            group_options = [
                {
                    "group": group_name,
                    "teacher_username": teacher_scope,
                    "label": group_name,
                    "href": f"/view_as_student/{group_name}" + (f"?teacher={teacher_scope}" if role == "admin" and teacher_scope else ""),
                }
                for group_name in groups
            ]
        grade_groups = list(groups)
        grade_group_options = list(group_options)
        prev_grade = None
        next_grade = None

        dashboard_scopes = [
            {
                "group": item["group"],
                "teacher_username": item["teacher_username"],
                "label": item["label"],
                "href": item["href"],
            }
            for item in group_options
        ]

        try:
            if month_param:
                current_month = datetime.strptime(month_param + "-01", "%Y-%m-%d").date()
            else:
                current_month = today_date.replace(day=1)
        except ValueError:
            current_month = today_date.replace(day=1)
        if current_month > today_date.replace(day=1):
            current_month = today_date.replace(day=1)
        month_start = current_month.replace(day=1)
        next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
        month_end = min(next_month - timedelta(days=1), today_date)
        prev_month_value = ((month_start - timedelta(days=1)).replace(day=1)).strftime("%Y-%m")
        next_month_value = next_month.strftime("%Y-%m") if next_month <= today_date.replace(day=1) else None

        term_days = sorted(day for day in get_all_term_days() if month_start.isoformat() <= day <= month_end.isoformat())
        if term_days:
            calendar_days = term_days
        else:
            calendar_days = []
            current_day = month_start
            while current_day <= month_end:
                if current_day.weekday() < 5:
                    calendar_days.append(current_day.isoformat())
                current_day += timedelta(days=1)

        if calendar_days:
            if selected_date_param in calendar_days:
                selected_date = selected_date_param
            elif today in calendar_days:
                selected_date = today
            else:
                selected_date = calendar_days[-1]
        else:
            selected_date = month_start.isoformat()

        month_present_map = {}
        month_note_map = {}
        for scope in dashboard_scopes:
            group_name = scope["group"]
            scope_teacher = scope["teacher_username"]
            params = [group_name, month_start.isoformat(), month_end.isoformat()]
            teacher_clause = ""
            if scope_teacher:
                teacher_clause = " AND u.teacher_username = ?"
                params.append(scope_teacher)
            cursor.execute(
                f"""
                SELECT DISTINCT lh.date
                FROM login_history lh
                JOIN users u ON u.username = lh.username
                WHERE u.role = 'student'
                  AND u.group_name = ?
                  AND lh.date BETWEEN ? AND ?{teacher_clause}
                """,
                params,
            )
            present_dates = {row[0] for row in cursor.fetchall()}
            cursor.execute(
                f"""
                SELECT DISTINCT ao.date
                FROM attendance_override ao
                JOIN users u ON u.username = ao.username
                WHERE u.role = 'student'
                  AND u.group_name = ?
                  AND ao.date BETWEEN ? AND ?
                  AND LOWER(COALESCE(ao.status, '')) IN ('present', 'late'){teacher_clause}
                """,
                params,
            )
            present_dates.update(row[0] for row in cursor.fetchall())
            month_present_map[(scope_teacher or "", group_name)] = present_dates

            if scope_teacher:
                cursor.execute(
                    """
                    SELECT note_date
                    FROM class_module_notes
                    WHERE group_name = ? AND teacher_username = ?
                      AND note_date BETWEEN ? AND ?
                    """,
                    (group_name, scope_teacher, month_start.isoformat(), month_end.isoformat()),
                )
            else:
                cursor.execute(
                    """
                    SELECT note_date
                    FROM class_module_notes
                    WHERE group_name = ? AND teacher_username IS NULL
                      AND note_date BETWEEN ? AND ?
                    """,
                    (group_name, month_start.isoformat(), month_end.isoformat()),
                )
            month_note_map[(scope_teacher or "", group_name)] = {row[0] for row in cursor.fetchall()}

        calendar_summary = {}
        for day in calendar_days:
            present_classes = 0
            noted_classes = 0
            for scope in dashboard_scopes:
                scope_key = (scope["teacher_username"] or "", scope["group"])
                if day in month_present_map.get(scope_key, set()):
                    present_classes += 1
                if day in month_note_map.get(scope_key, set()):
                    noted_classes += 1
            missed_classes = max(0, len(dashboard_scopes) - present_classes)
            calendar_summary[day] = {
                "present_classes": present_classes,
                "missed_classes": missed_classes,
                "noted_classes": noted_classes,
            }

        selected_day_rows = []
        selected_day_notes_map = defaultdict(list)
        if selected_date:
            selected_keys = []
            for scope in dashboard_scopes:
                selected_keys.append((scope["teacher_username"] or "", scope["group"]))
                if scope["teacher_username"]:
                    cursor.execute(
                        """
                        SELECT module_name, progress_text, note_text, module_finished, generated_test_id, created_at
                        FROM class_module_notes
                        WHERE note_date = ? AND group_name = ? AND teacher_username = ?
                        ORDER BY created_at DESC, id DESC
                        """,
                        (selected_date, scope["group"], scope["teacher_username"]),
                    )
                else:
                    cursor.execute(
                        """
                        SELECT module_name, progress_text, note_text, module_finished, generated_test_id, created_at
                        FROM class_module_notes
                        WHERE note_date = ? AND group_name = ? AND teacher_username IS NULL
                        ORDER BY created_at DESC, id DESC
                        """,
                        (selected_date, scope["group"]),
                    )
                selected_day_notes_map[(scope["teacher_username"] or "", scope["group"])] = cursor.fetchall()

            for scope in dashboard_scopes:
                scope_key = (scope["teacher_username"] or "", scope["group"])
                is_present = selected_date in month_present_map.get(scope_key, set())
                view_href = f"/view_as_student/{scope['group']}"
                if scope["teacher_username"]:
                    view_href += f"?teacher={scope['teacher_username']}"
                selected_day_rows.append(
                    {
                        "group": scope["group"],
                        "teacher_username": scope["teacher_username"],
                        "label": scope["label"],
                        "view_href": view_href,
                        "status": "present" if is_present else "missed",
                        "notes": selected_day_notes_map.get(scope_key, []),
                    }
                )

        module_names = []
        cursor.execute("SELECT modules FROM question_bank_questions WHERE COALESCE(modules, '') != ''")
        for (modules_text,) in cursor.fetchall():
            module_names.extend(parse_module_names(modules_text))
        module_names = sorted({item for item in module_names if item}, key=str.lower)

        calendar_weeks = []
        if calendar_days:
            first_visible = datetime.strptime(calendar_days[0], "%Y-%m-%d").date()
            last_visible = datetime.strptime(calendar_days[-1], "%Y-%m-%d").date()
            grid_start = first_visible - timedelta(days=first_visible.weekday())
            grid_end = last_visible + timedelta(days=(6 - last_visible.weekday()))
            week = []
            current_day = grid_start
            while current_day <= grid_end:
                day_str = current_day.isoformat()
                in_month = month_start <= current_day <= month_end and day_str in calendar_summary
                week.append(
                    {
                        "date": day_str,
                        "day": current_day.day,
                        "in_month": in_month,
                        "is_selected": day_str == selected_date,
                        "summary": calendar_summary.get(day_str),
                    }
                )
                if len(week) == 7:
                    calendar_weeks.append(week)
                    week = []
                current_day += timedelta(days=1)

        cursor.execute(
            """
            SELECT COUNT(DISTINCT lh.username)
            FROM login_history lh
            JOIN users u ON u.username = lh.username
            WHERE lh.date = ? AND u.role = 'student'
            """
            + (" AND u.teacher_username = ?" if teacher_scope else "")
            + grade_filter_clause,
            tuple([today] + ([teacher_scope] if teacher_scope else []) + grade_filter_params),
        )
        active_today = cursor.fetchone()[0] or 0

        days_21 = get_last_21_days()
        excluded_days = fetch_group_excluded_dates(cursor, groups)
        filtered_days = [day for day in days_21 if day not in excluded_days]
        excluded_days_grade = excluded_days
        filtered_grade_days = filtered_days
        login_times = fetch_first_login_times(cursor, student_usernames, filtered_days)
        overrides = fetch_attendance_override_statuses(cursor, student_usernames, filtered_days)

        group_att = []
        total_present_all = 0
        total_slots_all = 0
        if role == "admin" and not selected_teacher:
            for scope in group_options:
                group_name = scope["group"]
                scope_teacher = scope["teacher_username"]
                cursor.execute(
                    """
                    SELECT username, full_name
                    FROM users
                    WHERE role = 'student' AND group_name = ? AND teacher_username = ?
                    ORDER BY full_name, username
                    """,
                    (group_name, scope_teacher),
                )
                members = [(row[0], row[1] or row[0]) for row in cursor.fetchall()]
                scope_days = [day for day in filtered_days if day not in excluded_days.get(group_name, set())]
                late_cutoffs = fetch_group_late_thresholds(cursor, group_name, scope_days, teacher_username=scope_teacher)
                class_checked_dates = fetch_class_checked_dates(cursor, group_name, teacher_username=scope_teacher)
                total_present = 0
                total_absent = 0
                for student_username, _student_name in members:
                    history = build_attendance_history(
                        cursor,
                        student_username,
                        group_name,
                        scope_days,
                        login_map=login_times,
                        override_map=overrides,
                        late_cutoffs=late_cutoffs,
                        class_checked_dates=class_checked_dates,
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
                        "teacher_username": scope_teacher,
                        "label": scope["label"],
                        "view_href": scope["href"],
                        "students": len(members),
                        "att_pct": round((total_present / total_counted) * 100) if total_counted else 0,
                    }
                )
        else:
            group_members = defaultdict(list)
            for uname, full_name, group_name, _teacher_name, _grade in broad_student_rows:
                if group_name:
                    group_members[group_name].append((uname, full_name or uname))
            for scope in group_options:
                group_name = scope["group"]
                members = group_members.get(group_name, [])
                group_days = [day for day in filtered_days if day not in excluded_days.get(group_name, set())]
                late_cutoffs = fetch_group_late_thresholds(cursor, group_name, group_days, teacher_username=teacher_scope)
                class_checked_dates = fetch_class_checked_dates(cursor, group_name, teacher_username=teacher_scope)
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
                        late_cutoffs=late_cutoffs,
                        class_checked_dates=class_checked_dates,
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
                        "teacher_username": teacher_scope,
                        "label": scope["label"],
                        "view_href": scope["href"],
                        "students": len(members),
                        "att_pct": round((total_present / total_counted) * 100) if total_counted else 0,
                    }
                )
        grade_present_total = 0
        grade_absent_total = 0
        for uname, _full_name, group_name, learner_teacher, _grade in student_rows:
            group_days = [day for day in filtered_grade_days if day not in excluded_days_grade.get(group_name, set())]
            learner_scope = learner_teacher if role == "admin" and not selected_teacher else teacher_scope
            late_cutoffs = fetch_group_late_thresholds(cursor, group_name, group_days, teacher_username=learner_scope)
            class_checked_dates = fetch_class_checked_dates(cursor, group_name, teacher_username=learner_scope)
            attendance_history = build_attendance_history(
                cursor,
                uname,
                group_name,
                group_days,
                login_map=login_times,
                override_map=overrides,
                late_cutoffs=late_cutoffs,
                class_checked_dates=class_checked_dates,
                excluded_dates=excluded_days_grade.get(group_name, set()),
            )
            attendance_summary = summarize_attendance_history(attendance_history)
            grade_present_total += attendance_summary["present_days"]
            grade_absent_total += attendance_summary["absent_days"]
        grade_total_slots = grade_present_total + grade_absent_total
        avg_att_pct = round((grade_present_total / grade_total_slots) * 100) if grade_total_slots else 0

        low_attendance = get_low_attendance_learners(10, grade_groups, teacher_scope)
        learner_scope_labels = {
            uname: f"{group_name} ({teacher_name})" if role == "admin" and not selected_teacher and group_name and teacher_name else (group_name or "—")
            for uname, _full_name, group_name, teacher_name, _grade in student_rows
        }
        low_attendance = [
            (name, learner_username, absent, learner_scope_labels.get(learner_username, "—"))
            for name, learner_username, absent in low_attendance
        ]
        practical_avg_map = fetch_student_practical_averages(cursor, teacher_scope)
        theory_avg_map = fetch_student_theory_averages(cursor, teacher_scope)
        practical_group_avg_map = fetch_group_practical_averages(cursor, groups, teacher_username=teacher_scope)
        theory_group_avg_map = fetch_group_theory_averages(cursor, groups, teacher_username=teacher_scope)

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
        for uname, full_name, group_name, learner_teacher, _grade in student_rows:
            group_days = [day for day in filtered_grade_days if day not in excluded_days_grade.get(group_name, set())]
            learner_scope = learner_teacher if role == "admin" and not selected_teacher else teacher_scope
            late_cutoffs = fetch_group_late_thresholds(cursor, group_name, group_days, teacher_username=learner_scope)
            class_checked_dates = fetch_class_checked_dates(cursor, group_name, teacher_username=learner_scope)
            attendance_history = build_attendance_history(
                cursor,
                uname,
                group_name,
                group_days,
                login_map=login_times,
                override_map=overrides,
                late_cutoffs=late_cutoffs,
                class_checked_dates=class_checked_dates,
                excluded_dates=excluded_days_grade.get(group_name, set()),
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
                        "group": f"{group_name} ({learner_teacher})" if role == "admin" and not selected_teacher and group_name and learner_teacher else (group_name or "—"),
                        "score": risk_score,
                        "status": "High Risk" if risk_score > 70 else "At Risk",
                        "reason": " | ".join(reasons) if reasons else "Multiple factors",
                    }
                )
            combined_students.append(
                (
                    uname,
                    full_name or uname,
                    f"{group_name} ({learner_teacher})" if role == "admin" and not selected_teacher and group_name and learner_teacher else (group_name or "—"),
                    combined_avg,
                )
            )

        at_risk_students.sort(key=lambda item: item["score"], reverse=True)
        at_risk_students = at_risk_students[:10]
        combined_students = [row for row in combined_students if row[3] is not None]
        top_performers = sorted(combined_students, key=lambda item: item[3], reverse=True)[:5]
        bottom_performers = sorted(combined_students, key=lambda item: item[3])[:5]
        student_grade_map = {row[0]: (row[4] or "").strip() for row in student_rows}
        top_performers_by_grade = defaultdict(list)
        bottom_performers_by_grade = defaultdict(list)
        for learner_username, learner_name, group_label, combined_avg in sorted(combined_students, key=lambda item: item[3], reverse=True):
            learner_grade = student_grade_map.get(learner_username)
            if not learner_grade:
                continue
            if len(top_performers_by_grade[learner_grade]) >= 5:
                continue
            top_performers_by_grade[learner_grade].append(
                (learner_username, learner_name, group_label, combined_avg)
            )
        for learner_username, learner_name, group_label, combined_avg in sorted(combined_students, key=lambda item: item[3]):
            learner_grade = student_grade_map.get(learner_username)
            if not learner_grade:
                continue
            if len(bottom_performers_by_grade[learner_grade]) >= 5:
                continue
            bottom_performers_by_grade[learner_grade].append(
                (learner_username, learner_name, group_label, combined_avg)
            )
        top_performers_by_grade = dict(
            sorted(top_performers_by_grade.items(), key=lambda item: (len(item[0]), item[0]))
        )
        bottom_performers_by_grade = dict(
            sorted(bottom_performers_by_grade.items(), key=lambda item: (len(item[0]), item[0]))
        )
        low_attendance_by_grade = defaultdict(list)
        for name, learner_username, absent, group_label in low_attendance:
            learner_grade = student_grade_map.get(learner_username)
            if not learner_grade:
                continue
            if len(low_attendance_by_grade[learner_grade]) >= 10:
                continue
            low_attendance_by_grade[learner_grade].append((name, learner_username, absent, group_label))
        low_attendance_by_grade = dict(
            sorted(low_attendance_by_grade.items(), key=lambda item: (len(item[0]), item[0]))
        )
        at_risk_by_grade = defaultdict(list)
        for student in sorted(at_risk_students, key=lambda item: item["score"], reverse=True):
            learner_grade = student_grade_map.get(student["username"])
            if not learner_grade:
                continue
            if len(at_risk_by_grade[learner_grade]) >= 10:
                continue
            at_risk_by_grade[learner_grade].append(student)
        at_risk_by_grade = dict(
            sorted(at_risk_by_grade.items(), key=lambda item: (len(item[0]), item[0]))
        )

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
                SELECT u.full_name, u.group_name, b.subject, b.task, b.best_score, MAX(r.timestamp), u.teacher_username
                FROM (
                    SELECT username, subject, task, MAX(score) as best_score
                    FROM results GROUP BY username, subject, task
                ) b
                JOIN results r ON r.username = b.username AND r.subject = b.subject AND r.task = b.task AND r.score = b.best_score
                JOIN users u ON u.username = b.username
                WHERE u.role = 'student' {group_filter_clause}{grade_filter_clause}
                GROUP BY b.username, b.subject, b.task
                ORDER BY MAX(r.timestamp) DESC LIMIT 15
                """,
                group_filter_params + grade_filter_params,
            )
        else:
            cursor.execute(
                """
                SELECT u.full_name, u.group_name, b.subject, b.task, b.best_score, MAX(r.timestamp), u.teacher_username
                FROM (
                    SELECT username, subject, task, MAX(score) as best_score
                    FROM results GROUP BY username, subject, task
                ) b
                JOIN results r ON r.username = b.username AND r.subject = b.subject AND r.task = b.task AND r.score = b.best_score
                JOIN users u ON u.username = b.username
                WHERE u.role = 'student'""" + grade_filter_clause + """
                GROUP BY b.username, b.subject, b.task
                ORDER BY MAX(r.timestamp) DESC LIMIT 15
                """,
                grade_filter_params,
            )
        recent_submissions = cursor.fetchall()

        subject_avgs = defaultdict(list)
        if role == "admin" and not selected_teacher:
            for scope in grade_group_options:
                label = scope["label"]
                group_name = scope["group"]
                scope_teacher = scope["teacher_username"]
                cursor.execute(
                    """
                    SELECT b.subject, ROUND(AVG(b.best_score),1), COUNT(*)
                    FROM (
                        SELECT username, subject, task, MAX(score) as best_score
                        FROM results GROUP BY username, subject, task
                    ) b
                    JOIN users u ON u.username = b.username
                    WHERE u.group_name = ? AND u.teacher_username = ? AND u.role = 'student' AND u.grade = ?
                    GROUP BY b.subject
                    ORDER BY b.subject
                    """,
                    (group_name, scope_teacher, selected_grade),
                )
                for subject, avg, cnt in cursor.fetchall():
                    subject_avgs[label].append((subject, avg, cnt, "Practical"))
                cursor.execute(
                    """
                    SELECT ROUND(AVG(b.best_pct),1), COUNT(*)
                    FROM (
                        SELECT username, test_id, MAX(percentage) as best_pct
                        FROM theory_submissions GROUP BY username, test_id
                    ) b
                    JOIN users u ON u.username = b.username
                    WHERE u.group_name = ? AND u.teacher_username = ? AND u.role = 'student' AND u.grade = ?
                    """,
                    (group_name, scope_teacher, selected_grade),
                )
                theory_avg, theory_cnt = cursor.fetchone()
                if theory_avg is not None or theory_cnt:
                    subject_avgs[label].append(("Theory", theory_avg, theory_cnt, "Theory"))
        else:
            practical_subjects = defaultdict(set)
            if grade_groups:
                placeholders = ",".join("?" for _ in grade_groups)
                cursor.execute(
                    f"""
                    SELECT tg.group_name, s.name
                    FROM task_groups tg
                    JOIN tasks t ON t.id = tg.task_id
                    JOIN subjects s ON s.id = t.subject_id
                    WHERE t.task_type = 'practical' AND tg.group_name IN ({placeholders})
                    """,
                    grade_groups,
                )
                for group_name, subject in cursor.fetchall():
                    practical_subjects[group_name].add(subject)
                cursor.execute(
                    f"""
                    SELECT u.group_name, b.subject, ROUND(AVG(b.best_score),1), COUNT(*)
                    FROM (
                        SELECT username, subject, task, MAX(score) as best_score
                        FROM results GROUP BY username, subject, task
                    ) b
                    JOIN users u ON u.username = b.username
                    WHERE u.group_name IS NOT NULL AND u.role = 'student' {group_filter_clause}{grade_filter_clause}
                    GROUP BY u.group_name, b.subject
                    ORDER BY u.group_name, b.subject
                    """,
                    group_filter_params + grade_filter_params,
                )
                practical_avgs_raw = cursor.fetchall()
                practical_avgs = {(group_name, subject): (avg, cnt) for group_name, subject, avg, cnt in practical_avgs_raw}
                for group_name, subjects in practical_subjects.items():
                    for subject in sorted(subjects):
                        avg, cnt = practical_avgs.get((group_name, subject), (None, 0))
                        subject_avgs[group_name].append((subject, avg, cnt, "Practical"))
                for group_name, subject, avg, cnt in practical_avgs_raw:
                    if subject not in practical_subjects.get(group_name, set()):
                        subject_avgs[group_name].append((subject, avg, cnt, "Practical"))
                cursor.execute(
                    f"""
                    SELECT u.group_name, ROUND(AVG(b.best_pct),1), COUNT(*)
                    FROM (
                        SELECT username, test_id, MAX(percentage) as best_pct
                        FROM theory_submissions GROUP BY username, test_id
                    ) b
                    JOIN theory_tests tt ON b.test_id = tt.id
                    JOIN users u ON u.username = b.username
                    WHERE u.group_name IS NOT NULL AND u.role = 'student' {group_filter_clause}{grade_filter_clause}
                    GROUP BY u.group_name
                    ORDER BY u.group_name
                    """,
                    group_filter_params + grade_filter_params,
                )
                theory_avgs = {group_name: (avg, cnt) for group_name, avg, cnt in cursor.fetchall()}
                for group_name in sorted(grade_groups):
                    avg, cnt = theory_avgs.get(group_name, (None, 0))
                    if avg is not None or cnt:
                        subject_avgs[group_name].append(("Theory", avg, cnt, "Theory"))
        subject_avgs = dict(subject_avgs)

        if role == "teacher":
            cursor.execute(
                f"""
                SELECT u.full_name, u.group_name, tt.subject, tt.title, b.best_pct, MAX(ts.submitted_at), u.teacher_username
                FROM (
                    SELECT username, test_id, MAX(percentage) as best_pct
                    FROM theory_submissions GROUP BY username, test_id
                ) b
                JOIN theory_submissions ts ON ts.username = b.username AND ts.test_id = b.test_id AND ts.percentage = b.best_pct
                JOIN theory_tests tt ON b.test_id = tt.id
                JOIN users u ON u.username = b.username
                WHERE u.role = 'student' {group_filter_clause}{grade_filter_clause}
                GROUP BY b.username, b.test_id
                ORDER BY MAX(ts.submitted_at) DESC LIMIT 15
                """,
                group_filter_params + grade_filter_params,
            )
        else:
            cursor.execute(
                """
                SELECT u.full_name, u.group_name, tt.subject, tt.title, b.best_pct, MAX(ts.submitted_at), u.teacher_username
                FROM (
                    SELECT username, test_id, MAX(percentage) as best_pct
                    FROM theory_submissions GROUP BY username, test_id
                ) b
                JOIN theory_submissions ts ON ts.username = b.username AND ts.test_id = b.test_id AND ts.percentage = b.best_pct
                JOIN theory_tests tt ON b.test_id = tt.id
                JOIN users u ON u.username = b.username
                WHERE u.role = 'student'""" + grade_filter_clause + """
                GROUP BY b.username, b.test_id
                ORDER BY MAX(ts.submitted_at) DESC LIMIT 15
                """,
                grade_filter_params,
            )
        recent_theory_submissions = cursor.fetchall()

        students_without_classes_query = """
            SELECT username, full_name
            FROM users
            WHERE role = 'student' AND (
                (group_name IS NULL OR group_name = '') OR
                (teacher_username IS NULL OR teacher_username = '')
            )
        """
        students_without_classes_params = list(grade_filter_params)
        if role == "teacher":
            students_without_classes_query = """
                SELECT username, full_name
                FROM users
                WHERE role = 'student' AND (
                    ((group_name IS NULL OR group_name = '') AND teacher_username = ?)
                    OR (teacher_username IS NULL OR teacher_username = '')
                )
            """
            students_without_classes_params = [username, *grade_filter_params]
        if selected_grade:
            students_without_classes_query += " AND grade = ?"
        students_without_classes_query += " ORDER BY full_name, username"
        cursor.execute(
            students_without_classes_query,
            tuple(students_without_classes_params),
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
                  {group_filter_clause}{grade_filter_clause}
                GROUP BY u.group_name
                """,
                tuple([today] + group_filter_params + grade_filter_params),
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
                """ + grade_filter_clause + """
                GROUP BY u.group_name
                """,
                tuple([today] + grade_filter_params),
            )
        missing_by_group = cursor.fetchall()
        if role == "admin" and not selected_teacher:
            split_missing = []
            for scope in grade_group_options:
                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM users u
                    JOIN task_groups tg ON tg.group_name = u.group_name
                    JOIN tasks t ON t.id = tg.task_id
                    JOIN subjects s ON s.id = t.subject_id
                    WHERE u.role = 'student'
                      AND u.group_name = ?
                      AND u.teacher_username = ?
                      AND u.grade = ?
                      AND t.assign_date <= ?
                      AND t.task_type = 'practical'
                      AND NOT EXISTS (
                          SELECT 1 FROM results r
                          WHERE r.username = u.username AND r.subject = s.name AND r.task = t.name
                      )
                    """,
                    (scope["group"], scope["teacher_username"], selected_grade, today),
                )
                split_missing.append(
                    {
                        "group": scope["group"],
                        "teacher_username": scope["teacher_username"],
                        "label": scope["label"],
                        "href": scope["href"],
                        "count": cursor.fetchone()[0] or 0,
                    }
                )
            missing_by_group = split_missing
        else:
            missing_by_group = [
                {
                    "group": grp,
                    "teacher_username": teacher_scope,
                    "label": grp,
                    "href": f"/view_as_student/{grp}" + (f"?teacher={teacher_scope}" if role == "admin" and teacher_scope else ""),
                    "count": cnt,
                }
                for grp, cnt in missing_by_group
            ]

        group_att_summary = []
        for item in group_att:
            if role == "admin" and not selected_teacher and item.get("teacher_username"):
                cursor.execute(
                    """
                    SELECT username
                    FROM users
                    WHERE role = 'student' AND group_name = ? AND teacher_username = ?
                    """,
                    (item["group"], item["teacher_username"]),
                )
                scope_usernames = [row[0] for row in cursor.fetchall()]
                practical_scores = [practical_avg_map.get(uname) for uname in scope_usernames if practical_avg_map.get(uname) is not None]
                theory_scores = [theory_avg_map.get(uname) for uname in scope_usernames if theory_avg_map.get(uname) is not None]
                practical_group_avg = round(sum(practical_scores) / len(practical_scores), 1) if practical_scores else None
                theory_group_avg = round(sum(theory_scores) / len(theory_scores), 1) if theory_scores else None
            else:
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
            group_options=group_options,
            teacher_options=teacher_options,
            selected_teacher=selected_teacher,
            selected_grade=selected_grade,
            prev_grade=prev_grade,
            next_grade=next_grade,
            group_att=group_att_summary,
            low_attendance=low_attendance,
            low_attendance_by_grade=low_attendance_by_grade,
            recent_activities=recent_activities,
            recent_submissions=recent_submissions,
            recent_theory_submissions=recent_theory_submissions,
            subject_avgs=subject_avgs,
            top_performers=top_performers,
            top_performers_by_grade=top_performers_by_grade,
            bottom_performers=bottom_performers,
            bottom_performers_by_grade=bottom_performers_by_grade,
            at_risk_students=at_risk_students,
            at_risk_by_grade=at_risk_by_grade,
            students_without_classes=students_without_classes,
            missing_by_group=missing_by_group,
            quick_actions=quick_actions,
            available_quick_actions=available_quick_actions,
            active_term=get_active_term_range(),
            days_in_period=len(days_21),
            dashboard_month=month_start.strftime("%Y-%m"),
            dashboard_month_label=month_start.strftime("%B %Y"),
            prev_month_value=prev_month_value,
            next_month_value=next_month_value,
            selected_date=selected_date,
            calendar_weeks=calendar_weeks,
            selected_day_rows=selected_day_rows,
            module_names=module_names,
        )

    @app.route("/teacher_dashboard/module_note", methods=["POST"])
    def teacher_dashboard_module_note():
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))

        role = get_user_role(username)
        if role not in ["teacher", "admin"]:
            return "Access denied", 403

        group = (request.form.get("group") or "").strip()
        scope_teacher = (request.form.get("scope_teacher") or "").strip() or None
        note_date = (request.form.get("date") or "").strip()
        module_name = (request.form.get("module_name") or "").strip()
        progress_text = (request.form.get("progress_text") or "").strip()
        note_text = (request.form.get("note_text") or "").strip()
        module_finished = 1 if request.form.get("module_finished") else 0
        selected_teacher = (request.form.get("selected_teacher") or "").strip() or None
        selected_grade = (request.form.get("selected_grade") or "").strip()
        month_value = (request.form.get("month") or "").strip()

        redirect_kwargs = {}
        if selected_teacher:
            redirect_kwargs["teacher"] = selected_teacher
        if selected_grade:
            redirect_kwargs["grade"] = selected_grade
        if month_value:
            redirect_kwargs["month"] = month_value
        if note_date:
            redirect_kwargs["selected_date"] = note_date

        if not group or not note_date or not module_name:
            flash("Date, class, and module are required.", "error")
            return redirect(url_for("teacher_dashboard", **redirect_kwargs))

        if role == "teacher":
            scope_teacher = username

        conn = get_db()
        cursor = conn.cursor()
        generated_test_id = None

        if module_finished:
            cursor.execute(
                """
                SELECT id
                FROM theory_tests
                WHERE LOWER(COALESCE(generated_module_name, '')) = LOWER(?)
                ORDER BY id DESC
                LIMIT 1
                """,
                (module_name,),
            )
            existing_test = cursor.fetchone()
            if existing_test:
                generated_test_id = existing_test[0]
            else:
                cursor.execute(
                    """
                    SELECT id, question_type, subject, question_text, COALESCE(modules, '')
                    FROM question_bank_questions
                    ORDER BY id
                    """
                )
                bank_rows = cursor.fetchall()
                matching_rows = [
                    row for row in bank_rows
                    if module_name.lower() in {item.lower() for item in parse_module_names(row[4] or "")}
                ]
                if not matching_rows:
                    conn.close()
                    flash(f"No question bank questions found for module '{module_name}'.", "error")
                    return redirect(url_for("teacher_dashboard", **redirect_kwargs))

                subjects = [row[2] for row in matching_rows if row[2]]
                subject_label = subjects[0] if len(set(subjects)) == 1 else (subjects[0] if subjects else "Theory")
                cursor.execute(
                    """
                    INSERT INTO theory_tests
                        (title, subject, assign_date, time_limit, allow_multiple, max_attempts, show_answers, created_by, created_at, is_active, generated_module_name)
                    VALUES (?, ?, ?, 0, 0, 1, 1, ?, ?, 1, ?)
                    """,
                    (
                        f"{module_name} Class Test",
                        subject_label,
                        note_date,
                        username,
                        datetime.now().isoformat(),
                        module_name,
                    ),
                )
                generated_test_id = cursor.lastrowid
                order_index = 1
                non_match_rows = [row for row in matching_rows if row[1] != "match"]
                match_ids = [row[0] for row in matching_rows if row[1] == "match"]
                for bank_question_id, _question_type, _subject, _question_text, _modules in non_match_rows:
                    clone_bank_question_to_test(cursor, bank_question_id, generated_test_id, order_index)
                    order_index += 1
                if match_ids:
                    merge_bank_match_rows_into_test(cursor, match_ids, generated_test_id, order_index)

            cursor.execute(
                "INSERT OR IGNORE INTO theory_test_groups (test_id, group_name) VALUES (?, ?)",
                (generated_test_id, group),
            )
            if scope_teacher:
                cursor.execute(
                    "INSERT OR IGNORE INTO theory_test_teachers (test_id, teacher_username) VALUES (?, ?)",
                    (generated_test_id, scope_teacher),
                )
            cursor.execute("UPDATE theory_tests SET is_active = 1 WHERE id = ?", (generated_test_id,))

        cursor.execute(
            """
            INSERT INTO class_module_notes
                (note_date, group_name, teacher_username, module_name, progress_text, note_text, module_finished, generated_test_id, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                note_date,
                group,
                scope_teacher,
                module_name,
                progress_text,
                note_text,
                module_finished,
                generated_test_id,
                username,
                datetime.now().isoformat(),
            ),
        )
        conn.commit()
        conn.close()

        if generated_test_id:
            flash(f"Module note saved and class test assigned for {group}.", "success")
        else:
            flash(f"Module note saved for {group}.", "success")
        return redirect(url_for("teacher_dashboard", **redirect_kwargs))

    @app.route("/dashboard")
    def legacy_dashboard():
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))
        role = get_user_role(username)
        if role in ["teacher", "admin"]:
            return redirect(url_for("teacher_dashboard"))
        return redirect(url_for("student_dashboard"))
