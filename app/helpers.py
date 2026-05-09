import os
import importlib
from datetime import datetime, timedelta
from .database import get_db, get_groups


# ── Term helpers ──────────────────────────────────────────────────────────────

def get_term_dates():
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT term, start_date, end_date FROM term_dates ORDER BY term")
        rows = cursor.fetchall()
    except Exception:
        rows = []
    conn.close()
    terms = {i: {"start": None, "end": None} for i in range(1, 5)}
    for term, start, end in rows:
        terms[term] = {"start": start, "end": end}
    return terms


def get_active_term_range():
    today = datetime.now().date().isoformat()
    for t in get_term_dates().values():
        if t["start"] and t["end"] and t["start"] <= today <= t["end"]:
            return t["start"], t["end"]
    return None


def get_all_term_days():
    days = set()
    for t in get_term_dates().values():
        if t["start"] and t["end"]:
            current = datetime.strptime(t["start"], "%Y-%m-%d").date()
            end = min(datetime.strptime(t["end"], "%Y-%m-%d").date(), datetime.now().date())
            while current <= end:
                if current.weekday() < 5:
                    days.add(current.strftime("%Y-%m-%d"))
                current += timedelta(days=1)
    return days


def get_last_21_days():
    days = []
    current = datetime.now().date()
    term_days = get_all_term_days()
    limit = 0
    while len(days) < 21 and limit < 365:
        s = current.strftime("%Y-%m-%d")
        if current.weekday() < 5 and (not term_days or s in term_days):
            days.append(s)
        current -= timedelta(days=1)
        limit += 1
    return list(reversed(days))


def get_last_7_days():
    days = []
    current = datetime.now().date()
    term_days = get_all_term_days()
    limit = 0
    while len(days) < 7 and limit < 365:
        s = current.strftime("%Y-%m-%d")
        if current.weekday() < 5 and (not term_days or s in term_days):
            days.append(s)
        current -= timedelta(days=1)
        limit += 1
    return list(reversed(days))


# ── Attendance helpers ────────────────────────────────────────────────────────

def get_group_late_threshold(group, date):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT MIN(login_time) FROM login_history
    WHERE date = ? AND username IN (SELECT username FROM users WHERE group_name = ?)
    """, (date, group))
    min_login = cursor.fetchone()[0]
    conn.close()
    if not min_login:
        return None
    try:
        min_dt = datetime.fromisoformat(min_login)
    except ValueError:
        min_dt = datetime.strptime(min_login, "%Y-%m-%d %H:%M:%S")
    return (min_dt + timedelta(minutes=6)).strftime("%H:%M")


def get_attendance_data(group, start_date=None, end_date=None):
    conn = get_db()
    cursor = conn.cursor()

    if not start_date or not end_date:
        term_range = get_active_term_range()
        if term_range:
            start_date, end_date = term_range
            current = datetime.strptime(start_date, "%Y-%m-%d").date()
            end = datetime.strptime(end_date, "%Y-%m-%d").date()
            days = []
            while current <= end:
                if current.weekday() < 5:
                    days.append(current.strftime("%Y-%m-%d"))
                current += timedelta(days=1)
        else:
            days = get_last_7_days()
    else:
        days = []
        current = datetime.strptime(start_date, "%Y-%m-%d").date()
        end = datetime.strptime(end_date, "%Y-%m-%d").date()
        while current <= end:
            if current.weekday() < 5:
                days.append(current.strftime("%Y-%m-%d"))
            current += timedelta(days=1)

    today_str = datetime.now().date().isoformat()
    days = [d for d in days if d <= today_str]

    cursor.execute("SELECT date FROM excluded_dates WHERE group_name IS NULL OR group_name = ?", (group,))
    excluded = {row[0] for row in cursor.fetchall()}
    days = [d for d in days if d not in excluded]

    cursor.execute("SELECT username, full_name, group_name FROM users WHERE group_name = ? AND role = 'student'", (group,))
    learners = cursor.fetchall()

    late_cutoffs = {day: get_group_late_threshold(group, day) for day in days}
    attendance = []

    for user, name, user_group_name in learners:
        row = {"username": user, "name": name, "group": user_group_name, "days": {}}
        for day in days:
            cursor.execute("SELECT MIN(login_time) FROM login_history WHERE username = ? AND date = ?", (user, day))
            result = cursor.fetchone()[0]
            if result:
                time_str = result.split(" ")[1][:5]
                cutoff = late_cutoffs.get(day)
                row["days"][day] = {"time": time_str, "late": cutoff is not None and time_str > cutoff, "manual": False}
            else:
                cursor.execute("SELECT status FROM attendance_override WHERE username = ? AND date = ?", (user, day))
                override = cursor.fetchone()
                if override and override[0] == "present":
                    row["days"][day] = {"time": "12:00", "late": False, "manual": True}
                else:
                    row["days"][day] = None

        total_days = len(days)
        present_days = sum(1 for d in days if row["days"][d])
        row["attendance_pct"] = round((present_days / total_days) * 100) if total_days else 0
        attendance.append(row)

    conn.close()
    return days, attendance


def get_low_attendance_learners(limit=10):
    days = get_last_21_days()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT date FROM excluded_dates WHERE group_name IS NULL")
    excluded = {row[0] for row in cursor.fetchall()}
    days = [d for d in days if d not in excluded]

    cursor.execute("SELECT username, full_name FROM users WHERE role = 'student'")
    learners = cursor.fetchall()
    results = []
    for username, full_name in learners:
        present = 0
        for day in days:
            cursor.execute("SELECT 1 FROM login_history WHERE username = ? AND date = ?", (username, day))
            if cursor.fetchone():
                present += 1
                continue
            cursor.execute("SELECT status FROM attendance_override WHERE username = ? AND date = ?", (username, day))
            override = cursor.fetchone()
            if override and override[0] == "present":
                present += 1
        results.append((full_name or username, len(days) - present))

    conn.close()
    results.sort(key=lambda x: x[1], reverse=True)
    return results[:limit]


# ── Marking helper ────────────────────────────────────────────────────────────

def mark_file(filepath, marking_script):
    if not marking_script:
        return {"task_name": "Unknown", "score": 0, "total": 0, "percentage": 0, "results": [],
                "error": "No marking script assigned to this task. Please contact your teacher."}
    try:
        module = importlib.import_module(f"marking.tasks.{marking_script}")
        return module.mark(filepath)
    except ModuleNotFoundError:
        return {"task_name": marking_script, "score": 0, "total": 0, "percentage": 0, "results": [],
                "error": f"Marking script '{marking_script}' not found. Please contact your teacher."}


def get_marking_scripts():
    tasks_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "marking", "tasks")
    scripts = []
    if os.path.exists(tasks_dir):
        for f in sorted(os.listdir(tasks_dir)):
            if f.endswith(".py") and f != "__init__.py":
                scripts.append(f[:-3])
    return scripts
