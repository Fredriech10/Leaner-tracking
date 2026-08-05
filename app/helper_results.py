from .helper_common import parse_module_names


def fetch_student_practical_averages(cursor, teacher_username=None):
    params = []
    teacher_filter = ""
    if teacher_username:
        teacher_filter = " AND u.teacher_username = ?"
        params.append(teacher_username)
    cursor.execute(
        f"""
        SELECT best_scores.username, ROUND(AVG(best_scores.best_score), 1)
        FROM (
            SELECT username, subject, task, MAX(score) AS best_score
            FROM results
            GROUP BY username, subject, task
        ) best_scores
        JOIN users u ON u.username = best_scores.username
        WHERE u.role = 'student'{teacher_filter}
        GROUP BY best_scores.username
        """,
        params,
    )
    return {username: average for username, average in cursor.fetchall()}


def fetch_student_theory_averages(cursor, teacher_username=None):
    params = []
    teacher_filter = ""
    if teacher_username:
        teacher_filter = " AND u.teacher_username = ?"
        params.append(teacher_username)
    cursor.execute(
        f"""
        SELECT best_scores.username, ROUND(AVG(best_scores.best_pct), 1)
        FROM (
            SELECT username, test_id, MAX(percentage) AS best_pct
            FROM theory_submissions
            GROUP BY username, test_id
        ) best_scores
        JOIN users u ON u.username = best_scores.username
        WHERE u.role = 'student'{teacher_filter}
        GROUP BY best_scores.username
        """,
        params,
    )
    return {username: average for username, average in cursor.fetchall()}


def fetch_group_practical_averages(cursor, groups):
    if not groups:
        return {}
    placeholders = ",".join("?" for _ in groups)
    cursor.execute(
        f"""
        SELECT u.group_name, ROUND(AVG(best_scores.best_score), 1)
        FROM (
            SELECT username, subject, task, MAX(score) AS best_score
            FROM results
            GROUP BY username, subject, task
        ) best_scores
        JOIN users u ON u.username = best_scores.username
        WHERE u.role = 'student' AND u.group_name IN ({placeholders})
        GROUP BY u.group_name
        """,
        groups,
    )
    return {group: average for group, average in cursor.fetchall()}


def fetch_group_theory_averages(cursor, groups):
    if not groups:
        return {}
    placeholders = ",".join("?" for _ in groups)
    cursor.execute(
        f"""
        SELECT u.group_name, ROUND(AVG(best_scores.best_pct), 1)
        FROM (
            SELECT username, test_id, MAX(percentage) AS best_pct
            FROM theory_submissions
            GROUP BY username, test_id
        ) best_scores
        JOIN users u ON u.username = best_scores.username
        WHERE u.role = 'student' AND u.group_name IN ({placeholders})
        GROUP BY u.group_name
        """,
        groups,
    )
    return {group: average for group, average in cursor.fetchall()}


def fetch_theory_module_weaknesses(cursor, username=None, group_name=None, limit=10):
    where_parts = ["latest.rn = 1"]
    params = []
    if username:
        where_parts.append("latest.username = ?")
        params.append(username)
    if group_name:
        where_parts.append("u.group_name = ?")
        params.append(group_name)
    where_clause = " AND ".join(where_parts)
    cursor.execute(
        f"""
        SELECT latest.username, tq.source_modules, tq.question_type, ta.is_correct
        FROM (
            SELECT ts.id, ts.username, ts.test_id,
                   ROW_NUMBER() OVER (
                       PARTITION BY ts.username, ts.test_id
                       ORDER BY COALESCE(ts.submitted_at, '') DESC, ts.id DESC
                   ) AS rn
            FROM theory_submissions ts
        ) latest
        JOIN theory_answers ta ON ta.submission_id = latest.id
        JOIN theory_questions tq ON tq.id = ta.question_id
        JOIN users u ON u.username = latest.username
        WHERE {where_clause}
        """,
        params,
    )
    summary = {}
    for learner_username, source_modules, question_type, is_correct in cursor.fetchall():
        modules = parse_module_names(source_modules or "") or ["Unmapped"]
        for module_name in modules:
            item = summary.setdefault(
                module_name,
                {"asked": 0, "wrong": 0, "learners": set(), "question_types": set()},
            )
            item["asked"] += 1
            item["wrong"] += 0 if is_correct else 1
            item["learners"].add(learner_username)
            if question_type:
                item["question_types"].add(question_type)
    rows = []
    for module_name, item in summary.items():
        if not item["asked"]:
            continue
        rows.append(
            {
                "module": module_name,
                "asked": item["asked"],
                "wrong": item["wrong"],
                "wrong_pct": round((item["wrong"] / item["asked"]) * 100),
                "learners": len(item["learners"]),
                "question_types": ", ".join(sorted(item["question_types"])),
            }
        )
    rows.sort(key=lambda row: (row["wrong_pct"], row["wrong"], row["asked"]), reverse=True)
    return rows[:limit]
