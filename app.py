from flask import Flask, request, redirect, url_for, render_template, session, flash
from markupsafe import escape
from datetime import datetime, timedelta
import threading
import time
import os
import sqlite3
import random
from flask import send_file
import pandas as pd
import io
from io import BytesIO

TIMEOUT = 60

def update_active_user(username):
    """Update the last seen time for a user in the active_users dict"""
    with lock:
        active_users[username] = datetime.now()

def get_last_21_days():
    days = []
    current = datetime.now().date()
    term_days = get_all_term_days()  # empty set if no terms configured
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
    term_days = get_all_term_days()  # empty set if no terms configured
    limit = 0

    while len(days) < 7 and limit < 365:
        s = current.strftime("%Y-%m-%d")
        if current.weekday() < 5 and (not term_days or s in term_days):
            days.append(s)
        current -= timedelta(days=1)
        limit += 1

    return list(reversed(days))

# 🔹 Database setup
DB_NAME = "school.db"

def get_db():
    return sqlite3.connect(DB_NAME)


def get_term_dates():
    """Return all 4 terms as a dict {1: {start, end}, ...}."""
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
    """Return (start, end) of the currently active term, or None."""
    today = datetime.now().date().isoformat()
    for t in get_term_dates().values():
        if t["start"] and t["end"] and t["start"] <= today <= t["end"]:
            return t["start"], t["end"]
    return None


def get_all_term_days():
    """Return a set of all weekdays that fall within any configured term (up to today)."""
    today = datetime.now().date().isoformat()
    days = set()
    for t in get_term_dates().values():
        if t["start"] and t["end"]:
            current = datetime.strptime(t["start"], "%Y-%m-%d").date()
            end = min(datetime.strptime(t["end"], "%Y-%m-%d").date(),
                      datetime.now().date())
            while current <= end:
                if current.weekday() < 5:
                    days.add(current.strftime("%Y-%m-%d"))
                current += timedelta(days=1)
    return days


def init_db():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        subject TEXT,
        task TEXT,
        score INTEGER,
        feedback TEXT,
        timestamp TEXT
    )
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS weaknesses (
        username TEXT,
        skill TEXT,
        count INTEGER,
        PRIMARY KEY (username, skill)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY,
        role TEXT,
        last_active TEXT,
        full_name TEXT,
        group_name TEXT,
        teacher_username TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS group_teachers (
        group_name TEXT PRIMARY KEY,
        teacher_username TEXT
    )
    """)

    # Migration: add direct teacher assignment to users if missing
    try:
        cursor.execute("PRAGMA table_info(users)")
        user_cols = [c[1] for c in cursor.fetchall()]
        if "teacher_username" not in user_cols:
            cursor.execute("ALTER TABLE users ADD COLUMN teacher_username TEXT")
            print("Migration: added teacher_username column to users")
    except Exception as e:
        print(f"Note: users migration check: {e}")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS login_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        login_time TEXT,
        date TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS attendance_override (
        username TEXT,
        date TEXT,
        status TEXT,  -- 'present' or 'absent'
        PRIMARY KEY (username, date)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS excluded_dates (
        date TEXT,
        group_name TEXT,  -- NULL for global exclusions, specific group name for group-specific
        reason TEXT,
        created_by TEXT,
        created_at TEXT,
        PRIMARY KEY (date, group_name)
    )
    """)

    # Migration: Handle old table structure
    try:
        cursor.execute("PRAGMA table_info(excluded_dates)")
        columns = cursor.fetchall()
        column_names = [col[1] for col in columns]
        
        if 'group_name' not in column_names:
            # Old table structure exists, migrate it
            print("Migrating excluded_dates table...")
            
            # Create new table with proper structure
            cursor.execute("""
            CREATE TABLE excluded_dates_new (
                date TEXT,
                group_name TEXT,
                reason TEXT,
                created_by TEXT,
                created_at TEXT,
                PRIMARY KEY (date, group_name)
            )
            """)
            
            # Copy old data (assuming old structure was: date, reason, created_by, created_at)
            cursor.execute("""
            INSERT INTO excluded_dates_new (date, group_name, reason, created_by, created_at)
            SELECT date, NULL, reason, created_by, created_at FROM excluded_dates
            """)
            
            # Replace old table
            cursor.execute("DROP TABLE excluded_dates")
            cursor.execute("ALTER TABLE excluded_dates_new RENAME TO excluded_dates")
            print("Migration completed successfully")
            
    except Exception as e:
        print(f"Note: Migration check completed with: {e}")
        # Continue anyway - table should exist now

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS activities (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        action TEXT,
        timestamp TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS subjects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE,
        created_by TEXT,
        created_at TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS theory_tests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        subject TEXT,
        assign_date TEXT,  -- YYYY-MM-DD
        time_limit INTEGER,
        allow_multiple INTEGER DEFAULT 0,
        max_attempts INTEGER DEFAULT 1,
        show_answers INTEGER DEFAULT 1,
        created_by TEXT,
        created_at TEXT,
        is_active INTEGER DEFAULT 0
    )
    """)

    # Migration: add assign_date if missing (idempotent)
    try:
        cursor.execute("PRAGMA table_info(theory_tests)")
        cols = [c[1] for c in cursor.fetchall()]
        if "assign_date" not in cols:
            cursor.execute("ALTER TABLE theory_tests ADD COLUMN assign_date TEXT")
            print("Migration: added assign_date column to theory_tests")
    except Exception as e:
        print(f"Note: theory_tests assign_date migration: {e}")

    # Migration: remove group_name column from theory_tests if present,
    # and add allow_multiple, max_attempts, show_answers if missing
    try:
        cursor.execute("PRAGMA table_info(theory_tests)")
        cols = [c[1] for c in cursor.fetchall()]
        if "group_name" in cols:
            cursor.execute("""
                CREATE TABLE theory_tests_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT, subject TEXT, time_limit INTEGER,
                    allow_multiple INTEGER DEFAULT 0,
                    max_attempts INTEGER DEFAULT 1,
                    show_answers INTEGER DEFAULT 1,
                    created_by TEXT, created_at TEXT, is_active INTEGER DEFAULT 0
                )
            """)
            cursor.execute("INSERT INTO theory_tests_new (id,title,subject,time_limit,created_by,created_at,is_active) SELECT id,title,subject,time_limit,created_by,created_at,is_active FROM theory_tests")
            cursor.execute("DROP TABLE theory_tests")
            cursor.execute("ALTER TABLE theory_tests_new RENAME TO theory_tests")
            print("Migration: removed group_name from theory_tests")
        else:
            if "allow_multiple" not in cols:
                cursor.execute("ALTER TABLE theory_tests ADD COLUMN allow_multiple INTEGER DEFAULT 0")
            if "max_attempts" not in cols:
                cursor.execute("ALTER TABLE theory_tests ADD COLUMN max_attempts INTEGER DEFAULT 1")
            if "show_answers" not in cols:
                cursor.execute("ALTER TABLE theory_tests ADD COLUMN show_answers INTEGER DEFAULT 1")
    except Exception as e:
        print(f"Note: theory_tests migration: {e}")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS theory_test_groups (
        test_id INTEGER,
        group_name TEXT,
        PRIMARY KEY (test_id, group_name),
        FOREIGN KEY (test_id) REFERENCES theory_tests (id)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS theory_questions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        test_id INTEGER,
        question_text TEXT,
        question_type TEXT,
        marks INTEGER DEFAULT 1,
        order_index INTEGER DEFAULT 0,
        FOREIGN KEY (test_id) REFERENCES theory_tests (id)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS theory_options (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        question_id INTEGER,
        option_text TEXT,
        is_correct INTEGER DEFAULT 0,
        match_pair TEXT,
        FOREIGN KEY (question_id) REFERENCES theory_questions (id)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS theory_submissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        test_id INTEGER,
        username TEXT,
        score INTEGER,
        total INTEGER,
        percentage INTEGER,
        submitted_at TEXT,
        FOREIGN KEY (test_id) REFERENCES theory_tests (id)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS theory_answers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        submission_id INTEGER,
        question_id INTEGER,
        answer_text TEXT,
        is_correct INTEGER DEFAULT 0,
        marks_awarded INTEGER DEFAULT 0,
        FOREIGN KEY (submission_id) REFERENCES theory_submissions (id),
        FOREIGN KEY (question_id) REFERENCES theory_questions (id)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        subject_id INTEGER,
        name TEXT,
        assign_date TEXT,
        marking_script TEXT,
        theory_test_id INTEGER,
        task_type TEXT DEFAULT 'practical',
        allow_multiple INTEGER DEFAULT 0,
        max_attempts INTEGER DEFAULT 1,
        is_active INTEGER DEFAULT 1,
        created_by TEXT,
        created_at TEXT,
        FOREIGN KEY (subject_id) REFERENCES subjects (id)
    )
    """)

    # Migration: add columns to tasks if missing
    try:
        cursor.execute("PRAGMA table_info(tasks)")
        columns = [col[1] for col in cursor.fetchall()]
        if "marking_script" not in columns:
            cursor.execute("ALTER TABLE tasks ADD COLUMN marking_script TEXT")
            print("Migration: added marking_script column to tasks")
        if "theory_test_id" not in columns:
            cursor.execute("ALTER TABLE tasks ADD COLUMN theory_test_id INTEGER")
            print("Migration: added theory_test_id column to tasks")
        if "task_type" not in columns:
            cursor.execute("ALTER TABLE tasks ADD COLUMN task_type TEXT DEFAULT 'practical'")
            print("Migration: added task_type column to tasks")
        if "allow_multiple" not in columns:
            cursor.execute("ALTER TABLE tasks ADD COLUMN allow_multiple INTEGER DEFAULT 0")
            print("Migration: added allow_multiple column to tasks")
        if "max_attempts" not in columns:
            cursor.execute("ALTER TABLE tasks ADD COLUMN max_attempts INTEGER DEFAULT 1")
            print("Migration: added max_attempts column to tasks")
        if "is_active" not in columns:
            cursor.execute("ALTER TABLE tasks ADD COLUMN is_active INTEGER DEFAULT 1")
        
        if "question_text" not in columns:
            cursor.execute("ALTER TABLE tasks ADD COLUMN question_text TEXT")
            print("Migration: added question_text column to tasks")

        if "sample_file" not in columns:
            cursor.execute("ALTER TABLE tasks ADD COLUMN sample_file BLOB")
            print("Migration: added sample_file BLOB column to tasks")

        if "sample_file_name" not in columns:
            cursor.execute("ALTER TABLE tasks ADD COLUMN sample_file_name TEXT")
            print("Migration: added sample_file_name column to tasks")
    except Exception as e:
        print(f"Note: tasks migration check: {e}")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS learner_notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        note TEXT,
        flag TEXT,
        created_by TEXT,
        created_at TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS result_removals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        task_type TEXT,
        subject TEXT,
        task_name TEXT,
        test_id INTEGER,
        removed_by TEXT,
        reason TEXT,
        removed_at TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS task_groups (
        task_id INTEGER,
        group_name TEXT,
        PRIMARY KEY (task_id, group_name),
        FOREIGN KEY (task_id) REFERENCES tasks (id)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS task_teachers (
        task_id INTEGER,
        teacher_username TEXT,
        PRIMARY KEY (task_id, teacher_username),
        FOREIGN KEY (task_id) REFERENCES tasks (id)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS theory_test_teachers (
        test_id INTEGER,
        teacher_username TEXT,
        PRIMARY KEY (test_id, teacher_username),
        FOREIGN KEY (test_id) REFERENCES theory_tests (id)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS term_dates (
        term INTEGER PRIMARY KEY,  -- 1, 2, 3, or 4
        start_date TEXT,
        end_date TEXT
    )
    """)

    # Seed initial subjects if empty
    cursor.execute("SELECT COUNT(*) FROM subjects")
    subjects_count = cursor.fetchone()[0]
    is_new_db = subjects_count == 0
    if is_new_db:
        initial_subjects = ["Word", "Excel", "Access", "HTML"]
        for subj in initial_subjects:
            cursor.execute("INSERT INTO subjects (name, created_by, created_at) VALUES (?, ?, ?)",
                           (subj, "system", datetime.now().isoformat()))

    # Seed initial tasks only for a fresh database
    cursor.execute("SELECT COUNT(*) FROM tasks")
    if cursor.fetchone()[0] == 0 and is_new_db:
        cursor.execute("SELECT id, name FROM subjects")
        subjects = cursor.fetchall()
        today = datetime.now().date().isoformat()
        for subj_id, subj_name in subjects:
            for i in range(1, 4):
                task_name = f"Task {i}"
                cursor.execute("INSERT INTO tasks (subject_id, name, assign_date, created_by, created_at) VALUES (?, ?, ?, ?, ?)",
                               (subj_id, task_name, today, "system", datetime.now().isoformat()))
                task_id = cursor.lastrowid
                # Assign to all groups
                cursor.execute("SELECT DISTINCT group_name FROM users WHERE group_name IS NOT NULL")
                groups = cursor.fetchall()
                for group_row in groups:
                    cursor.execute("INSERT INTO task_groups (task_id, group_name) VALUES (?, ?)", (task_id, group_row[0]))

    conn.commit()
    conn.close()

def get_user_role(username):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT role FROM users WHERE username = ?", (username,))
    result = cursor.fetchone()

    conn.close()

    return result[0] if result else "student"  # default = student

def log_login(username):
    conn = get_db()
    cursor = conn.cursor()

    now = datetime.now()

    cursor.execute("""
    INSERT INTO login_history (username, login_time, date)
    VALUES (?, ?, ?)
    """, (username, str(now), now.strftime("%Y-%m-%d")))

    conn.commit()
    conn.close()

def log_activity(username, action):
    conn = get_db()
    cursor = conn.cursor()

    now = datetime.now().isoformat()

    cursor.execute("""
    INSERT INTO activities (username, action, timestamp)
    VALUES (?, ?, ?)
    """, (username, action, now))

    conn.commit()
    conn.close()

def create_user_if_not_exists(username):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
    INSERT INTO users (username, role, last_active)
    VALUES (?, 'student', ?)
    ON CONFLICT(username) DO NOTHING
    """, (username, str(datetime.now())))

    conn.commit()
    conn.close()

def update_weakness(username, skills):
    conn = get_db()
    cursor = conn.cursor()

    for skill in skills:
        cursor.execute("""
        INSERT INTO weaknesses (username, skill, count)
        VALUES (?, ?, 1)
        ON CONFLICT(username, skill)
        DO UPDATE SET count = count + 1
        """, (username, skill))

    conn.commit()
    conn.close()

def get_weaknesses(username):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT skill, count
    FROM weaknesses
    WHERE username = ?
    ORDER BY count DESC
    LIMIT 5
    """, (username,))

    results = cursor.fetchall()
    conn.close()

    return results

def save_result(username, subject, task, score, feedback):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
    INSERT INTO results (username, subject, task, score, feedback, timestamp)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (username, subject, task, score, feedback, str(datetime.now())))

    conn.commit()
    conn.close()

def mark_file(filepath, marking_script):
    """
    Route a submitted file to the correct task marker using the
    marking_script name stored on the task in the database.
    """
    import importlib
    if not marking_script:
        return {
            "task_name": "Unknown Task",
            "score": 0,
            "total": 0,
            "percentage": 0,
            "results": [],
            "error": "No marking script assigned to this task. Please contact your teacher."
        }
    try:
        module = importlib.import_module(f"marking.tasks.{marking_script}")
        return module.mark(filepath)
    except ModuleNotFoundError:
        return {
            "task_name": marking_script,
            "score": 0,
            "total": 0,
            "percentage": 0,
            "results": [],
            "error": f"Marking script '{marking_script}' not found. Please contact your teacher."
        }

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'dev-key-change-in-prod')

@app.context_processor
def inject_session_user():
    from flask import session as _s
    uname = _s.get('username', '')
    role = ''
    if uname:
        try:
            role = get_user_role(uname)
        except Exception:
            pass
    return dict(session_username=uname, session_role=role)


# Store active users in memory
active_users = {}
lock = threading.Lock()

def get_recent_results(username):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT subject, task, score
    FROM results
    WHERE username = ?
    ORDER BY id DESC
    LIMIT 5
    """, (username,))

    results = cursor.fetchall()
    conn.close()

    return results

def get_student_dashboard_data(username):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT subject, ROUND(AVG(score), 1)
    FROM results
    WHERE username = ?
    GROUP BY subject
    """, (username,))
    subject_averages = cursor.fetchall()

    cursor.execute("""
    SELECT ROUND(AVG(score), 1)
    FROM results
    WHERE username = ?
    """, (username,))

    result = cursor.fetchone()
    overall_avg = result[0] if result and result[0] is not None else 0

    cursor.execute("""
    SELECT subject, task, score
    FROM results
    WHERE username = ?
    ORDER BY id DESC
    LIMIT 5
    """, (username,))
    recent_results = cursor.fetchall()

    conn.close()

    return (
        subject_averages or [],
        overall_avg,
        recent_results or []
    )

def get_overall_average(username):
    conn = get_db()
    cursor = conn.cursor()

    
    cursor.execute("""
    SELECT AVG(score)
    FROM results
    WHERE username = ?
    """, (username,))

    result = cursor.fetchone()
    conn.close()

    return round(result[0], 1) if result[0] else 0

def get_low_attendance_learners(limit=10, groups=None, teacher_username=None):
    days = get_last_21_days()
    conn = get_db()
    cursor = conn.cursor()

    # Get excluded dates (global only for cross-group summary)
    cursor.execute("SELECT date FROM excluded_dates WHERE group_name IS NULL")
    excluded = {row[0] for row in cursor.fetchall()}
    days = [d for d in days if d not in excluded]

    if teacher_username:
        cursor.execute(
            "SELECT username, full_name FROM users WHERE role = 'student' AND teacher_username = ?",
            (teacher_username,))
    elif groups:
        placeholders = ",".join("?" for _ in groups)
        cursor.execute(f"SELECT username, full_name FROM users WHERE role = 'student' AND group_name IN ({placeholders})", groups)
    else:
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

        absent = len(days) - present
        results.append((full_name or username, absent))

    conn.close()
    results.sort(key=lambda x: x[1], reverse=True)
    return results[:limit]


def get_teachers():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT username, full_name FROM users WHERE role = 'teacher' ORDER BY full_name")
    teachers = cursor.fetchall()
    conn.close()
    return teachers


def get_marking_scripts():
    """Return a list of available marking script names from marking/tasks/."""
    tasks_dir = os.path.join(os.path.dirname(__file__), "marking", "tasks")
    scripts = []
    if os.path.exists(tasks_dir):
        for f in sorted(os.listdir(tasks_dir)):
            if f.endswith(".py") and f != "__init__.py":
                scripts.append(f[:-3])  # strip .py
    return scripts

def get_groups(username=None):
    conn = get_db()
    cursor = conn.cursor()

    if username:
        role = get_user_role(username)
        if role == 'teacher':
            group_set = set()
            cursor.execute("SELECT group_name FROM group_teachers WHERE teacher_username = ?", (username,))
            group_set.update(g[0] for g in cursor.fetchall() if g[0])
            cursor.execute("SELECT DISTINCT group_name FROM users WHERE role = 'student' AND teacher_username = ? AND group_name IS NOT NULL", (username,))
            group_set.update(g[0] for g in cursor.fetchall() if g[0])
            conn.close()
            return sorted(group_set)

    cursor.execute("SELECT DISTINCT group_name FROM users WHERE group_name IS NOT NULL")
    groups = [g[0] for g in cursor.fetchall()]

    conn.close()
    return groups


def add_learner_note_entry(cursor, username, note, created_by, flag=""):
    cursor.execute("""
        INSERT INTO learner_notes (username, note, flag, created_by, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (username, note, flag, created_by, datetime.now().isoformat()))


def get_group_late_threshold(group, date):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT MIN(login_time)
    FROM login_history
    WHERE date = ?
      AND username IN (
          SELECT username FROM users WHERE group_name = ?
      )
    """, (date, group))
    min_login = cursor.fetchone()[0]
    conn.close()

    if not min_login:
        return None

    try:
        min_dt = datetime.fromisoformat(min_login)
    except ValueError:
        min_dt = datetime.strptime(min_login, "%Y-%m-%d %H:%M:%S")

    late_cutoff = min_dt + timedelta(minutes=6)
    return late_cutoff.strftime("%H:%M")


def is_attendance_editable(date_str, role='teacher'):
    """Check if attendance for a date can be edited (not locked after 10 days)."""
    if role == 'admin':  # Admins can always edit
        return True
    try:
        date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
        days_diff = (datetime.now().date() - date_obj).days
        return days_diff <= 10
    except ValueError:
        return False  # Invalid date, treat as locked


def get_attendance_data(group, start_date=None, end_date=None, teacher_username=None):
    conn = get_db()
    cursor = conn.cursor()

    # If no dates provided, use active term range or fall back to last 7 days
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
        # Generate business days (Mon-Fri) between start_date and end_date
        days = []
        current = datetime.strptime(start_date, "%Y-%m-%d").date()
        end = datetime.strptime(end_date, "%Y-%m-%d").date()
        while current <= end:
            if current.weekday() < 5:
                days.append(current.strftime("%Y-%m-%d"))
            current += timedelta(days=1)

    # Remove future dates
    today_str = datetime.now().date().isoformat()
    days = [day for day in days if day <= today_str]

    # Filter out excluded dates
    cursor.execute("""
    SELECT date FROM excluded_dates 
    WHERE group_name IS NULL OR group_name = ?
    """, (group,))
    excluded_dates = {row[0] for row in cursor.fetchall()}
    days = [day for day in days if day not in excluded_dates]

    query = """
    SELECT username, full_name, group_name
    FROM users
    WHERE group_name = ? AND role = 'student'
    """
    params = [group]
    if teacher_username:
        query += " AND teacher_username = ?"
        params.append(teacher_username)
    
    cursor.execute(query, params)
    learners = cursor.fetchall()

    attendance = []

    # Precompute late cutoff per day for the group
    late_cutoffs = {}
    for day in days:
        late_cutoffs[day] = get_group_late_threshold(group, day)

    for user, name, user_group_name in learners:
        row = {
            "username": user,
            "name": name,
            "group": user_group_name,
            "days": {}
        }

        for day in days:

            # 🔹 FIRST: check real login
            cursor.execute("""
            SELECT MIN(login_time)
            FROM login_history
            WHERE username = ? AND date = ?
            """, (user, day))

            result = cursor.fetchone()[0]

            if result:
                # ✅ REAL LOGIN ALWAYS WINS (they actually logged in)
                time_str = result.split(" ")[1][:5]
                cutoff = late_cutoffs.get(day)
                is_late = cutoff is not None and time_str > cutoff

                row["days"][day] = {
                    "time": time_str,
                    "late": is_late,
                    "manual": False
                }

            else:
                # 🔹 ONLY THEN check override (they didn't log in, but can be manually set)
                cursor.execute("""
                SELECT status FROM attendance_override
                WHERE username = ? AND date = ?
                """, (user, day))

                override = cursor.fetchone()

                if override:
                    if override[0] == "present":
                        row["days"][day] = {
                            "time": "12:00",
                            "late": False,
                            "manual": True
                        }
                    else:
                        row["days"][day] = None
                else:
                    row["days"][day] = None


        # 🔹 Attendance %
        total_days = len(days)
        present_days = sum(1 for d in days if row["days"][d])
        row["attendance_pct"] = round((present_days / total_days) * 100) if total_days else 0

        attendance.append(row)

    conn.close()
    return days, attendance

def import_users_from_excel():
    """Import users from Excel file Users/grade12.xlsx"""
    try:
        df = pd.read_excel("Users/grade12.xlsx")
        
        conn = get_db()
        cursor = conn.cursor()
        
        imported_count = 0
        updated_count = 0
        
        for _, row in df.iterrows():
            username = str(row["username"]).strip().upper()
            full_name = str(row["full_name"]).strip()
            group_name = str(row["group"]).strip()
            
            # Check if user already exists
            cursor.execute("SELECT username FROM users WHERE username = ?", (username,))
            existing = cursor.fetchone()
            
            cursor.execute("""
            INSERT INTO users (username, full_name, group_name, role)
            VALUES (?, ?, ?, 'student')
            ON CONFLICT(username) DO UPDATE SET
                full_name = excluded.full_name,
                group_name = excluded.group_name
            """, (username, full_name, group_name))
            
            if existing:
                updated_count += 1
            else:
                imported_count += 1
        
        conn.commit()
        conn.close()
        
        return f"Successfully imported {imported_count} new users and updated {updated_count} existing users."
    
    except FileNotFoundError:
        return "Error: Users/grade12.xlsx file not found."
    except Exception as e:
        return f"Error importing users: {str(e)}"

# 🔹 Login Page
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip().upper()

        if username and len(username) <= 20 and username.isalnum():
            session["username"] = username

            create_user_if_not_exists(username)
            update_last_active(username)
            log_login(username)
            log_activity(username, "logged in")

            with lock:
                active_users[username] = datetime.now()

            role = get_user_role(username)
            if role in ["teacher", "admin"]:
                return redirect(url_for("teacher_dashboard"))
            return redirect(url_for("student_dashboard"))
        else:
            return "Invalid username", 400

    return render_template("login.html")


# 🔹 Heartbeat (updates activity)
@app.route("/heartbeat/<username>")
def heartbeat(username):
    with lock:
        if username in active_users:
            active_users[username] = datetime.now()
            update_last_active(username)
        else:
            return "Invalid", 401
    return "OK"


def cleanup_thread():
    while True:
        now = datetime.now()
        with lock:
            to_remove = []
            for user, last_seen in list(active_users.items()):
                if now - last_seen > timedelta(seconds=TIMEOUT):
                    to_remove.append(user)
            for user in to_remove:
                del active_users[user]
        time.sleep(30)


@app.route("/student_dashboard")
def student_dashboard():
    username = session.get("username")
    if not username:
        return redirect(url_for("login"))

    update_active_user(username)
    role = get_user_role(username)

    # Teachers go to teacher dashboard
    if role in ["teacher", "admin"]:
        return redirect(url_for("teacher_dashboard"))

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT full_name, group_name FROM users WHERE username = ?", (username,))
    user_row = cursor.fetchone()
    display_name = user_row[0] if user_row and user_row[0] else username
    user_group = user_row[1] if user_row else None

    # ─ Academic (best score per task)
    cursor.execute("""
        SELECT subject, ROUND(AVG(best_score),1)
        FROM (SELECT subject, task, MAX(score) as best_score FROM results WHERE username = ? GROUP BY subject, task)
        GROUP BY subject
    """, (username,))
    subject_avgs = cursor.fetchall()

    cursor.execute("""
        SELECT ROUND(AVG(best_score),1)
        FROM (SELECT subject, task, MAX(score) as best_score FROM results WHERE username = ? GROUP BY subject, task)
    """, (username,))
    overall_row = cursor.fetchone()
    practical_avg = overall_row[0] if overall_row and overall_row[0] else 0

    cursor.execute("""
        SELECT ROUND(AVG(best_pct),1)
        FROM (SELECT test_id, MAX(percentage) as best_pct FROM theory_submissions WHERE username = ? GROUP BY test_id)
    """, (username,))
    theory_avg_row = cursor.fetchone()
    theory_avg = theory_avg_row[0] if theory_avg_row and theory_avg_row[0] else None

    if practical_avg and theory_avg:
        overall_avg = round((practical_avg + theory_avg) / 2, 1)
    else:
        overall_avg = practical_avg or theory_avg or 0

    cursor.execute("""
        SELECT subject, task, MAX(score) as score, feedback, MAX(timestamp) as timestamp
        FROM results WHERE username = ? GROUP BY subject, task ORDER BY timestamp DESC LIMIT 5
    """, (username,))
    recent_results = cursor.fetchall()

    cursor.execute("""
        SELECT tt.subject, tt.title, MAX(ts.percentage) as best_pct, MAX(ts.submitted_at) as latest
        FROM theory_submissions ts
        JOIN theory_tests tt ON ts.test_id = tt.id
        WHERE ts.username = ? GROUP BY ts.test_id ORDER BY latest DESC LIMIT 5
    """, (username,))
    recent_theory_results = cursor.fetchall()

    cursor.execute("""
        SELECT tt.subject, ROUND(AVG(best_pct),1)
        FROM (SELECT test_id, MAX(percentage) as best_pct FROM theory_submissions WHERE username = ? GROUP BY test_id) b
        JOIN theory_tests tt ON b.test_id = tt.id
        WHERE tt.subject IS NOT NULL AND tt.subject != ''
        GROUP BY tt.subject
    """, (username,))
    theory_subject_avgs = cursor.fetchall()

    # ─ Attendance (last 7 working days)
    days = get_last_7_days()
    cursor.execute("SELECT date FROM excluded_dates WHERE group_name IS NULL OR group_name = ?", (user_group,))
    excluded = {r[0] for r in cursor.fetchall()}
    days = [d for d in days if d not in excluded]

    att_history = []
    cutoffs = {d: get_group_late_threshold(user_group, d) for d in days} if user_group else {}
    for day in days:
        cursor.execute("SELECT MIN(login_time) FROM login_history WHERE username = ? AND date = ?", (username, day))
        lt = cursor.fetchone()[0]
        if lt:
            t = lt.split(" ")[1][:5]
            late = cutoffs.get(day) is not None and t > cutoffs[day]
            att_history.append({"date": day, "status": "present", "late": late, "time": t})
        else:
            cursor.execute("SELECT status FROM attendance_override WHERE username = ? AND date = ?", (username, day))
            ov = cursor.fetchone()
            if ov and ov[0] == "present":
                att_history.append({"date": day, "status": "present", "late": False, "time": "12:00"})
            else:
                att_history.append({"date": day, "status": "absent", "late": False, "time": ""})

    present = sum(1 for d in att_history if d["status"] == "present")
    att_pct = round((present / len(att_history)) * 100) if att_history else 0

    # ─ Practical subjects and tasks for inline panel
    today = datetime.now().date().isoformat()
    cursor.execute("SELECT id, name FROM subjects ORDER BY name")
    all_subjects = cursor.fetchall()
    subjects_with_tasks = []
    for subj_id, subj_name in all_subjects:
        cursor.execute("""
            SELECT t.id, t.name
            FROM tasks t
            JOIN task_groups tg ON t.id = tg.task_id
            WHERE t.subject_id = ? AND tg.group_name = ? AND t.assign_date <= ?
            AND t.task_type = 'practical' AND t.is_active = 1
            ORDER BY t.name
        """, (subj_id, user_group, today))
        tasks_for_subj = cursor.fetchall()
        if tasks_for_subj:
            subjects_with_tasks.append({'id': subj_id, 'name': subj_name, 'tasks': tasks_for_subj})

    # ─ Missing tasks (practical + theory) assigned to the student's group
    today = datetime.now().date().isoformat()

    # Practical missing tasks
    cursor.execute("""
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
    """, (user_group, today, username))
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

    # Need subject_id for upload link
    if practical_missing_assignments:
        task_ids = [a["task_id"] for a in practical_missing_assignments]
        placeholders = ",".join(["?"] * len(task_ids))
        cursor.execute(f"""
            SELECT id, subject_id
            FROM tasks
            WHERE id IN ({placeholders})
        """, task_ids)
        id_to_subject = {row[0]: row[1] for row in cursor.fetchall()}

        for a in practical_missing_assignments:
            a["subject_id"] = id_to_subject.get(a["task_id"])
            if a["subject_id"] is not None:
                a["start_url"] = f"/upload/{username}/{a['subject_id']}/{a['task_id']}"

    # Theory missing tasks for the group (no submission by this student)
    cursor.execute("""
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
    """, (user_group, username))
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
    # Backward-compatible variable for the existing template placeholder
    missing_tasks = [(None, a['subject'], a['activity'], a['due'] or '') for a in missing_assignments if a['type']=='practical']

    # If template expects best-effort ordering, put practical first then theory.
    missing_assignments = practical_missing_assignments + theory_missing_assignments


    # ─ Weaknesses
    cursor.execute("SELECT skill, count FROM weaknesses WHERE username = ? ORDER BY count DESC LIMIT 5", (username,))
    weaknesses = cursor.fetchall()

    # ─ Recent feedback (non-empty)
    cursor.execute("""
        SELECT subject, task, feedback, timestamp
        FROM results WHERE username = ? AND feedback IS NOT NULL AND feedback != ''
        ORDER BY timestamp DESC LIMIT 3
    """, (username,))
    recent_feedback = cursor.fetchall()

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
        att_pct=att_pct,
        subjects_with_tasks=subjects_with_tasks,
        missing_assignments=missing_assignments,
        missing_tasks=missing_tasks,
        weaknesses=weaknesses,
        recent_feedback=recent_feedback
    )

@app.route("/auto_login")

def auto_login():
    username = request.args.get("username", "").strip().upper()

    if username and len(username) <= 20 and username.isalnum():
        session["username"] = username   # ✅ IMPORTANT

        create_user_if_not_exists(username)
        update_last_active(username)
        log_login(username)
        log_activity(username, "logged in")

        with lock:
            active_users[username] = datetime.now()

        role = get_user_role(username)
        if role in ["teacher", "admin"]:
            return redirect(url_for("teacher_dashboard"))
        return redirect(url_for("student_dashboard"))

    return "Invalid auto-login", 400

@app.route("/logout")
def logout():
    username = session.get("username")
    if not username:
        return redirect(url_for("login"))

    if username:
        with lock:
            active_users.pop(username, None)

    session.clear()   # ✅ IMPORTANT

    return redirect(url_for("login"))



# 🔹 Teacher View (see active users)
@app.route("/active")
def active():
    username = session.get("username")
    if not username:
        return redirect(url_for("login"))

    if not username:
        return redirect(url_for("login"))

    role = get_user_role(username)

    if role not in ["teacher", "admin"]:
        return "Access denied", 403

    now = datetime.now()

    # Remove inactive users
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

def update_last_active(username):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
    UPDATE users
    SET last_active = ?
    WHERE username = ?
    """, (str(datetime.now()), username))

    conn.commit()
    conn.close()

@app.route("/tasks/<int:task_id>/edit", methods=["GET", "POST"])
def edit_task(task_id):
    username = session.get("username")
    if not username or get_user_role(username) not in ["teacher", "admin"]:
        return "Access denied", 403

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT t.id, t.name, t.assign_date, t.marking_script, t.question_text, t.subject_id,
               t.sample_file, t.sample_file_name, t.allow_multiple, t.max_attempts
        FROM tasks t
        WHERE t.id = ? AND t.task_type = 'practical'
    """, (task_id,))
    task = cursor.fetchone()
    if not task:
        conn.close()
        return "Task not found", 404

    subject_id = task[5]

    if request.method == "POST":
        assign_date = request.form.get("assign_date")
        marking_script = request.form.get("marking_script")
        allow_multiple = 1 if request.form.get("allow_multiple") else 0
        max_attempts = int(request.form.get("max_attempts", 1)) if allow_multiple else 1
        groups = request.form.getlist("groups")

        question_text = request.form.get("question_text", "").strip()
        cursor.execute("""
            UPDATE tasks SET assign_date = ?, marking_script = ?, question_text = ?, allow_multiple = ?, max_attempts = ? WHERE id = ?
        """, (assign_date, marking_script, question_text, allow_multiple, max_attempts, task_id))

        cursor.execute("DELETE FROM task_groups WHERE task_id = ?", (task_id,))
        for g in groups:
            if g.strip():
                cursor.execute("INSERT INTO task_groups (task_id, group_name) VALUES (?, ?)", (task_id, g))

        cursor.execute("DELETE FROM task_teachers WHERE task_id = ?", (task_id,))
        teachers = request.form.getlist("teachers")
        for t in teachers:
            if t.strip():
                cursor.execute("INSERT INTO task_teachers (task_id, teacher_username) VALUES (?, ?)", (task_id, t))

        # Optional: replace sample file
        sample_file = request.files.get("sample_file")
        if sample_file and sample_file.filename:
            sample_bytes = sample_file.read()
            # keep original filename for downloading
            sample_filename = sample_file.filename
            cursor.execute(
                """UPDATE tasks
                   SET sample_file = ?, sample_file_name = ?
                   WHERE id = ?""",
                (sample_bytes, sample_filename, task_id)
            )

        conn.commit()
        conn.close()
        log_activity(username, f"edited task {task[1]}")
        return redirect(url_for("manage_tasks", subject_id=subject_id))

    # GET — load current groups and scripts
    cursor.execute("SELECT group_name FROM task_groups WHERE task_id = ?", (task_id,))
    current_groups = {row[0] for row in cursor.fetchall()}
    cursor.execute("SELECT teacher_username FROM task_teachers WHERE task_id = ?", (task_id,))
    current_teachers = {row[0] for row in cursor.fetchall()}
    all_groups = get_groups()
    available_scripts = get_marking_scripts()
    teachers = get_teachers()
    conn.close()

    script_options = '<option value="">-- No marking script --</option>'
    for s in available_scripts:
        selected = 'selected' if s == task[3] else ''
        script_options += f'<option value="{escape(s)}" {selected}>{escape(s)}</option>'

    teacher_checkboxes = ''
    for t in teachers:
        checked = 'checked' if t[0] in current_teachers else ''
        teacher_checkboxes += f'<label style="display:inline-flex;align-items:center;gap:5px;"><input type="checkbox" name="teachers" value="{escape(t[0])}" {checked}> {escape(t[1] or t[0])}</label>'

    return render_template(
        "edit_task.html",
        task=task,
        current_groups=current_groups,
        all_groups=all_groups,
        script_options=script_options,
        teacher_checkboxes=teacher_checkboxes
    )


@app.route("/tasks/<int:task_id>/toggle", methods=["POST"])
def toggle_task(task_id):
    username = session.get("username")
    if not username or get_user_role(username) not in ["teacher", "admin"]:
        return "Access denied", 403
    subject_id = request.form.get("subject_id")
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT is_active FROM tasks WHERE id = ?", (task_id,))
    row = cursor.fetchone()
    if row:
        new_state = 0 if row[0] else 1
        cursor.execute("UPDATE tasks SET is_active = ? WHERE id = ?", (new_state, task_id))
        conn.commit()
        state_label = "activated" if new_state else "deactivated"
        log_activity(username, f"{state_label} task {task_id}")
    conn.close()
    return redirect(url_for("manage_tasks", subject_id=subject_id))


@app.route("/tasks/<int:task_id>/clear_uploads", methods=["GET", "POST"])
def clear_task_uploads(task_id):

    """Serve a task's sample file stored in DB (BLOB)."""
    username = session.get("username")
    if not username:
        return "Unauthorized", 401

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT sample_file, sample_file_name
        FROM tasks
        WHERE id = ? AND task_type = 'practical'
        """,
        (task_id,)
    )
    row = cursor.fetchone()
    conn.close()

    if not row:
        return "Sample not found", 404

    sample_bytes, sample_name = row
    if not sample_bytes:
        return "No sample file uploaded", 404

    if not sample_name:
        sample_name = f"task_{task_id}_sample"

    ext = os.path.splitext(sample_name)[1].lower()

    # Import here to avoid issues if file is missing in some environments
    from io import BytesIO

    bio = BytesIO(sample_bytes)

    # Pick a reasonable mimetype
    mimetype = None
    if ext == ".docx":
        mimetype = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif ext == ".xlsx":
        mimetype = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif ext == ".html":
        mimetype = "text/html; charset=utf-8"

    from flask import send_file
    return send_file(
        bio,
        mimetype=mimetype,
        as_attachment=True,
        download_name=sample_name
    )


def clear_task_uploads_delete(task_id):
    username = session.get("username")
    if not username or get_user_role(username) not in ["teacher", "admin"]:
        return "Access denied", 403
    subject_id = request.form.get("subject_id")
    conn = get_db()
    cursor = conn.cursor()
    # Get subject and task name to match results table
    cursor.execute("""
        SELECT t.name, s.name FROM tasks t
        JOIN subjects s ON s.id = t.subject_id
        WHERE t.id = ?
    """, (task_id,))
    row = cursor.fetchone()
    if row:
        task_name, subject_name = row
        cursor.execute("""
            DELETE FROM results WHERE subject = ? AND task = ?
        """, (subject_name, task_name))
        conn.commit()
        log_activity(username, f"cleared uploads for {subject_name} {task_name}")
    conn.close()
    return redirect(url_for("manage_tasks", subject_id=subject_id))



@app.route("/upload/<username>/<subject_id>/<task_id>", methods=["GET", "POST"])
def upload(username, subject_id, task_id):
    # Verify the logged-in user is the one accessing
    session_user = session.get("username")
    if session_user != username:
        return "Unauthorized", 401

    # Update active user timestamp
    update_active_user(username)

    conn = get_db()
    cursor = conn.cursor()

    # Get subject name
    cursor.execute("SELECT name FROM subjects WHERE id = ?", (subject_id,))
    subject_row = cursor.fetchone()
    if not subject_row:
        conn.close()
        return "Subject not found", 404
    subject_name = subject_row[0]

    # Get task with assign_date, marking_script, submission rules, and is_active
    cursor.execute("SELECT name, assign_date, marking_script, question_text, allow_multiple, max_attempts, is_active FROM tasks WHERE id = ?", (task_id,))
    task_row = cursor.fetchone()
    if not task_row:
        conn.close()
        return "Task not found", 404
    task_name, assign_date, marking_script, question_text, allow_multiple, max_attempts, task_is_active = task_row

    # Block upload if task is deactivated (students only)
    user_role = get_user_role(username)
    if user_role not in ["teacher", "admin"] and not task_is_active:
        conn.close()
        return """
        <p><a href="/student_dashboard">← Back to Dashboard</a></p>
        <h2>Upload Closed</h2>
        <p style="color:#A4262C;">This task is currently not accepting uploads. Please contact your teacher.</p>
        """, 403
    cursor.execute("SELECT group_name FROM users WHERE username = ?", (username,))
    user_group_row = cursor.fetchone()
    user_group = user_group_row[0] if user_group_row else None

    # Check authorization
    if user_role not in ["teacher", "admin"]:
        # Students can only access if task is assigned to their group AND assign date has passed
        today = datetime.now().date().isoformat()
        cursor.execute("""
        SELECT COUNT(*) FROM task_groups
        WHERE task_id = ? AND group_name = ?
        """, (task_id, user_group))
        
        if cursor.fetchone()[0] == 0:
            conn.close()
            return "Access denied: Task not assigned to your group", 403
        
        if assign_date > today:
            conn.close()
            return "Access denied: Task is not yet available", 403

    if request.method == "POST":
        cursor.execute("SELECT COUNT(*) FROM results WHERE username = ? AND subject = ? AND task = ?", (username, subject_name, task_name))
        submission_count = cursor.fetchone()[0]

        if not allow_multiple and submission_count >= 1:
            conn.close()
            return "<p><a href=\"/student_dashboard\">← Back to Dashboard</a></p><h2>Upload Closed</h2><p style=\"color:#A4262C;\">This task allows only a single submission, and you have already submitted once.</p>", 403

        if allow_multiple and submission_count >= max_attempts:
            conn.close()
            return "<p><a href=\"/student_dashboard\">← Back to Dashboard</a></p><h2>Upload Closed</h2><p style=\"color:#A4262C;\">You have reached the maximum number of submissions for this task.</p>", 403

        file = request.files.get("file")

        if not file:
            conn.close()
            return "No file uploaded", 400

        temp_path = f"temp_{username}.xlsx"
        file.save(temp_path)

        try:
            result = mark_file(temp_path, marking_script)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

        if result["error"]:
            conn.close()
            return f"""
            <p><a href="/student_dashboard">← Back to Dashboard</a></p>
            <h2>Submission Error</h2>
            <p style="color:red;">{escape(result['error'])}</p>
            """

        # Build weak skills from wrong answers
        weak_skills = [r["question"] for r in result["results"] if not r["passed"]]
        update_weakness(username, weak_skills)
        save_result(username, subject_name, task_name, result["percentage"], ", ".join(weak_skills[:3]) or "Well done!")
        log_activity(username, f"submitted {subject_name} {task_name}")

        correct_items = [r for r in result["results"] if r["passed"]]
        wrong_items = [r for r in result["results"] if not r["passed"]]

        conn.close()
        return render_template(
            "upload_result.html",
            subject_name=subject_name,
            task_name=task_name,
            score=result["score"],
            total=result["total"],
            percentage=result["percentage"],
            correct_items=correct_items,
            wrong_items=wrong_items,
        )

    conn.close()

    # Include a student-safe sample download link if a sample file exists
    sample_link_html = ""
    cursor = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT sample_file, sample_file_name FROM tasks WHERE id = ? AND task_type = 'practical'",
            (task_id,),
        )
        row = cursor.fetchone()
        if row and row[0]:
            sample_name = row[1] or f"task_{task_id}_sample"
            sample_link_html = (
                f'<p><a href="/tasks/{task_id}/clear_uploads">📎 Download task sample</a> '
                f'({escape(sample_name)})</p>'
            )
    finally:
        try:
            if cursor:
                conn.close()
        except Exception:
            pass

    return render_template(
        "upload_task.html",
        subject_name=subject_name,
        task_name=task_name,
        question_text=question_text,
        sample_link_html=sample_link_html,
    )




@app.route("/subjects/<username>")
def subjects(username):
    if not session.get("username"):
        return redirect(url_for("login"))

    session_user = session.get("username")
    if session_user != username:
        return "Unauthorized", 401

    update_active_user(username)

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT id, name FROM subjects ORDER BY name")
    all_subjects = cursor.fetchall()
    conn.close()

    if not all_subjects:
        subject_links = "<p>No subjects available yet.</p>"
    else:
        subject_links = ""
        for subj_id, subj_name in all_subjects:
            subject_links += f'<a href="/tasks/{escape(username)}/{subj_id}">📁 {escape(subj_name)}</a><br>\n'

    return f"""
    <p><a href="/student_dashboard">← Back to Dashboard</a></p>
    <h2>📁 Practical Assignments</h2>
    {subject_links}
    """

@app.route("/tasks/<username>/<subject_id>")
def tasks(username, subject_id):
    if not session.get("username"):
        return redirect(url_for("login"))

    # Verify the logged-in user is the one accessing
    session_user = session.get("username")
    if session_user != username:
        return "Unauthorized", 401

    # Update active user timestamp
    update_active_user(username)

    conn = get_db()
    cursor = conn.cursor()

    # Get subject name
    cursor.execute("SELECT name FROM subjects WHERE id = ?", (subject_id,))
    subject_row = cursor.fetchone()
    if not subject_row:
        conn.close()
        return "Subject not found", 404
    subject_name = subject_row[0]

    # Get user role and group
    role = get_user_role(username)
    cursor.execute("SELECT group_name FROM users WHERE username = ?", (username,))
    group_row = cursor.fetchone()
    user_group = group_row[0] if group_row else None

    # Get tasks
    today = datetime.now().date().isoformat()
    if role in ["teacher", "admin"]:
        # Teachers/admins see all tasks
        cursor.execute("""
        SELECT t.id, t.name, t.assign_date
        FROM tasks t
        WHERE t.subject_id = ?
        ORDER BY t.assign_date, t.name
        """, (subject_id,))
    else:
        # Students see only assigned tasks that are due
        cursor.execute("""
        SELECT t.id, t.name, t.assign_date
        FROM tasks t
        JOIN task_groups tg ON t.id = tg.task_id
        WHERE t.subject_id = ? AND tg.group_name = ? AND t.assign_date <= ?
        ORDER BY t.assign_date, t.name
        """, (subject_id, user_group, today))

    all_tasks = cursor.fetchall()
    conn.close()

    if not all_tasks:
        task_links = "<p>No tasks available.</p>"
    else:
        task_links = ""
        for task_id, task_name, assign_date in all_tasks:
            task_links += f'<a href="/upload/{escape(username)}/{subject_id}/{task_id}">📄 {escape(task_name)}</a><br>\n'

    escaped_username = escape(username)
    return f"""
    <p><a href="/subjects/{escaped_username}">← Back to Subjects</a> | <a href="/student_dashboard">Back to Dashboard</a></p>
    <h2>{escape(subject_name).upper()} Tasks</h2>
    {task_links}
    """

@app.route("/view_as_student/<group_name>")
def view_as_student(group_name):
    admin_user = session.get("username")
    if not admin_user:
        return redirect(url_for("login"))
    if get_user_role(admin_user) not in ["teacher", "admin"]:
        return "Access denied", 403

    conn = get_db()
    cursor = conn.cursor()

    # Pick first student in the group as representative
    cursor.execute("""
        SELECT username, full_name, group_name FROM users
        WHERE group_name = ? AND role = 'student' LIMIT 1
    """, (group_name,))
    rep = cursor.fetchone()

    # Group student count
    cursor.execute("SELECT COUNT(*) FROM users WHERE group_name = ? AND role = 'student'", (group_name,))
    student_count = cursor.fetchone()[0]

    # All students in group
    cursor.execute("""
        SELECT username, full_name FROM users
        WHERE group_name = ? AND role = 'student' ORDER BY full_name
    """, (group_name,))
    students = cursor.fetchall()

    # Subject averages for the group
    cursor.execute("""
        SELECT r.subject, ROUND(AVG(r.score), 1)
        FROM results r
        JOIN users u ON r.username = u.username
        WHERE u.group_name = ?
        GROUP BY r.subject
    """, (group_name,))
    subject_avgs = cursor.fetchall()

    # Overall group average
    cursor.execute("""
        SELECT ROUND(AVG(r.score), 1)
        FROM results r
        JOIN users u ON r.username = u.username
        WHERE u.group_name = ?
    """, (group_name,))
    overall_row = cursor.fetchone()
    overall_avg = overall_row[0] if overall_row and overall_row[0] else 0

    # Recent submissions for the group
    cursor.execute("""
        SELECT u.full_name, r.subject, r.task, r.score, r.timestamp
        FROM results r
        JOIN users u ON r.username = u.username
        WHERE u.group_name = ?
        ORDER BY r.timestamp DESC LIMIT 10
    """, (group_name,))
    recent_results = cursor.fetchall()

    # Attendance last 7 days for the group
    days = get_last_7_days()
    cursor.execute("SELECT date FROM excluded_dates WHERE group_name IS NULL OR group_name = ?", (group_name,))
    excluded = {r[0] for r in cursor.fetchall()}
    days = [d for d in days if d not in excluded]

    att_summary = []
    for day in days:
        cursor.execute("""
            SELECT COUNT(DISTINCT username) FROM login_history
            WHERE date = ? AND username IN (
                SELECT username FROM users WHERE group_name = ? AND role = 'student'
            )
        """, (day, group_name))
        present = cursor.fetchone()[0]
        pct = round((present / student_count) * 100) if student_count else 0
        att_summary.append({"date": day, "present": present, "total": student_count, "pct": pct})

    # Missing tasks for the group
    today = datetime.now().date().isoformat()
    cursor.execute("""
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
    """, (group_name, today))
    missing_tasks = cursor.fetchall()

    # Top weaknesses for the group
    cursor.execute("""
        SELECT w.skill, SUM(w.count) as total
        FROM weaknesses w
        JOIN users u ON w.username = u.username
        WHERE u.group_name = ?
        GROUP BY w.skill ORDER BY total DESC LIMIT 5
    """, (group_name,))
    weaknesses = cursor.fetchall()

    # Theory test results for the group
    cursor.execute("""
        SELECT t.title, ROUND(AVG(s.percentage), 1), COUNT(DISTINCT s.username)
        FROM theory_submissions s
        JOIN theory_tests t ON s.test_id = t.id
        JOIN users u ON s.username = u.username
        WHERE u.group_name = ?
        GROUP BY t.id ORDER BY s.submitted_at DESC LIMIT 5
    """, (group_name,))
    theory_avgs = cursor.fetchall()

    conn.close()
    return render_template(
        "view_as_student.html",
        group_name=group_name,
        student_count=student_count,
        students=students,
        subject_avgs=subject_avgs,
        overall_avg=overall_avg,
        recent_results=recent_results,
        att_summary=att_summary,
        missing_tasks=missing_tasks,
        weaknesses=weaknesses,
        theory_avgs=theory_avgs
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

    # ─ Quick stats
    cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'student'")
    total_students = cursor.fetchone()[0]

    today = datetime.now().strftime("%Y-%m-%d")
    cursor.execute("SELECT COUNT(DISTINCT username) FROM login_history WHERE date = ?", (today,))
    active_today = cursor.fetchone()[0]

    days_21 = get_last_21_days()

    # ─ Group list
    groups = get_groups(username)

    group_filter_clause = ""
    group_filter_params = []
    if role == 'teacher':
        group_filter_clause = "AND u.teacher_username = ?"
        group_filter_params = [username]

        cursor.execute(f"""
            SELECT COUNT(*)
            FROM users u
            WHERE u.role = 'student'
            {group_filter_clause}
        """, group_filter_params)
        total_students = cursor.fetchone()[0]

        cursor.execute(f"""
            SELECT COUNT(DISTINCT lh.username)
            FROM login_history lh
            JOIN users u ON u.username = lh.username
            WHERE lh.date = ? AND u.role = 'student'
            {group_filter_clause}
        """, (today, *group_filter_params))
        active_today = cursor.fetchone()[0]
    else:
        cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'student'")
        total_students = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(DISTINCT username) FROM login_history WHERE date = ?", (today,))
        active_today = cursor.fetchone()[0]

    # ─ Group attendance summary + overall avg (uses same logic as attendance page)
    group_att = []
    total_present_all = 0
    total_slots_all = 0
    for g in groups:
        days_g, data_g = get_attendance_data(g, teacher_username=username if role == 'teacher' else None)
        g_count = len(data_g)
        if g_count and days_g:
            present = sum(1 for row in data_g for d in days_g if row['days'].get(d))
            slots = g_count * len(days_g)
            g_pct = round((present / slots) * 100)
            total_present_all += present
            total_slots_all += slots
        else:
            g_pct = 0
        group_att.append({"group": g, "students": g_count, "att_pct": g_pct})

    avg_att_pct = round((total_present_all / total_slots_all) * 100) if total_slots_all else 0

    # ─ Low attendance learners
    low_attendance = get_low_attendance_learners(10, None, username if role == 'teacher' else None)

    # ─ Combined risk score for learners
    cursor.execute(f"""
        SELECT u.username, u.full_name, u.group_name,
               ROUND(AVG(b.best_score), 1) as avg_score
        FROM users u
        LEFT JOIN (
            SELECT username, subject, task, MAX(score) as best_score
            FROM results GROUP BY username, subject, task
        ) b ON u.username = b.username
        WHERE u.role = 'student' {group_filter_clause}
        GROUP BY u.username
    """, group_filter_params)
    students = cursor.fetchall()

    risk_learners = []
    for uname, full_name, grp, avg_score in students:
        avg_score = avg_score or 0
        present_days = 0
        for day in days_21:
            cursor.execute("SELECT 1 FROM login_history WHERE username = ? AND date = ?", (uname, day))
            if cursor.fetchone():
                present_days += 1
                continue
            cursor.execute("SELECT status FROM attendance_override WHERE username = ? AND date = ?", (uname, day))
            override = cursor.fetchone()
            if override and override[0] == 'present':
                present_days += 1

        attendance_pct = round((present_days / len(days_21)) * 100) if days_21 else 0

        cursor.execute("""
            SELECT COUNT(DISTINCT t.id)
            FROM task_groups tg
            JOIN tasks t ON t.id = tg.task_id
            JOIN subjects s ON s.id = t.subject_id
            WHERE tg.group_name = ?
              AND t.assign_date <= ?
              AND t.task_type = 'practical'
        """, (grp, today))
        total_practical = cursor.fetchone()[0] or 0

        cursor.execute("""
            SELECT COUNT(DISTINCT t.id)
            FROM task_groups tg
            JOIN tasks t ON t.id = tg.task_id
            JOIN subjects s ON s.id = t.subject_id
            WHERE tg.group_name = ?
              AND t.assign_date <= ?
              AND t.task_type = 'practical'
              AND NOT EXISTS (
                  SELECT 1 FROM results r
                  WHERE r.username = ?
                    AND r.subject = s.name
                    AND r.task = t.name
              )
        """, (grp, today, uname))
        missing_practical = cursor.fetchone()[0] or 0

        cursor.execute("""
            SELECT COUNT(DISTINCT tt.id)
            FROM theory_tests tt
            LEFT JOIN theory_test_groups ttg ON tt.id = ttg.test_id
            WHERE (ttg.group_name = ? OR ttg.group_name IS NULL)
              AND tt.assign_date <= ?
        """, (grp, today))
        total_theory = cursor.fetchone()[0] or 0

        cursor.execute("""
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
        """, (grp, today, uname))
        missing_theory = cursor.fetchone()[0] or 0

        total_assigned = total_practical + total_theory
        missing_pct = round((missing_practical + missing_theory) / total_assigned * 100) if total_assigned else 0

        risk_score = round((100 - attendance_pct) * 0.4 + (100 - avg_score) * 0.4 + missing_pct * 0.2)
        if risk_score <= 40:
            status = 'Safe'
        elif risk_score <= 70:
            status = 'At Risk'
        else:
            status = 'High Risk'

        reasons = []
        if attendance_pct < 60:
            reasons.append(f"A {attendance_pct}% < 60%")
        if avg_score < 40:
            reasons.append(f"AVG {avg_score}% < 40%")
        if missing_pct > 70:
            reasons.append(f"Missing {missing_pct}% > 70%")
        if not reasons:
            reasons.append("multiple risk factors")

        if status != 'Safe':
            risk_learners.append({
                'username': uname,
                'name': full_name or uname,
                'group': grp or '—',
                'score': risk_score,
                'status': status,
                'reason': ' + '.join(reasons)
            })

    risk_learners.sort(key=lambda x: x['score'], reverse=True)
    at_risk_students = risk_learners[:10]

    # ─ Recent activity (last 20)
    if role == 'teacher':
        cursor.execute("""
            SELECT a.username, a.action, a.timestamp
            FROM activities a
            LEFT JOIN users u ON u.username = a.username
            WHERE a.username = ?
              OR (u.role = 'student' AND u.teacher_username = ?)
            ORDER BY a.timestamp DESC LIMIT 20
        """, (username, username))
    else:
        cursor.execute("""
            SELECT username, action, timestamp FROM activities
            ORDER BY timestamp DESC LIMIT 20
        """)
    recent_activities = cursor.fetchall()

    # ─ Recent submissions (last 15, best score per student per task)
    if role == 'teacher':
        cursor.execute(f"""
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
        """, group_filter_params)
    else:
        cursor.execute("""
            SELECT u.full_name, u.group_name, b.subject, b.task, b.best_score, MAX(r.timestamp)
            FROM (
                SELECT username, subject, task, MAX(score) as best_score
                FROM results GROUP BY username, subject, task
            ) b
            JOIN results r ON r.username = b.username AND r.subject = b.subject AND r.task = b.task AND r.score = b.best_score
            JOIN users u ON u.username = b.username
            GROUP BY b.username, b.subject, b.task
            ORDER BY MAX(r.timestamp) DESC LIMIT 15
        """)
    recent_submissions = cursor.fetchall()

    # ─ Class averages per subject per group (best score per student per task)
    from collections import defaultdict

    # Build practical subjects per group from assigned tasks so new subjects appear even without results.
    practical_subjects = defaultdict(set)
    if role == 'teacher' and groups:
        placeholders = ",".join("?" for _ in groups)
        cursor.execute(f"""
            SELECT tg.group_name, s.name
            FROM task_groups tg
            JOIN tasks t ON t.id = tg.task_id
            JOIN subjects s ON s.id = t.subject_id
            WHERE t.task_type = 'practical' AND tg.group_name IN ({placeholders})
        """, groups)
    else:
        cursor.execute("""
            SELECT tg.group_name, s.name
            FROM task_groups tg
            JOIN tasks t ON t.id = tg.task_id
            JOIN subjects s ON s.id = t.subject_id
            WHERE t.task_type = 'practical'
        """)
    for group_name, subject in cursor.fetchall():
        practical_subjects[group_name].add(subject)

    if role == 'teacher':
        cursor.execute(f"""
            SELECT u.group_name, b.subject, ROUND(AVG(b.best_score),1), COUNT(*)
            FROM (
                SELECT username, subject, task, MAX(score) as best_score
                FROM results GROUP BY username, subject, task
            ) b
            JOIN users u ON u.username = b.username
            WHERE u.group_name IS NOT NULL AND u.role = 'student' {group_filter_clause}
            GROUP BY u.group_name, b.subject
            ORDER BY u.group_name, b.subject
        """, group_filter_params)
    else:
        cursor.execute("""
            SELECT u.group_name, b.subject, ROUND(AVG(b.best_score),1), COUNT(*)
            FROM (
                SELECT username, subject, task, MAX(score) as best_score
                FROM results GROUP BY username, subject, task
            ) b
            JOIN users u ON u.username = b.username
            WHERE u.group_name IS NOT NULL AND u.role = 'student'
            GROUP BY u.group_name, b.subject
            ORDER BY u.group_name, b.subject
        """)
    practical_avgs_raw = cursor.fetchall()

    practical_avgs = { (g, subj): (avg, cnt) for g, subj, avg, cnt in practical_avgs_raw }

    subject_avgs = defaultdict(list)
    for group_name, subjects in practical_subjects.items():
        for subject in sorted(subjects):
            avg, cnt = practical_avgs.get((group_name, subject), (None, 0))
            subject_avgs[group_name].append((subject, avg, cnt, 'Practical'))

    # Add any practical subjects that appear only in results but aren't assigned through tasks
    for group_name, subject, avg, cnt in practical_avgs_raw:
        if subject not in practical_subjects.get(group_name, set()):
            subject_avgs[group_name].append((subject, avg, cnt, 'Practical'))

    # ─ Combined theory averages per group
    if role == 'teacher':
        cursor.execute(f"""
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
        """, group_filter_params)
    else:
        cursor.execute("""
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
        """)
    theory_avgs_raw = cursor.fetchall()

    theory_avgs = {group_name: (avg, cnt) for group_name, avg, cnt in theory_avgs_raw}

    # Add Theory row for groups with theory assignments or results
    theory_groups = set()
    if role == 'teacher' and groups:
        placeholders = ",".join("?" for _ in groups)
        cursor.execute(f"""
            SELECT DISTINCT ttg.group_name
            FROM theory_tests tt
            JOIN theory_test_groups ttg ON tt.id = ttg.test_id
            WHERE tt.assign_date IS NOT NULL AND ttg.group_name IN ({placeholders})
        """, groups)
        theory_groups.update(row[0] for row in cursor.fetchall() if row[0])

        cursor.execute("""
            SELECT 1
            FROM theory_tests tt
            LEFT JOIN theory_test_groups ttg ON tt.id = ttg.test_id
            WHERE tt.assign_date IS NOT NULL AND ttg.group_name IS NULL
            LIMIT 1
        """)
        if cursor.fetchone():
            theory_groups.update(groups)
    else:
        cursor.execute("""
            SELECT DISTINCT ttg.group_name
            FROM theory_tests tt
            JOIN theory_test_groups ttg ON tt.id = ttg.test_id
            WHERE tt.assign_date IS NOT NULL AND ttg.group_name IS NOT NULL
        """)
        theory_groups.update(row[0] for row in cursor.fetchall() if row[0])

        cursor.execute("""
            SELECT 1
            FROM theory_tests tt
            LEFT JOIN theory_test_groups ttg ON tt.id = ttg.test_id
            WHERE tt.assign_date IS NOT NULL AND ttg.group_name IS NULL
            LIMIT 1
        """)
        if cursor.fetchone():
            cursor.execute("SELECT DISTINCT group_name FROM users WHERE group_name IS NOT NULL")
            theory_groups.update(row[0] for row in cursor.fetchall() if row[0])

    for group_name in sorted(theory_groups):
        avg, cnt = theory_avgs.get(group_name, (None, 0))
        subject_avgs[group_name].append(("Theory", avg, cnt, 'Theory'))

    subject_avgs = dict(subject_avgs)

    # ─ Recent theory submissions (best per student per test)
    if role == 'teacher':
        cursor.execute(f"""
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
        """, group_filter_params)
    else:
        cursor.execute("""
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
        """)
    recent_theory_submissions = cursor.fetchall()

    # ─ Top/bottom performers (best score per task)
    if role == 'teacher':
        cursor.execute(f"""
            SELECT u.full_name, u.group_name, ROUND(AVG(b.best_score),1) as avg
            FROM (
                SELECT username, subject, task, MAX(score) as best_score
                FROM results GROUP BY username, subject, task
            ) b
            JOIN users u ON u.username = b.username
            WHERE u.role = 'student' {group_filter_clause}
            GROUP BY b.username HAVING COUNT(*) >= 1
            ORDER BY avg DESC LIMIT 5
        """, group_filter_params)
        top_performers = cursor.fetchall()
        cursor.execute(f"""
            SELECT u.full_name, u.group_name, ROUND(AVG(b.best_score),1) as avg
            FROM (
                SELECT username, subject, task, MAX(score) as best_score
                FROM results GROUP BY username, subject, task
            ) b
            JOIN users u ON u.username = b.username
            WHERE u.role = 'student' {group_filter_clause}
            GROUP BY b.username HAVING COUNT(*) >= 1
            ORDER BY avg ASC LIMIT 5
        """, group_filter_params)
        bottom_performers = cursor.fetchall()
    else:
        cursor.execute("""
            SELECT u.full_name, u.group_name, ROUND(AVG(b.best_score),1) as avg
            FROM (
                SELECT username, subject, task, MAX(score) as best_score
                FROM results GROUP BY username, subject, task
            ) b
            JOIN users u ON u.username = b.username
            WHERE u.role = 'student'
            GROUP BY b.username HAVING COUNT(*) >= 1
            ORDER BY avg DESC LIMIT 5
        """)
        top_performers = cursor.fetchall()
        cursor.execute("""
            SELECT u.full_name, u.group_name, ROUND(AVG(b.best_score),1) as avg
            FROM (
                SELECT username, subject, task, MAX(score) as best_score
                FROM results GROUP BY username, subject, task
            ) b
            JOIN users u ON u.username = b.username
            WHERE u.role = 'student'
            GROUP BY b.username HAVING COUNT(*) >= 1
            ORDER BY avg ASC LIMIT 5
        """)
        bottom_performers = cursor.fetchall()

    # ─ Students without assigned classes or teachers
    cursor.execute("""
        SELECT username, full_name
        FROM users
        WHERE role = 'student' AND (
            (group_name IS NULL OR group_name = '') OR
            (teacher_username IS NULL OR teacher_username = '')
        )
        ORDER BY full_name, username
    """)
    students_without_classes = cursor.fetchall()

    # ─ Missing tasks count per group
    if role == 'teacher':
        cursor.execute(f"""
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
        """, (today, *group_filter_params))
    else:
        cursor.execute("""
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
        """, (today,))
    missing_by_group = cursor.fetchall()

    conn.close()
    return render_template(
        "teacher_dashboard.html",
        username=username,
        total_students=total_students,
        active_today=active_today,
        avg_att_pct=avg_att_pct,
        groups=groups,
        group_att=group_att,
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
        active_term=get_active_term_range(),
        days_in_period=len(days_21)
    )



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

    cursor.execute("""
    UPDATE users SET role = 'teacher' WHERE username = ?
    """, (username,))

    conn.commit()
    log_activity(admin_user, f"promoted {username} to teacher")
    conn.close()

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

    cursor.execute("""
    UPDATE users SET role = 'student' WHERE username = ?
    """, (username,))

    conn.commit()
    log_activity(admin_user, f"demoted {username} to student")
    conn.close()

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

    # Delete all data associated with this user
    cursor.execute("DELETE FROM results WHERE username = ?", (username,))
    cursor.execute("DELETE FROM weaknesses WHERE username = ?", (username,))
    cursor.execute("DELETE FROM login_history WHERE username = ?", (username,))
    cursor.execute("DELETE FROM attendance_override WHERE username = ?", (username,))
    cursor.execute("DELETE FROM activities WHERE username = ?", (username,))
    cursor.execute("DELETE FROM learner_notes WHERE username = ?", (username,))
    cursor.execute("DELETE FROM result_removals WHERE username = ?", (username,))
    cursor.execute("""
        DELETE FROM theory_answers WHERE submission_id IN
            (SELECT id FROM theory_submissions WHERE username = ?)
    """, (username,))
    cursor.execute("DELETE FROM theory_submissions WHERE username = ?", (username,))
    cursor.execute("DELETE FROM users WHERE username = ?", (username,))

    conn.commit()
    conn.close()
    log_activity(admin_user, f"deleted user {username}")
    return redirect(url_for("admin_panel"))


def calculate_attendance_percentage(data, days):
    total_cells = len(data) * len(days)
    present = 0

    for row in data:
        for d in days:
            if row["days"].get(d):
                present += 1

    return round((present / total_cells) * 100) if total_cells else 0

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
                cursor.execute("""
                    INSERT INTO term_dates (term, start_date, end_date)
                    VALUES (?, ?, ?)
                    ON CONFLICT(term) DO UPDATE SET start_date = excluded.start_date, end_date = excluded.end_date
                """, (term_num, start, end))
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
    edit_mode = request.args.get("edit") == "1"   # ✅ key line
    range_param = request.args.get("range", "week")

    # Calculate date range
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

    # ─────────────────────────────────────────────────────────────
    # Auto-exclude: on every attendance load, find past business
    # days where (total present across group) == 0 and add to
    # excluded_dates with reason='auto_excluded'.
    # Scope: past 90 days, but not before the active term start.
    # ─────────────────────────────────────────────────────────────
    conn = get_db()
    cursor = conn.cursor()

    # Active term start boundary (if any)
    active_term = get_active_term_range()
    active_term_start = None
    if active_term:
        active_term_start = active_term[0]

    today_date = datetime.now().date()
    start_boundary = today_date - timedelta(days=90)
    if active_term_start:
        try:
            active_start_date = datetime.strptime(active_term_start, "%Y-%m-%d").date()
            if active_start_date > start_boundary:
                start_boundary = active_start_date
        except Exception:
            pass

    # Eligible days: business days only, strictly day < today
    yesterday = today_date - timedelta(days=1)
    cur_day = start_boundary
    eligible_days = []
    while cur_day <= yesterday:
        if cur_day.weekday() < 5:
            eligible_days.append(cur_day.strftime("%Y-%m-%d"))
        cur_day += timedelta(days=1)

    # Load existing excluded dates for quick duplicate prevention
    cursor.execute("SELECT date, group_name FROM excluded_dates")
    existing_excluded = {(r[0], r[1]) for r in cursor.fetchall()}

    groups_to_check = groups if selected_group is None else ([selected_group] if selected_group in groups else [])
    for group in groups_to_check:
        # Get students in the group (and teacher constraint if needed)
        if role == "teacher":
            cursor.execute(
                "SELECT username FROM users WHERE group_name = ? AND role = 'student' AND teacher_username = ?",
                (group, username),
            )
        else:
            cursor.execute(
                "SELECT username FROM users WHERE group_name = ? AND role = 'student'",
                (group,),
            )
        student_usernames = [r[0] for r in cursor.fetchall()]
        if not student_usernames:
            continue

        # Pre-check: count of distinct present per day
        for day in eligible_days:
            # total present == login_history present OR manual override present
            placeholders = ",".join("?" * len(student_usernames))

            cursor.execute(f"""
                SELECT COUNT(DISTINCT username)
                FROM (
                    SELECT username
                    FROM login_history
                    WHERE date = ? AND username IN ({placeholders})
                    UNION
                    SELECT a.username
                    FROM attendance_override a
                    WHERE a.date = ? AND a.status = 'present'
                      AND a.username IN ({placeholders})
                      AND NOT EXISTS (
                          SELECT 1 FROM login_history lh
                          WHERE lh.date = ? AND lh.username = a.username
                      )
                ) p
            """, (*([day] + student_usernames), day, *student_usernames, day))
            present_count = cursor.fetchone()[0] or 0

            if present_count == 0 and (day, group) not in existing_excluded:
                cursor.execute("""
                    INSERT INTO excluded_dates (date, group_name, reason, created_by, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(date, group_name) DO NOTHING
                """, (day, group, "auto_excluded", username, datetime.now().isoformat()))
                existing_excluded.add((day, group))

    conn.commit()
    conn.close()
    # ─────────────────────────────────────────────────────────────

    days = []
    data = []

    daily_present_counts = {}
    daily_absent_counts = {}

    if selected_group:
        days, data = get_attendance_data(selected_group, start_date, end_date, teacher_username=username if role == 'teacher' else None)

        # Daily totals across all learners in the selected group
        for day in days:
            present = sum(1 for row in data if row.get("days", {}).get(day))
            total = len(data)
            daily_present_counts[day] = present
            daily_absent_counts[day] = total - present

    # Get excluded dates
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT date, group_name, reason, created_by, created_at
    FROM excluded_dates
    ORDER BY date DESC
    """)
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
        terms=terms
    )

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
        "last_active": "last_active"
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

    # Teachers only see their own students (plus themselves)
    if role == 'teacher':
        query += " AND (teacher_username = ? OR username = ?)"
        params.extend([username, username])

    if group:
        query += " AND group_name = ?"
        params.append(group)

    query += f" ORDER BY {valid_sorts[sort]} {order.upper()}"

    cursor.execute(query, params)
    users = cursor.fetchall()

    # Get group list for dropdown — teachers only see their own groups
    if role == 'teacher':
        my_groups = get_groups(username)
        groups = my_groups
    else:
        cursor.execute("SELECT DISTINCT group_name FROM users WHERE group_name IS NOT NULL")
        groups = [g[0] for g in cursor.fetchall()]

    conn.close()

    return render_template(
        "admin.html",
        users=users,
        groups=groups,
        search=search,
        selected_group=group,
        sort=sort,
        order=order
    )

@app.route("/import_users", methods=["POST"])
def import_users():
    username = session.get("username")
    
    if not username:
        return redirect(url_for("login"))
    
    role = get_user_role(username)
    if role not in ["teacher", "admin"]:
        return "Access denied", 403
    
    # Check if a file was uploaded
    if 'excel_file' not in request.files:
        flash("No file uploaded", "error")
        return redirect(url_for("admin_panel"))
    
    file = request.files['excel_file']
    if file.filename == '':
        flash("No file selected", "error")
        return redirect(url_for("admin_panel"))
    
    filename = file.filename or ""
    if not filename.lower().endswith(('.xlsx', '.xls')):
        flash("Please upload an Excel file (.xlsx or .xls)", "error")
        return redirect(url_for("admin_panel"))
    
    try:
        # Read the uploaded Excel file
        df = pd.read_excel(file)
        
        # Validate required columns
        required_columns = ['username', 'full_name', 'group']
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            flash(f"Missing required columns: {', '.join(missing_columns)}", "error")
            return redirect(url_for("admin_panel"))
        
        conn = get_db()
        cursor = conn.cursor()
        
        imported_count = 0
        updated_count = 0
        
        # Check which optional columns are present
        teacher_username_present = 'teacher_username' in df.columns
        role_present = 'role' in df.columns
        
        for _, row in df.iterrows():
            username_val = str(row["username"]).strip().upper()
            full_name = str(row["full_name"]).strip()
            group_name = str(row["group"]).strip()
            
            # Handle optional columns
            teacher_username = str(row["teacher_username"]).strip() if teacher_username_present else None
            if teacher_username == '':
                teacher_username = None
            
            role_value = str(row["role"]).strip().lower() if role_present else 'student'
            if role_value == '' or role_value not in ['student', 'teacher', 'admin']:
                role_value = 'student'
            
            # Check if user already exists
            cursor.execute("SELECT username FROM users WHERE username = ?", (username_val,))
            existing = cursor.fetchone()
            
            # Build dynamic SQL for UPSERT
            columns = ['username', 'full_name', 'group_name', 'teacher_username', 'role']
            values = [username_val, full_name, group_name, teacher_username, role_value]
            update_parts = ['full_name = excluded.full_name', 'group_name = excluded.group_name']
            
            if teacher_username_present:
                update_parts.append('teacher_username = excluded.teacher_username')
            
            if role_present:
                update_parts.append('role = excluded.role')
            
            update_clause = ', '.join(update_parts)
            
            cursor.execute(f"""
            INSERT INTO users ({', '.join(columns)})
            VALUES ({', '.join(['?'] * len(columns))})
            ON CONFLICT(username) DO UPDATE SET
                {update_clause}
            """, values)
            
            if existing:
                updated_count += 1
            else:
                imported_count += 1
        
        conn.commit()
        conn.close()
        
        flash(f"Successfully imported {imported_count} new users and updated {updated_count} existing users.", "success")
    
    except Exception as e:
        flash(f"Error importing users: {str(e)}", "error")
    
    return redirect(url_for("admin_panel"))

@app.route("/download_user_template")
def download_user_template():
    username = session.get("username")
    
    if not username:
        return redirect(url_for("login"))
    
    role = get_user_role(username)
    if role not in ["teacher", "admin"]:
        return "Access denied", 403
    
    # Create a sample DataFrame with the required columns
    sample_data = {
        'username': ['STUDENT001', 'STUDENT002', 'STUDENT003'],
        'full_name': ['Smith, John', 'Doe, Jane', 'Johnson, Bob'],
        'group': ['12A', '12A', '12B'],
        'teacher_username': ['TEACHER1', 'TEACHER1', 'TEACHER2'],
        'role': ['student', 'student', 'student']
    }
    df = pd.DataFrame(sample_data)
    
    # Create a BytesIO buffer to store the Excel file
    from io import BytesIO
    buffer = BytesIO()
    df.to_excel(buffer, index=False)
    buffer.seek(0)
    
    return send_file(
        buffer,
        as_attachment=True,
        download_name='user_import_template.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
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

    if role == 'teacher':
        cursor.execute("""
            SELECT a.username, a.action, strftime('%Y-%m-%d %H:%M:%S', a.timestamp)
            FROM activities a
            LEFT JOIN users u ON u.username = a.username
            WHERE a.username = ?
              OR (u.role = 'student' AND u.teacher_username = ?)
            ORDER BY a.timestamp DESC LIMIT 100
        """, (username, username))
    else:
        cursor.execute("""
            SELECT username, action, strftime('%Y-%m-%d %H:%M:%S', timestamp)
            FROM activities ORDER BY timestamp DESC LIMIT 100
        """)
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

    cursor.execute("SELECT username, full_name, group_name, teacher_username, role FROM users WHERE username = ?", (username,))
    user = cursor.fetchone()
    if not user:
        conn.close()
        return "User not found", 404

    if get_user_role(admin_user) == "teacher" and (user[2] or user[3]):
        conn.close()
        return "Access denied", 403

    if request.method == "POST":
        full_name = request.form.get("full_name")
        group_name = request.form.get("group_name")
        teacher_username = request.form.get("teacher_username") or None
        role_value = request.form.get("role") or "student"

        if role_value == "admin" and get_user_role(admin_user) != "admin":
            return "Access denied", 403

        cursor.execute("""
        UPDATE users
        SET full_name = ?, group_name = ?, teacher_username = ?, role = ?
        WHERE username = ?
        """, (full_name, group_name, teacher_username, role_value, username))

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

    # Teachers can only view records of their own students
    if admin_role == 'teacher':
        cursor.execute("SELECT teacher_username FROM users WHERE username = ?", (username,))
        row = cursor.fetchone()
        if not row or row[0] != admin_user:
            conn.close()
            return "Access denied", 403

    # ── Attendance ────────────────────────────────────────────────────
    days = get_last_21_days()
    history = []
    cursor.execute("SELECT group_name FROM users WHERE username = ?", (username,))
    group_row = cursor.fetchone()
    user_group = group_row[0] if group_row else None

    for day in days:
        cursor.execute("SELECT MIN(login_time) FROM login_history WHERE username = ? AND date = ?", (username, day))
        login_time = cursor.fetchone()[0]
        cutoff = get_group_late_threshold(user_group, day) if user_group else None
        if login_time:
            time_str = login_time.split(" ")[1][:5]
            late = cutoff is not None and time_str > cutoff
            history.append({"date": day, "status": "Present", "time": time_str, "late": late, "note": "Auto"})
        else:
            cursor.execute("SELECT status FROM attendance_override WHERE username = ? AND date = ?", (username, day))
            override = cursor.fetchone()
            if override and override[0] == "present":
                history.append({"date": day, "status": "Present", "time": "12:00", "late": False, "note": "Manual"})
            else:
                history.append({"date": day, "status": "Absent", "time": "", "late": False, "note": "Manual" if override else "Auto"})

    total_days = len(history)
    present_days = sum(1 for h in history if h["status"] == "Present")
    absent_days = total_days - present_days
    late_days = sum(1 for h in history if h["late"])
    attendance_pct = round((present_days / total_days) * 100) if total_days else 0
    recent_history = history[-10:]  # last 10 days

    # ── Academic results ──────────────────────────────────────────────
    cursor.execute("""
        SELECT subject, task, MAX(score) as score, feedback, MAX(timestamp) as timestamp
        FROM results WHERE username = ? GROUP BY subject, task ORDER BY timestamp DESC
    """, (username,))
    all_results = cursor.fetchall()

    cursor.execute("""
        SELECT subject, ROUND(AVG(best_score),1)
        FROM (SELECT subject, task, MAX(score) as best_score FROM results WHERE username = ? GROUP BY subject, task)
        GROUP BY subject
    """, (username,))
    subject_avgs = cursor.fetchall()

    cursor.execute("""
        SELECT ROUND(AVG(best_score),1)
        FROM (SELECT subject, task, MAX(score) as best_score FROM results WHERE username = ? GROUP BY subject, task)
    """, (username,))
    overall_avg_row = cursor.fetchone()
    practical_avg = overall_avg_row[0] if overall_avg_row and overall_avg_row[0] else 0

    cursor.execute("""
        SELECT ROUND(AVG(best_pct),1)
        FROM (SELECT test_id, MAX(percentage) as best_pct FROM theory_submissions WHERE username = ? GROUP BY test_id)
    """, (username,))
    theory_avg_row = cursor.fetchone()
    theory_avg = theory_avg_row[0] if theory_avg_row and theory_avg_row[0] else None

    overall_avg = round((practical_avg + theory_avg) / 2, 1) if practical_avg and theory_avg else (practical_avg or theory_avg or 0)

    recent_results = all_results[:10]

    # Trend: compare last 5 vs previous 5
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

    # Task status rows - DYNAMICALLY fetch only assigned tasks
    cursor.execute("SELECT group_name FROM users WHERE username = ?", (username,))
    user_group_row = cursor.fetchone()
    user_group = user_group_row[0] if user_group_row else None
    
    # Get practical tasks assigned to this user's group
    cursor.execute("""
        SELECT DISTINCT s.name as subject, t.name as task_name
        FROM tasks t
        JOIN subjects s ON t.subject_id = s.id
        JOIN task_groups tg ON t.id = tg.task_id
        WHERE tg.group_name = ? AND t.task_type = 'practical'
        ORDER BY s.name, t.name
    """, (user_group,))
    assigned_practical_tasks = cursor.fetchall()
    
    # Get theory tests assigned to this user's group
    cursor.execute("""
        SELECT DISTINCT tt.id, tt.title
        FROM theory_tests tt
        LEFT JOIN theory_test_groups ttg ON tt.id = ttg.test_id
        WHERE (ttg.group_name = ? OR ttg.group_name IS NULL)
        ORDER BY tt.title
    """, (user_group,))
    assigned_theory_tests = cursor.fetchall()
    
    # Build task rows from assigned tasks only
    results_map = {(r[0], r[1]): {"score": r[2], "feedback": r[3], "timestamp": r[4]} for r in all_results}
    task_rows = []
    for subject, task in assigned_practical_tasks:
        row = results_map.get((subject, task))
        task_rows.append({
            "subject": subject, "task": task,
            "score": row["score"] if row else None,
            "feedback": row["feedback"] if row else None,
            "timestamp": row["timestamp"] if row else None,
            "status": "Submitted" if row else "Not submitted",
            "type": "practical"
        })
    
    # Get theory test submissions
    theory_submissions_map = {}
    for test_id, title in assigned_theory_tests:
        cursor.execute("""
            SELECT MAX(percentage), MAX(submitted_at)
            FROM theory_submissions
            WHERE username = ? AND test_id = ?
        """, (username, test_id))
        result = cursor.fetchone()
        if result and result[0] is not None:
            theory_submissions_map[title] = {"score": result[0], "timestamp": result[1]}
    
    # Add theory tests to task rows
    for test_id, title in assigned_theory_tests:
        row = theory_submissions_map.get(title)
        task_rows.append({
            "subject": "Theory", "task": title,
            "score": row["score"] if row else None,
            "feedback": "",
            "timestamp": row["timestamp"] if row else None,
            "status": "Submitted" if row else "Not submitted",
            "type": "theory"
        })
    
    average = round(sum(t["score"] for t in task_rows if t["score"] is not None) /
                    max(1, sum(1 for t in task_rows if t["score"] is not None)), 1) \
              if any(t["score"] is not None for t in task_rows) else 0

    # ── Theory test results ───────────────────────────────────────────
    cursor.execute("""
        SELECT tt.title, ts.score, ts.total, MAX(ts.percentage) as best_pct, MAX(ts.submitted_at) as latest
        FROM theory_submissions ts
        JOIN theory_tests tt ON ts.test_id = tt.id
        WHERE ts.username = ? GROUP BY ts.test_id ORDER BY latest DESC LIMIT 10
    """, (username,))
    theory_results = cursor.fetchall()

    # ── Weaknesses ────────────────────────────────────────────────────
    cursor.execute("""
        SELECT skill, count FROM weaknesses
        WHERE username = ? ORDER BY count DESC LIMIT 10
    """, (username,))
    weaknesses = cursor.fetchall()

    # ── Recent activity ───────────────────────────────────────────────
    cursor.execute("""
        SELECT action, timestamp FROM activities
        WHERE username = ? ORDER BY timestamp DESC LIMIT 10
    """, (username,))
    recent_activity = cursor.fetchall()

    # ── Teacher notes ─────────────────────────────────────────────────
    cursor.execute("SELECT id, note, flag, created_by, created_at FROM learner_notes WHERE username = ? ORDER BY created_at DESC", (username,))
    notes = cursor.fetchall()

    conn.close()
    return render_template(
        "learner_record.html",
        user=user,
        history=recent_history,
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
        trend=trend,
        weaknesses=weaknesses,
        recent_activity=recent_activity,
        notes=notes
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
        cursor.execute("""
            INSERT INTO learner_notes (username, note, flag, created_by, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (username, note, flag, admin_user, datetime.now().isoformat()))
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

    task_type  = request.form.get("task_type")   # 'practical' or 'theory'
    subject    = request.form.get("subject", "")
    task_name  = request.form.get("task_name", "")
    test_id    = request.form.get("test_id", "")
    target     = request.form.get("target")       # 'all' or a specific username
    reason     = request.form.get("reason", "").strip()
    group      = request.form.get("group", "")

    if not reason:
        reason = "Removed by teacher"

    conn = get_db()
    cursor = conn.cursor()

    # Determine which students are affected
    if target == "all":
        if task_type == "practical":
            cursor.execute("SELECT DISTINCT username FROM results WHERE subject = ? AND task = ?",
                           (subject, task_name))
        else:
            cursor.execute("SELECT DISTINCT username FROM theory_submissions WHERE test_id = ?",
                           (test_id,))
        affected = [row[0] for row in cursor.fetchall()]
    else:
        affected = [target]

    now = datetime.now().isoformat()

    for username in affected:
        # Log the removal
        cursor.execute("""
            INSERT INTO result_removals
                (username, task_type, subject, task_name, test_id, removed_by, reason, removed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (username, task_type, subject, task_name,
               test_id if task_type == "theory" else None,
               teacher, reason, now))

        # Also add a learner note so it shows on their record
        note_text = (f"⚠️ Marks removed by {teacher}: "
                     f"{'[Theory] ' + task_name if task_type == 'theory' else subject + ' - ' + task_name}. "
                     f"Reason: {reason}")
        cursor.execute("""
            INSERT INTO learner_notes (username, note, flag, created_by, created_at)
            VALUES (?, ?, 'warning', ?, ?)
        """, (username, note_text, teacher, now))

        # Delete the actual results
        if task_type == "practical":
            cursor.execute("DELETE FROM results WHERE username = ? AND subject = ? AND task = ?",
                           (username, subject, task_name))
        else:
            cursor.execute("""
                DELETE FROM theory_answers WHERE submission_id IN
                    (SELECT id FROM theory_submissions WHERE username = ? AND test_id = ?)
            """, (username, test_id))
            cursor.execute("DELETE FROM theory_submissions WHERE username = ? AND test_id = ?",
                           (username, test_id))

    conn.commit()
    log_activity(teacher, f"removed {'all' if target == 'all' else target}'s results for "
                          f"{'[Theory] ' + task_name if task_type == 'theory' else subject + ' - ' + task_name}. "
                          f"Reason: {reason}")
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
    all_groups = get_groups(username) if role == 'teacher' else get_groups()
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

    with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
        for group in selected_groups:
            # Get all students in the group
            cursor.execute("""
                SELECT username, full_name FROM users
                WHERE group_name = ? AND role = 'student'
                ORDER BY full_name
            """, (group,))
            students_raw = cursor.fetchall()

            # Get practical tasks assigned to this group
            cursor.execute("""
                SELECT DISTINCT s.name as subject, t.name as task_name, t.id
                FROM tasks t
                JOIN subjects s ON t.subject_id = s.id
                JOIN task_groups tg ON t.id = tg.task_id
                WHERE tg.group_name = ? AND t.task_type = 'practical'
                ORDER BY s.name, t.name
            """, (group,))
            practical_tasks = cursor.fetchall()

            # Get theory tests assigned to this group
            cursor.execute("""
                SELECT DISTINCT tt.id, tt.title, tt.subject
                FROM theory_tests tt
                LEFT JOIN theory_test_groups ttg ON tt.id = ttg.test_id
                WHERE (ttg.group_name = ? OR ttg.group_name IS NULL)
                ORDER BY tt.subject, tt.title
            """, (group,))
            theory_tasks = cursor.fetchall()

            # Build rows for Excel
            rows = []
            for student_username, full_name in students_raw:
                row = {
                    "Username": student_username,
                    "Name": full_name or student_username,
                    "Group": group
                }

                # Get practical results
                for subject, task_name, task_id in practical_tasks:
                    cursor.execute("""
                        SELECT MAX(score)
                        FROM results
                        WHERE username = ? AND subject = ? AND task = ?
                    """, (student_username, subject, task_name))
                    result = cursor.fetchone()
                    col_name = f"{subject} - {task_name}"
                    row[col_name] = result[0] if result and result[0] is not None else ""

                # Get theory results
                for test_id, title, subject in theory_tasks:
                    cursor.execute("""
                        SELECT MAX(percentage)
                        FROM theory_submissions
                        WHERE username = ? AND test_id = ?
                    """, (student_username, test_id))
                    result = cursor.fetchone()
                    col_name = f"[Theory] {title}"
                    row[col_name] = result[0] if result and result[0] is not None else ""

                # Calculate overall average
                all_scores = []
                for subject, task_name, task_id in practical_tasks:
                    cursor.execute("""
                        SELECT MAX(score)
                        FROM results
                        WHERE username = ? AND subject = ? AND task = ?
                    """, (student_username, subject, task_name))
                    result = cursor.fetchone()
                    if result and result[0] is not None:
                        all_scores.append(result[0])
                
                for test_id, title, subject in theory_tasks:
                    cursor.execute("""
                        SELECT MAX(percentage)
                        FROM theory_submissions
                        WHERE username = ? AND test_id = ?
                    """, (student_username, test_id))
                    result = cursor.fetchone()
                    if result and result[0] is not None:
                        all_scores.append(result[0])
                
                row["Overall Average"] = round(sum(all_scores) / len(all_scores), 1) if all_scores else ""

                rows.append(row)

            # Create DataFrame and write to Excel
            df = pd.DataFrame(rows)
            # Clean sheet name (remove special characters)
            sheet_name = group.replace("/", "_").replace("\\", "_")[:31]  # Excel sheet name limit
            df.to_excel(writer, sheet_name=sheet_name, index=False)

    log_activity(username, "exported results by group")
    conn.close()

    response = send_file(file_path, as_attachment=True)
    response.headers["HX-Redirect"] = url_for("teacher_dashboard")
    return response

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
    days, data = get_attendance_data(group, teacher_username=username if role == 'teacher' else None)

    rows = []

    for row in data:
        base = {
            "Username": row["username"],
            "Name": row["name"],
            "Group": row["group"],
            "Attendance %": row["attendance_pct"]
        }

        for d in days:
            val = row["days"].get(d)
            base[d] = val["time"] if val else "A"

        rows.append(base)

    df = pd.DataFrame(rows)
    
    file_path = "attendance_export.xlsx"
    df.to_excel(file_path, index=False)

    log_activity(username, "exported attendance")

    conn.close()

    return send_file(file_path, as_attachment=True)

@app.route("/risk_learners")
def risk_learners():
    username = session.get("username")
    if not username:
        return redirect(url_for("login"))

    role = get_user_role(username)
    if role not in ["teacher", "admin"]:
        return "Access denied", 403

    selected_group = request.args.get("group")
    groups = get_groups(username) if role == 'teacher' else get_groups()

    # Teachers can only view their own groups
    if role == 'teacher' and selected_group and selected_group not in groups:
        selected_group = None

    if not selected_group:
        return render_template("Riks_learners.html", groups=groups, selected_group=None)

    conn = get_db()
    cursor = conn.cursor()

    # Get students for this group
    if role == 'teacher':
        cursor.execute("""
            SELECT username, full_name
            FROM users
            WHERE group_name = ? AND role = 'student' AND teacher_username = ?
            ORDER BY full_name
        """, (selected_group, username))
    else:
        cursor.execute("""
            SELECT username, full_name
            FROM users
            WHERE group_name = ? AND role = 'student'
            ORDER BY full_name
        """, (selected_group,))
    students_raw = cursor.fetchall()

    days_21 = get_last_21_days()
    today = datetime.now().strftime("%Y-%m-%d")
    risk_students = []

    for student_username, full_name in students_raw:
        cursor.execute("""
            SELECT ROUND(AVG(best_score), 1)
            FROM (
                SELECT subject, task, MAX(score) as best_score
                FROM results
                WHERE username = ?
                GROUP BY subject, task
            )
        """, (student_username,))
        avg_score = cursor.fetchone()[0] or 0

        present_days = 0
        for day in days_21:
            cursor.execute("SELECT 1 FROM login_history WHERE username = ? AND date = ?", (student_username, day))
            if cursor.fetchone():
                present_days += 1
                continue
            cursor.execute("SELECT status FROM attendance_override WHERE username = ? AND date = ?", (student_username, day))
            override = cursor.fetchone()
            if override and override[0] == 'present':
                present_days += 1

        attendance_pct = round((present_days / len(days_21)) * 100) if days_21 else 0

        cursor.execute("""
            SELECT COUNT(DISTINCT t.id)
            FROM task_groups tg
            JOIN tasks t ON t.id = tg.task_id
            WHERE tg.group_name = ?
              AND t.assign_date <= ?
        """, (selected_group, today))
        total_assigned = cursor.fetchone()[0] or 0

        cursor.execute("""
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
        """, (selected_group, today, student_username))
        missing_practical = cursor.fetchone()[0] or 0

        cursor.execute("""
            SELECT COUNT(DISTINCT tt.id)
            FROM theory_tests tt
            LEFT JOIN theory_test_groups ttg ON tt.id = ttg.test_id
            WHERE (ttg.group_name = ? OR ttg.group_name IS NULL)
              AND tt.assign_date <= ?
        """, (selected_group, today))
        total_theory = cursor.fetchone()[0] or 0

        cursor.execute("""
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
        """, (selected_group, today, student_username))
        missing_theory = cursor.fetchone()[0] or 0

        total_tasks = total_assigned + total_theory
        missing_pct = round((missing_practical + missing_theory) / total_tasks * 100) if total_tasks else 0

        risk_score = round((100 - attendance_pct) * 0.4 + (100 - avg_score) * 0.4 + missing_pct * 0.2)
        if risk_score <= 40:
            status = 'Safe'
        elif risk_score <= 70:
            status = 'At Risk'
        else:
            status = 'High Risk'

        reasons = []
        if attendance_pct < 60:
            reasons.append(f"A {attendance_pct}%")
        if avg_score < 40:
            reasons.append(f"AVG{avg_score}%")
        if missing_pct > 70:
            reasons.append(f"Missing {missing_pct}%")
        if not reasons:
            reasons.append("balanced risk factors")

        risk_students.append({
            'username': student_username,
            'name': full_name or student_username,
            'group': selected_group,
            'attendance_pct': attendance_pct,
            'avg_score': avg_score,
            'missing_pct': missing_pct,
            'score': risk_score,
            'status': status,
            'reason': ' + '.join(reasons)
        })

    conn.close()
    return render_template("Riks_learners.html", groups=groups, selected_group=selected_group,
                           risk_students=risk_students)


@app.route("/group_results")
def group_results():
    username = session.get("username")
    if not username:
        return redirect(url_for("login"))

    role = get_user_role(username)
    if role not in ["teacher", "admin"]:
        return "Access denied", 403

    selected_group = request.args.get("group")
    groups = get_groups(username) if role == 'teacher' else get_groups()

    # Teachers cannot access groups that aren't theirs
    if role == 'teacher' and selected_group and selected_group not in groups:
        selected_group = None

    if not selected_group:
        return render_template("group_results.html", groups=groups, selected_group=None)

    conn = get_db()
    cursor = conn.cursor()

    # Get students — teachers only see their own students
    if role == 'teacher':
        cursor.execute("""
            SELECT username, full_name FROM users
            WHERE group_name = ? AND role = 'student' AND teacher_username = ?
            ORDER BY full_name
        """, (selected_group, username))
    else:
        cursor.execute("""
            SELECT username, full_name FROM users
            WHERE group_name = ? AND role = 'student'
            ORDER BY full_name
        """, (selected_group,))
    students_raw = cursor.fetchall()

    # Get practical tasks assigned to this group
    cursor.execute("""
        SELECT DISTINCT s.name as subject, t.name as task_name, t.id
        FROM tasks t
        JOIN subjects s ON t.subject_id = s.id
        JOIN task_groups tg ON t.id = tg.task_id
        WHERE tg.group_name = ? AND t.task_type = 'practical'
        ORDER BY s.name, t.name
    """, (selected_group,))
    practical_tasks = [{"subject": row[0], "name": row[1], "id": row[2]} for row in cursor.fetchall()]

    # Get theory tests assigned to this group (include inactive tests if they have submissions)
    cursor.execute("""
        SELECT DISTINCT tt.id, tt.title, tt.subject
        FROM theory_tests tt
        LEFT JOIN theory_test_groups ttg ON tt.id = ttg.test_id
        WHERE (ttg.group_name = ? OR ttg.group_name IS NULL)
        ORDER BY tt.subject, tt.title
    """, (selected_group,))
    theory_tasks = [{"test_id": row[0], "title": row[1], "subject": row[2]} for row in cursor.fetchall()]

    # Build student results
    students = []
    total_averages = []

    for username, full_name in students_raw:
        student = {
            "username": username,
            "full_name": full_name,
            "practical_results": {},
            "theory_results": {},
            "overall_avg": None
        }

        # Get practical results for this student
        for task in practical_tasks:
            cursor.execute("""
                SELECT score, timestamp
                FROM results
                WHERE username = ? AND subject = ? AND task = ?
                ORDER BY timestamp DESC
            """, (username, task["subject"], task["name"]))
            scores = cursor.fetchall()
            
            if scores:
                all_scores = [s[0] for s in scores]
                best_score = max(all_scores)
                student["practical_results"][(task["subject"], task["name"])] = {
                    "best_score": best_score,
                    "attempts": len(scores),
                    "all_scores": all_scores
                }

        # Get theory results for this student
        for task in theory_tasks:
            cursor.execute("""
                SELECT percentage, submitted_at
                FROM theory_submissions
                WHERE username = ? AND test_id = ?
                ORDER BY submitted_at DESC
            """, (username, task["test_id"]))
            scores = cursor.fetchall()
            
            if scores:
                all_scores = [s[0] for s in scores]
                best_score = max(all_scores)
                student["theory_results"][task["test_id"]] = {
                    "best_score": best_score,
                    "attempts": len(scores),
                    "all_scores": all_scores
                }

        # Calculate overall average (best scores only)
        all_best_scores = []
        all_best_scores.extend([r["best_score"] for r in student["practical_results"].values()])
        all_best_scores.extend([r["best_score"] for r in student["theory_results"].values()])
        
        if all_best_scores:
            student["overall_avg"] = round(sum(all_best_scores) / len(all_best_scores), 1)
            total_averages.append(student["overall_avg"])

        students.append(student)

    # Calculate group average
    group_average = round(sum(total_averages) / len(total_averages), 1) if total_averages else 0

    conn.close()

    return render_template(
        "group_results.html",
        groups=groups,
        selected_group=selected_group,
        students=students,
        practical_tasks=practical_tasks,
        theory_tasks=theory_tasks,
        group_average=group_average
    )


@app.route("/export_attendance_form")
def export_attendance_form():
    username = session.get("username")
    if not username:
        return redirect(url_for("login"))
    role = get_user_role(username)
    if role not in ["teacher", "admin"]:
        return "Access denied", 403
    all_groups = get_groups(username) if role == 'teacher' else get_groups()
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
    with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
        for group in selected_groups:
            days, data = get_attendance_data(group, start_date, end_date, teacher_username=username if role == 'teacher' else None)

            # Filter days to the selected date range
            filtered_days = [d for d in days if start_date <= d <= end_date]

            rows = []

            for row in data:
                base = {
                    "Username": row["username"],
                    "Name": row["name"],
                    "Group": row["group"],
                    "Attendance %": row["attendance_pct"]
                }

                for d in filtered_days:
                    val = row["days"].get(d)
                    base[d] = val["time"] if val else "A"

                rows.append(base)

            df = pd.DataFrame(rows)
            # Clean sheet name (remove special characters)
            sheet_name = group.replace("/", "_").replace("\\", "_")[:31]  # Excel sheet name limit
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

    # 🔹 Get users in group
    cursor.execute("""
    SELECT username FROM users WHERE group_name = ? AND role = 'student'
    """, (group,))
    users = [u[0] for u in cursor.fetchall()]

    if users:
        placeholders = ",".join(["?"] * len(users))

        # 🔹 Delete login history (auto attendance)
        cursor.execute(f"""
        DELETE FROM login_history
        WHERE username IN ({placeholders}) AND date = ?
        """, (*users, date))

        # 🔹 Delete manual overrides
        cursor.execute(f"""
        DELETE FROM attendance_override
        WHERE username IN ({placeholders}) AND date = ?
        """, (*users, date))

        for user in users:
            add_learner_note_entry(cursor, user,
                f"Attendance reset for {date} in group {group}.", username)

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

    # 🔹 Get users in group
    cursor.execute("""
    SELECT username FROM users WHERE group_name = ? AND role = 'student'
    """, (group,))
    users = [u[0] for u in cursor.fetchall()]

    if users:
        # 🔹 Mark all as present (insert/update overrides)
        for user in users:
            cursor.execute("SELECT status FROM attendance_override WHERE username = ? AND date = ?", (user, date))
            previous = cursor.fetchone()

            cursor.execute("""
            INSERT INTO attendance_override (username, date, status)
            VALUES (?, ?, ?)
            ON CONFLICT(username, date)
            DO UPDATE SET status = excluded.status
            """, (user, date, "present"))

            if previous is None or previous[0] != "present":
                add_learner_note_entry(cursor, user,
                    f"Marked present for {date} in group {group}.", username)

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

        # FIX: Safe split (prevents unpack error)
        try:
            _, data = key.split("att_")
            user, day = data.split("|")
        except ValueError:
            continue

        value = value.strip().lower()

        # 🔹 SKIP EMPTY INPUT → DO NOTHING
        if value == "":
            continue

        # 🔹 CHECK if login already exists
        cursor.execute("""
        SELECT MIN(login_time)
        FROM login_history
        WHERE username = ? AND date = ?
        """, (user, day))

        login = cursor.fetchone()[0]

        # 🔹 Determine status
        if value == "x":
            status = "absent"
        else:
            status = "present"

        # 🔹 Insert override ONLY if needed
        cursor.execute("SELECT status FROM attendance_override WHERE username = ? AND date = ?", (user, day))
        previous = cursor.fetchone()

        cursor.execute("""
        INSERT INTO attendance_override (username, date, status)
        VALUES (?, ?, ?)
        ON CONFLICT(username, date)
        DO UPDATE SET status = excluded.status
        """, (user, day, status))

        if previous is None or previous[0] != status:
            add_learner_note_entry(cursor, user,
                f"Attendance manually set to {status.upper()} for {day}.", username)

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
    group = request.form.get("group")  # Can be empty string for global, or specific group
    reason = request.form.get("reason", "")

    if not date:
        return "Missing date", 400

    # Convert empty string to None for global exclusions
    if group == "":
        group = None

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
    INSERT INTO excluded_dates (date, group_name, reason, created_by, created_at)
    VALUES (?, ?, ?, ?, ?)
    ON CONFLICT(date, group_name)
    DO UPDATE SET reason = excluded.reason, created_by = excluded.created_by, created_at = excluded.created_at
    """, (date, group, reason, username, datetime.now().isoformat()))

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
    group = request.form.get("group")  # Can be empty string for global, or specific group

    if not date:
        return "Missing date", 400

    # Convert empty string to None for global exclusions
    if group == "":
        group = None

    conn = get_db()
    cursor = conn.cursor()

    # If group is specified, only remove group-specific exclusion
    # If group is None, remove global exclusion
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

    # 🔹 Get users in group
    cursor.execute("""
    SELECT username FROM users WHERE group_name = ? AND role = 'student'
    """, (group,))
    users = [u[0] for u in cursor.fetchall()]

    if users:
        # 🔹 Mark all as absent (insert/update overrides)
        for user in users:
            cursor.execute("SELECT status FROM attendance_override WHERE username = ? AND date = ?", (user, date))
            previous = cursor.fetchone()

            cursor.execute("""
            INSERT INTO attendance_override (username, date, status)
            VALUES (?, ?, ?)
            ON CONFLICT(username, date)
            DO UPDATE SET status = excluded.status
            """, (user, date, "absent"))

            if previous is None or previous[0] != "absent":
                add_learner_note_entry(cursor, user,
                    f"Marked absent for {date} in group {group}.", username)

    conn.commit()
    log_activity(username, f"marked all in {group} absent on {date}")
    conn.close()

    return redirect(url_for("attendance", group=group))

@app.route("/api/excluded_dates", methods=["GET"])
def api_excluded_dates():
    """API endpoint to fetch excluded dates as JSON"""
    username = session.get("username")
    if not username:
        return {"error": "Unauthorized"}, 401

    role = get_user_role(username)
    if role not in ["teacher", "admin"]:
        return {"error": "Access denied"}, 403

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT date, group_name, reason, created_by, created_at
    FROM excluded_dates
    ORDER BY date DESC
    """)

    excluded_dates = []
    for row in cursor.fetchall():
        excluded_dates.append({
            "date": row[0],
            "group_name": row[1],
            "reason": row[2],
            "created_by": row[3],
            "created_at": row[4]
        })

    conn.close()

    return {"excluded_dates": excluded_dates}

@app.route("/api/attendance_data", methods=["GET"])
def api_attendance_data():
    """API endpoint to fetch attendance data as JSON"""
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

    days, data = get_attendance_data(group, start_date, end_date, teacher_username=username if role == 'teacher' else None)

    return {
        "days": days,
        "data": data,
        "success": True
    }

@app.route("/manage_subjects", methods=["GET", "POST"])
def manage_subjects():
    username = session.get("username")
    if not username:
        return redirect(url_for("login"))

    role = get_user_role(username)
    if role not in ["teacher", "admin"]:
        return "Access denied", 403

    if request.method == "POST":
        action = request.form.get("action")
        if action == "create":
            subject_name = request.form.get("subject_name")
            if subject_name:
                conn = get_db()
                cursor = conn.cursor()
                try:
                    cursor.execute("INSERT INTO subjects (name, created_by, created_at) VALUES (?, ?, ?)",
                                   (subject_name, username, datetime.now().isoformat()))
                    conn.commit()
                    log_activity(username, f"created subject {subject_name}")
                except sqlite3.IntegrityError:
                    pass  # Subject already exists
                conn.close()
        elif action == "delete":
            subject_id = request.form.get("subject_id")
            if subject_id:
                conn = get_db()
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM subjects WHERE id = ?", (subject_id,))
                subj = cursor.fetchone()
                if subj:
                    # Delete all results for tasks in this subject
                    cursor.execute("""
                        DELETE FROM results WHERE subject = ?
                    """, (subj[0],))
                    # Delete task groups and tasks
                    cursor.execute("DELETE FROM task_groups WHERE task_id IN (SELECT id FROM tasks WHERE subject_id = ?)", (subject_id,))
                    cursor.execute("DELETE FROM tasks WHERE subject_id = ?", (subject_id,))
                    cursor.execute("DELETE FROM subjects WHERE id = ?", (subject_id,))
                    conn.commit()
                    log_activity(username, f"deleted subject {subj[0]} and all related tasks and results")
                conn.close()

        # After POST we also render template with fresh subject list
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id, name FROM subjects ORDER BY name")
        subjects = cursor.fetchall()
        conn.close()
        return render_template("manage_subjects.html", subjects=subjects)


    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM subjects ORDER BY name")
    subjects = cursor.fetchall()
    conn.close()

    return render_template("manage_subjects.html", subjects=subjects)


@app.route("/manage_tasks/<subject_id>", methods=["GET", "POST"])

def manage_tasks(subject_id):
    username = session.get("username")
    if not username:
        return redirect(url_for("login"))

    role = get_user_role(username)
    if role not in ["teacher", "admin"]:
        return "Access denied", 403

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT name FROM subjects WHERE id = ?", (subject_id,))
    subj = cursor.fetchone()
    if not subj:
        conn.close()
        return "Subject not found", 404
    subject_name = subj[0]

    if request.method == "POST":
        action = request.form.get("action")
        if action == "create":
            task_name = request.form.get("task_name")
            assign_date = request.form.get("assign_date")
            marking_script = request.form.get("marking_script")
            allow_multiple = 1 if request.form.get("allow_multiple") else 0
            max_attempts = int(request.form.get("max_attempts", 1)) if allow_multiple else 1
            groups = request.form.getlist("groups")
            teachers = request.form.getlist("teachers")
            if task_name and assign_date:
                question_text = request.form.get("question_text", "").strip()
                cursor.execute("INSERT INTO tasks (subject_id, name, assign_date, marking_script, question_text, task_type, allow_multiple, max_attempts, created_by, created_at) VALUES (?, ?, ?, ?, ?, 'practical', ?, ?, ?, ?)",
                               (subject_id, task_name, assign_date, marking_script, question_text, allow_multiple, max_attempts, username, datetime.now().isoformat()))
                task_id = cursor.lastrowid
                # Handle sample file upload
                if 'sample_file' in request.files:
                    file = request.files['sample_file']
                    if file.filename:
                        file_content = file.read()
                        file_name = file.filename
                        cursor.execute("UPDATE tasks SET sample_file = ?, sample_file_name = ? WHERE id = ?", (file_content, file_name, task_id))
                for group in groups:
                    cursor.execute("INSERT INTO task_groups (task_id, group_name) VALUES (?, ?)", (task_id, group))
                for teacher in teachers:
                    if teacher.strip():
                        cursor.execute("INSERT INTO task_teachers (task_id, teacher_username) VALUES (?, ?)", (task_id, teacher))
                conn.commit()
                log_activity(username, f"created task {task_name} in {subject_name}")
        elif action == "reuse":
            source_task_id = request.form.get("source_task_id")
            new_task_name = request.form.get("task_name", "").strip()
            new_assign_date = request.form.get("assign_date")
            new_marking_script = request.form.get("marking_script") or None
            new_allow_multiple = 1 if request.form.get("allow_multiple") else 0
            new_max_attempts = int(request.form.get("max_attempts", 1)) if new_allow_multiple else 1
            new_groups = request.form.getlist("groups")
            new_teachers = request.form.getlist("teachers")
            if source_task_id and new_task_name and new_assign_date:
                cursor.execute(
                    "SELECT question_text, sample_file, sample_file_name FROM tasks WHERE id = ?",
                    (source_task_id,)
                )
                src = cursor.fetchone()
                src_question = src[0] if src else ""
                src_file = src[1] if src else None
                src_file_name = src[2] if src else None
                cursor.execute(
                    "INSERT INTO tasks (subject_id, name, assign_date, marking_script, question_text, "
                    "task_type, allow_multiple, max_attempts, sample_file, sample_file_name, created_by, created_at) "
                    "VALUES (?, ?, ?, ?, ?, 'practical', ?, ?, ?, ?, ?, ?)",
                    (subject_id, new_task_name, new_assign_date, new_marking_script, src_question,
                     new_allow_multiple, new_max_attempts, src_file, src_file_name,
                     username, datetime.now().isoformat())
                )
                new_task_id = cursor.lastrowid
                for g in new_groups:
                    if g.strip():
                        cursor.execute("INSERT INTO task_groups (task_id, group_name) VALUES (?, ?)", (new_task_id, g))
                for t in new_teachers:
                    if t.strip():
                        cursor.execute("INSERT INTO task_teachers (task_id, teacher_username) VALUES (?, ?)", (new_task_id, t))
                conn.commit()
                log_activity(username, f"reused task {source_task_id} as '{new_task_name}' in {subject_name}")
        elif action == "assign_theory":
            task_name = request.form.get("task_name")
            assign_date = request.form.get("assign_date")
            theory_test_id = request.form.get("theory_test_id")
            groups = request.form.getlist("groups")
            teachers = request.form.getlist("teachers")
            if task_name and assign_date and theory_test_id:
                cursor.execute("INSERT INTO tasks (subject_id, name, assign_date, theory_test_id, task_type, created_by, created_at) VALUES (?, ?, ?, ?, 'theory', ?, ?)",
                               (subject_id, task_name, assign_date, theory_test_id, username, datetime.now().isoformat()))
                task_id = cursor.lastrowid
                for group in groups:
                    cursor.execute("INSERT INTO task_groups (task_id, group_name) VALUES (?, ?)", (task_id, group))
                for teacher in teachers:
                    if teacher.strip():
                        cursor.execute("INSERT INTO task_teachers (task_id, teacher_username) VALUES (?, ?)", (task_id, teacher))
                conn.commit()
                log_activity(username, f"assigned theory test as task {task_name} in {subject_name}")
        elif action == "delete":
            task_id = request.form.get("task_id")
            if task_id:
                cursor.execute("SELECT name, subject_id FROM tasks WHERE id = ?", (task_id,))
                tsk = cursor.fetchone()
                if tsk:
                    task_name = tsk[0]
                    subject_id_val = tsk[1]
                    # Get subject name to delete results
                    cursor.execute("SELECT name FROM subjects WHERE id = ?", (subject_id_val,))
                    subj_row = cursor.fetchone()
                    if subj_row:
                        subject_name = subj_row[0]
                        # Delete all results for this task
                        cursor.execute("""
                            DELETE FROM results WHERE subject = ? AND task = ?
                        """, (subject_name, task_name))
                    # Delete task groups and task
                    cursor.execute("DELETE FROM task_groups WHERE task_id = ?", (task_id,))
                    cursor.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
                    conn.commit()
                    log_activity(username, f"deleted task {task_name} from {subject_name} and all related results")

        conn.close()
        return redirect(url_for("manage_tasks", subject_id=subject_id))


    # Get all groups — teachers can assign tasks to any group
    cursor.execute("SELECT DISTINCT group_name FROM users WHERE group_name IS NOT NULL ORDER BY group_name")
    all_groups = [row[0] for row in cursor.fetchall()]

    # Get available marking scripts
    available_scripts = get_marking_scripts()

    # Get available theory tests
    cursor.execute("SELECT id, title, subject FROM theory_tests ORDER BY title")
    available_theory_tests = cursor.fetchall()

    teachers = get_teachers()
    teacher_checkboxes = ''.join(
        f'<label style="display:inline-flex;align-items:center;gap:5px;">'
        f'<input type="checkbox" name="teachers" value="{escape(t[0])}"> {escape(t[1] or t[0])}</label>'
        for t in teachers
    )

    # Get tasks — all tasks visible, teachers can manage any
    cursor.execute("""
    SELECT t.id, t.name, t.assign_date, t.marking_script, t.task_type, t.theory_test_id,
           t.allow_multiple, t.max_attempts, t.is_active, t.question_text, t.sample_file_name,
           GROUP_CONCAT(DISTINCT tg.group_name),
           GROUP_CONCAT(DISTINCT tt.teacher_username)
    FROM tasks t
    LEFT JOIN task_groups tg ON t.id = tg.task_id
    LEFT JOIN task_teachers tt ON t.id = tt.task_id
    WHERE t.subject_id = ?
    GROUP BY t.id
    ORDER BY t.assign_date, t.name
    """, (subject_id,))
    tasks = cursor.fetchall()
    conn.close()

    task_list = ""
    for task_id, task_name, assign_date, marking_script, task_type, theory_test_id, allow_multiple, max_attempts, is_active, question_text, sample_file_name, group_list, teacher_list in tasks:
        if task_type == "theory":
            type_label = '<span style="background:#0078D4;color:white;padding:2px 6px;border-radius:10px;font-size:0.8em;">📝 Theory</span>'
            script_label = f'Test ID: {theory_test_id}'
        else:
            type_label = '<span style="background:#107C10;color:white;padding:2px 6px;border-radius:10px;font-size:0.8em;">📁 Practical</span>'
            script_label = marking_script if marking_script else '<span style="color:red;">None assigned</span>'

        status_badge = '<span style="background:#c8f7c5;color:#107C10;padding:2px 8px;border-radius:10px;font-size:0.8em;">Active</span>' if is_active else '<span style="background:#f7c5c5;color:#A4262C;padding:2px 8px;border-radius:10px;font-size:0.8em;">Inactive</span>'
        toggle_label = '⏸ Deactivate' if is_active else '▶ Activate'
        toggle_style = 'background:#ff8c00;color:white;' if is_active else 'background:#107C10;color:white;'

        if task_type == 'practical':
            attempts_label = 'Single' if not allow_multiple else f'Multiple ({max_attempts})'
        else:
            attempts_label = 'Theory task'

        task_list += f"""
        <tr>
            <td>{escape(task_name)} {type_label}</td>
            <td>{assign_date}</td>
            <td>{group_list or 'None'}</td>
            <td>{teacher_list or 'None'}</td>
            <td>{script_label}</td>
            <td>{f'<a href="/tasks/{task_id}/sample_file" target="_blank">{escape(sample_file_name)}</a>' if sample_file_name else 'None'}</td>
            <td>{attempts_label}</td>
            <td>{status_badge}</td>
            <td style="white-space:nowrap; vertical-align:middle;">
                {'<a href="/tasks/' + str(task_id) + '/edit" title="Edit task" class="btn btn-primary">✏️</a>' if task_type == 'practical' else ''}
                <a href="/tasks/{task_id}/preview" class="icon-btn" title="Preview learner view">👁</a>
                {'<button type="button" class="btn btn-success" title="Reuse: copy into a new task" onclick="openReuseTaskModal(' + str(task_id) + ', ' + repr(task_name) + ', ' + repr(marking_script or '') + ', ' + str(allow_multiple) + ', ' + str(max_attempts) + ')">📋</button>' if task_type == 'practical' else ''}
                <form method="post" action="/tasks/{task_id}/toggle" style="display:inline-flex; margin:0;">
                    <input type="hidden" name="subject_id" value="{subject_id}">
                    <button type="submit" title="{toggle_label}" class="btn" style="{toggle_style}">{'⏸' if is_active else '▶'}</button>
                </form>
                <form method="post" action="/tasks/{task_id}/clear_uploads" style="display:inline-flex; margin:0;"
                      onsubmit="return confirm('Clear ALL uploads for {escape(task_name)}? This cannot be undone.')">
                    <input type="hidden" name="subject_id" value="{subject_id}">
                    <button type="submit" title="Clear uploads" class="btn btn-danger">🗑</button>
                </form>
                <form method="post" style="display:inline-flex; margin:0;" onsubmit="return confirm('⚠️ WARNING: Delete task {escape(task_name)} and ALL STUDENT SUBMISSIONS?\n\nThis will permanently remove:\n- All student uploads and scores\n- Task from Group Results\n\nThis action CANNOT be undone!')">
                    <input type="hidden" name="action" value="delete">
                    <input type="hidden" name="task_id" value="{task_id}">
                    <button type="submit" title="Delete task" class="btn" style="background:#555;color:white;">🗑</button>
                </form>
            </td>
        </tr>
        """

    group_checkboxes = ""
    for group in all_groups:
        group_checkboxes += f'<label style="display:inline-flex;align-items:center;gap:5px;margin-right:10px;"><input type="checkbox" name="groups" value="{escape(group)}"> {escape(group)}</label>'

    script_options = '<option value="">-- No marking script --</option>'
    for script in available_scripts:
        script_options += f'<option value="{escape(script)}">{escape(script)}</option>'

    theory_test_options = '<option value="">-- Select Theory Test --</option>'
    for tt_id, tt_title, tt_subject in available_theory_tests:
        label = f"{tt_title}" + (f" ({tt_subject})" if tt_subject else "")
        theory_test_options += f'<option value="{tt_id}">{escape(label)}</option>'

    return render_template(
        "manage_tasks.html",
        subject_name=subject_name,
        script_options=script_options,
        group_checkboxes=group_checkboxes,
        teacher_checkboxes=teacher_checkboxes,
        task_list=task_list,
    )


@app.route("/tasks/<int:task_id>/preview")
def task_preview(task_id):
    username = session.get("username")
    if not username:
        return redirect(url_for("login"))

    role = get_user_role(username)
    if role not in ["teacher", "admin"]:
        return "Access denied", 403

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT t.name, t.assign_date, t.marking_script, t.question_text, t.task_type, t.theory_test_id, t.sample_file_name, s.name "
        "FROM tasks t JOIN subjects s ON t.subject_id = s.id WHERE t.id = ?",
        (task_id,),
    )
    task_row = cursor.fetchone()
    if not task_row:
        conn.close()
        return "Task not found", 404

    task_name, assign_date, marking_script, question_text, task_type, theory_test_id, sample_file_name, subject_name = task_row
    theory_test_title = None
    if task_type == "theory" and theory_test_id:
        cursor.execute("SELECT title FROM theory_tests WHERE id = ?", (theory_test_id,))
        test_row = cursor.fetchone()
        theory_test_title = test_row[0] if test_row else None

    conn.close()
    return render_template(
        "task_preview.html",
        subject_name=subject_name,
        task_name=task_name,
        assign_date=assign_date,
        task_type=task_type,
        marking_script=marking_script,
        question_text=question_text,
        sample_file_name=sample_file_name,
        sample_url=f"/tasks/{task_id}/sample_file" if sample_file_name else None,
        theory_test_title=theory_test_title,
        theory_test_id=theory_test_id,
    )


@app.route("/tasks/<int:task_id>/sample_file")
def download_sample_file(task_id):
    username = session.get("username")
    if not username:
        return redirect(url_for("login"))

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT sample_file, sample_file_name FROM tasks WHERE id = ?", (task_id,))
    row = cursor.fetchone()
    conn.close()

    if not row or not row[0]:
        return "Sample file not found", 404

    file_content, file_name = row
    return send_file(
        io.BytesIO(file_content),
        as_attachment=True,
        download_name=file_name,
        mimetype='application/octet-stream'
    )


# ── Theory Test Routes ───────────────────────────────────────────────────────

@app.route("/manage_tests")
def manage_tests():
    username = session.get("username")
    if not username:
        return redirect(url_for("login"))
    role = get_user_role(username)
    if role not in ["teacher", "admin"]:
        return "Access denied", 403

    conn = get_db()
    cursor = conn.cursor()
    # All teachers see all tests and can assign to any group
    cursor.execute("""
        SELECT
            t.id, t.title, t.subject, t.assign_date, t.time_limit, t.is_active,
            GROUP_CONCAT(DISTINCT tg.group_name),
            COUNT(DISTINCT q.id),
            t.allow_multiple, t.max_attempts, t.show_answers,
            GROUP_CONCAT(DISTINCT tt.teacher_username)
        FROM theory_tests t
        LEFT JOIN theory_questions q ON t.id = q.test_id
        LEFT JOIN theory_test_groups tg ON t.id = tg.test_id
        LEFT JOIN theory_test_teachers tt ON t.id = tt.test_id
        GROUP BY t.id
        ORDER BY t.created_at DESC
    """)
    tests = cursor.fetchall()
    groups = get_groups(username) if role == 'teacher' else get_groups()
    teachers = get_teachers()
    teacher_checkboxes = ''.join(
        f'<label style="font-weight:normal;display:inline-flex;align-items:center;gap:5px;">'
        f'<input type="checkbox" name="teachers" value="{escape(t[0])}"> {escape(t[1] or t[0])}</label>'
        for t in teachers
    )

    test_list = ""
    for test in tests:
        test_id = test[0]
        test_title = escape(test[1] or "")
        test_subject = escape(test[2] or "")
        assign_date = test[3] or '—'
        time_limit_val = test[4] or 0
        is_active = bool(test[5])
        groups_text = escape(test[6] or 'All Groups')
        question_count = test[7] or 0
        allow_multiple = bool(test[8])
        max_attempts = test[9] or 1
        show_answers = bool(test[10])
        teachers_text = escape(test[11] or 'All Teachers')

        status_badge = '<span class="badge-active">Active</span>' if is_active else '<span class="badge-inactive">Inactive</span>'
        attempt_text = f'{max_attempts} max' if allow_multiple else '1 (single)'
        toggle_label = 'Deactivate' if is_active else 'Activate'
        toggle_class = 'btn-warning' if is_active else 'btn-success'

        test_list += f"""
        <tr>
            <td>{test_title}</td>
            <td>{test_subject or '—'}</td>
            <td>{groups_text}</td>
            <td>{teachers_text}</td>
            <td>{question_count}</td>
            <td>{assign_date}</td>
            <td>{time_limit_val if time_limit_val else 'No limit'}</td>
            <td>{attempt_text}</td>
            <td>{'✔ Yes' if show_answers else '✘ No'}</td>
            <td>{status_badge}</td>
            <td style="white-space:nowrap; vertical-align:middle;">
                <a href="/manage_tests/{test_id}/questions" class="btn btn-primary" title="Edit questions">✏️</a>
                <a href="/manage_tests/{test_id}/edit" class="btn btn-warning" title="Edit settings">⚙️</a>
                <button type="button" class="btn btn-success" title="Reuse: copy questions into a new test"
                    onclick="openReuseModal(this)"
                    data-test-id="{test_id}"
                    data-title="{test_title}"
                    data-subject="{test_subject}"
                    data-time-limit="{time_limit_val}"
                    data-allow-multiple="{1 if allow_multiple else 0}"
                    data-max-attempts="{max_attempts}"
                    data-show-answers="{1 if show_answers else 0}">📋</button>
                <form method="post" action="/manage_tests/{test_id}/toggle" style="display:inline-flex; margin:0;">
                    <button type="submit" class="btn {toggle_class}" title="{toggle_label}">{'⏸' if is_active else '▶'}</button>
                </form>
                <form method="post" action="/manage_tests/{test_id}/delete" style="display:inline-flex; margin:0;"
                      onsubmit="return confirm('⚠️ WARNING: Delete this test, all questions, AND ALL STUDENT SUBMISSIONS?\n\nThis will permanently remove:\n- All test questions\n- All student attempts and scores\n- Test from Group Results\n\nThis action CANNOT be undone!')">
                    <button type="submit" class="btn btn-danger" title="Delete test">🗑</button>
                </form>
            </td>
        </tr>
        """

    conn.close()
    return render_template("manage_tests.html", tests=tests, groups=groups, teacher_checkboxes=teacher_checkboxes, test_list=test_list)


@app.route("/manage_tests/create", methods=["POST"])
def create_test():
    username = session.get("username")
    if not username:
        return redirect(url_for("login"))
    if get_user_role(username) not in ["teacher", "admin"]:
        return "Access denied", 403

    title = request.form.get("title", "").strip()
    subject = request.form.get("subject", "").strip()
    groups = request.form.getlist("groups")
    teachers = request.form.getlist("teachers")
    time_limit = request.form.get("time_limit", 0)
    assign_date = request.form.get("assign_date")  # YYYY-MM-DD
    allow_multiple = 1 if request.form.get("allow_multiple") else 0
    max_attempts = int(request.form.get("max_attempts", 1))
    show_answers = 1 if request.form.get("show_answers") else 0

    if not title:
        return "Test title is required", 400

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO theory_tests
            (title, subject, assign_date, time_limit, allow_multiple, max_attempts, show_answers, created_by, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (title, subject, assign_date, time_limit, allow_multiple, max_attempts, show_answers, username, datetime.now().isoformat()))
    test_id = cursor.lastrowid
    for g in groups:
        if g.strip():
            cursor.execute("INSERT INTO theory_test_groups (test_id, group_name) VALUES (?, ?)", (test_id, g))
    for teacher in teachers:
        if teacher.strip():
            cursor.execute("INSERT INTO theory_test_teachers (test_id, teacher_username) VALUES (?, ?)", (test_id, teacher))
    conn.commit()
    conn.close()
    log_activity(username, f"created theory test '{title}'")
    return redirect(url_for("manage_test_questions", test_id=test_id))


@app.route("/manage_tests/<int:test_id>/edit", methods=["GET", "POST"])
def edit_test(test_id):
    username = session.get("username")
    if not username:
        return redirect(url_for("login"))
    if get_user_role(username) not in ["teacher", "admin"]:
        return "Access denied", 403

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT id, title, subject, assign_date, time_limit, allow_multiple, max_attempts, show_answers FROM theory_tests WHERE id = ?", (test_id,))
    test = cursor.fetchone()
    if not test:
        conn.close()
        return "Test not found", 404

    if request.method == "POST":
        allow_multiple = 1 if request.form.get("allow_multiple") else 0
        max_attempts = int(request.form.get("max_attempts", 1))
        show_answers = 1 if request.form.get("show_answers") else 0
        groups = request.form.getlist("groups")
        teachers = request.form.getlist("teachers")

        assign_date = request.form.get("assign_date")
      #  time_limit = request.form.get("time_limit", 0)

        cursor.execute("""
            UPDATE theory_tests
            SET assign_date = ?, allow_multiple = ?, max_attempts = ?, show_answers = ?
            WHERE id = ?
        """, (assign_date, allow_multiple, max_attempts, show_answers, test_id))

        cursor.execute("DELETE FROM theory_test_groups WHERE test_id = ?", (test_id,))
        for g in groups:
            if g.strip():
                cursor.execute("INSERT INTO theory_test_groups (test_id, group_name) VALUES (?, ?)", (test_id, g))

        cursor.execute("DELETE FROM theory_test_teachers WHERE test_id = ?", (test_id,))
        for teacher in teachers:
            if teacher.strip():
                cursor.execute("INSERT INTO theory_test_teachers (test_id, teacher_username) VALUES (?, ?)", (test_id, teacher))

        conn.commit()
        conn.close()
        log_activity(username, f"edited theory test settings for test {test_id}")
        return redirect(url_for("manage_tests"))

    # GET — load current groups
    cursor.execute("SELECT group_name FROM theory_test_groups WHERE test_id = ?", (test_id,))
    current_groups = {row[0] for row in cursor.fetchall()}
    cursor.execute("SELECT teacher_username FROM theory_test_teachers WHERE test_id = ?", (test_id,))
    current_teachers = {row[0] for row in cursor.fetchall()}
    all_groups = get_groups()
    all_teachers = get_teachers()
    conn.close()

    return render_template("edit_test.html", test=test, current_groups=current_groups, all_groups=all_groups, all_teachers=all_teachers, current_teachers=current_teachers)


@app.route("/manage_tests/<int:test_id>/toggle", methods=["POST"])
def toggle_test(test_id):
    username = session.get("username")
    if not username:
        return redirect(url_for("login"))
    if get_user_role(username) not in ["teacher", "admin"]:
        return "Access denied", 403

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT is_active FROM theory_tests WHERE id = ?", (test_id,))
    row = cursor.fetchone()
    if row:
        new_state = 0 if row[0] else 1
        cursor.execute("UPDATE theory_tests SET is_active = ? WHERE id = ?", (new_state, test_id))
        conn.commit()
    conn.close()
    return redirect(url_for("manage_tests"))


@app.route("/manage_tests/<int:test_id>/delete", methods=["POST"])
def delete_test(test_id):
    username = session.get("username")
    if not username:
        return redirect(url_for("login"))
    if get_user_role(username) not in ["teacher", "admin"]:
        return "Access denied", 403

    conn = get_db()
    cursor = conn.cursor()
    
    # Get test title for logging
    cursor.execute("SELECT title FROM theory_tests WHERE id = ?", (test_id,))
    test_row = cursor.fetchone()
    test_title = test_row[0] if test_row else f"Test {test_id}"
    
    # Delete in order: answers → submissions → options → questions → test_groups → tasks → test
    cursor.execute("DELETE FROM theory_answers WHERE submission_id IN (SELECT id FROM theory_submissions WHERE test_id = ?)", (test_id,))
    cursor.execute("DELETE FROM theory_submissions WHERE test_id = ?", (test_id,))
    cursor.execute("DELETE FROM theory_options WHERE question_id IN (SELECT id FROM theory_questions WHERE test_id = ?)", (test_id,))
    cursor.execute("DELETE FROM theory_questions WHERE test_id = ?", (test_id,))
    cursor.execute("DELETE FROM theory_test_groups WHERE test_id = ?", (test_id,))
    # Also delete any tasks that reference this theory test
    cursor.execute("DELETE FROM task_groups WHERE task_id IN (SELECT id FROM tasks WHERE theory_test_id = ?)", (test_id,))
    cursor.execute("DELETE FROM tasks WHERE theory_test_id = ?", (test_id,))
    cursor.execute("DELETE FROM theory_tests WHERE id = ?", (test_id,))
    conn.commit()
    conn.close()
    log_activity(username, f"deleted theory test '{test_title}' and all related submissions")
    return redirect(url_for("manage_tests"))


@app.route("/manage_tests/<int:test_id>/questions", methods=["GET", "POST"])
def manage_test_questions(test_id):
    username = session.get("username")
    if not username:
        return redirect(url_for("login"))
    if get_user_role(username) not in ["teacher", "admin"]:
        return "Access denied", 403

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT id, title, subject FROM theory_tests WHERE id = ?", (test_id,))
    test = cursor.fetchone()
    if not test:
        conn.close()
        return "Test not found", 404

    if request.method == "POST":
        action = request.form.get("action")

        if action == "add_question":
            q_text = request.form.get("question_text", "").strip()
            q_type = request.form.get("question_type", "")
            marks = int(request.form.get("marks", 1))

            cursor.execute("SELECT COUNT(*) FROM theory_questions WHERE test_id = ?", (test_id,))
            order_index = cursor.fetchone()[0]

            cursor.execute("""
                INSERT INTO theory_questions (test_id, question_text, question_type, marks, order_index)
                VALUES (?, ?, ?, ?, ?)
            """, (test_id, q_text, q_type, marks, order_index))
            q_id = cursor.lastrowid

            # Handle options per question type
            if q_type in ["mcq_single", "mcq_multi"]:
                options = request.form.getlist("option_text")
                correct = request.form.getlist("is_correct")
                for i, opt in enumerate(options):
                    if opt.strip():
                        is_correct = 1 if str(i) in correct else 0
                        cursor.execute("""
                            INSERT INTO theory_options (question_id, option_text, is_correct)
                            VALUES (?, ?, ?)
                        """, (q_id, opt.strip(), is_correct))

            elif q_type == "true_false":
                correct_answer = request.form.get("tf_correct", "True")
                correction_term = request.form.get("correction_term", "").strip()
                cursor.execute("INSERT INTO theory_options (question_id, option_text, is_correct) VALUES (?, 'True', ?)",
                               (q_id, 1 if correct_answer == "True" else 0))
                cursor.execute("INSERT INTO theory_options (question_id, option_text, is_correct) VALUES (?, 'False', ?)",
                               (q_id, 1 if correct_answer == "False" else 0))
                if correction_term:
                    cursor.execute("INSERT INTO theory_options (question_id, option_text, is_correct, match_pair) VALUES (?, ?, 0, 'correction')",
                                   (q_id, correction_term))

            elif q_type == "fill_in":
                answer = request.form.get("fill_answer", "").strip()
                cursor.execute("INSERT INTO theory_options (question_id, option_text, is_correct) VALUES (?, ?, 1)",
                               (q_id, answer))

            elif q_type == "match":
                col_a = request.form.getlist("match_a")
                col_b = request.form.getlist("match_b")
                for a, b in zip(col_a, col_b):
                    if a.strip() and b.strip():
                        cursor.execute("""
                            INSERT INTO theory_options (question_id, option_text, is_correct, match_pair)
                            VALUES (?, ?, 1, ?)
                        """, (q_id, a.strip(), b.strip()))

            conn.commit()
            log_activity(username, f"added question to test {test_id}")

        elif action == "delete_question":
            q_id = request.form.get("question_id")
            cursor.execute("DELETE FROM theory_options WHERE question_id = ?", (q_id,))
            cursor.execute("DELETE FROM theory_questions WHERE id = ?", (q_id,))
            conn.commit()

        elif action == "edit_question":
            q_id = request.form.get("question_id")
            q_text = request.form.get("question_text", "").strip()
            marks = int(request.form.get("marks", 1))
            q_type = request.form.get("question_type", "")

            cursor.execute("UPDATE theory_questions SET question_text = ?, marks = ? WHERE id = ?",
                           (q_text, marks, q_id))

            # Replace all options
            cursor.execute("DELETE FROM theory_options WHERE question_id = ?", (q_id,))

            if q_type in ["mcq_single", "mcq_multi"]:
                options = request.form.getlist("option_text")
                correct = request.form.getlist("is_correct")
                for i, opt in enumerate(options):
                    if opt.strip():
                        is_correct = 1 if str(i) in correct else 0
                        cursor.execute("INSERT INTO theory_options (question_id, option_text, is_correct) VALUES (?, ?, ?)",
                                       (q_id, opt.strip(), is_correct))

            elif q_type == "true_false":
                correct_answer = request.form.get("tf_correct", "True")
                correction_term = request.form.get("correction_term", "").strip()
                cursor.execute("INSERT INTO theory_options (question_id, option_text, is_correct) VALUES (?, 'True', ?)",
                               (q_id, 1 if correct_answer == "True" else 0))
                cursor.execute("INSERT INTO theory_options (question_id, option_text, is_correct) VALUES (?, 'False', ?)",
                               (q_id, 1 if correct_answer == "False" else 0))
                if correction_term:
                    cursor.execute("INSERT INTO theory_options (question_id, option_text, is_correct, match_pair) VALUES (?, ?, 0, 'correction')",
                                   (q_id, correction_term))

            elif q_type == "fill_in":
                answer = request.form.get("fill_answer", "").strip()
                cursor.execute("INSERT INTO theory_options (question_id, option_text, is_correct) VALUES (?, ?, 1)",
                               (q_id, answer))

            elif q_type == "match":
                col_a = request.form.getlist("match_a")
                col_b = request.form.getlist("match_b")
                for a, b in zip(col_a, col_b):
                    if a.strip() and b.strip():
                        cursor.execute("INSERT INTO theory_options (question_id, option_text, is_correct, match_pair) VALUES (?, ?, 1, ?)",
                                       (q_id, a.strip(), b.strip()))

            conn.commit()
            log_activity(username, f"edited question {q_id} in test {test_id}")

        elif action == "import_questions_json":
            import_success = None
            import_error = None

            from theory_json_importer import insert_theory_test_from_json

            payload = request.form.get("questions_json", "").strip()
            # Append-only by default: checkbox checked => append
            append = request.form.get("append") is not None

            try:
                if not payload:
                    raise ValueError("questions_json is empty")

                if not append:
                    # Replace: clear existing questions/options for this test
                    cursor.execute("""
                        DELETE FROM theory_options
                        WHERE question_id IN (SELECT id FROM theory_questions WHERE test_id = ?)
                    """, (test_id,))
                    cursor.execute("DELETE FROM theory_questions WHERE test_id = ?", (test_id,))
                    start_order_index = 0
                else:
                    cursor.execute("""
                        SELECT COALESCE(MAX(order_index), -1) + 1
                        FROM theory_questions
                        WHERE test_id = ?
                    """, (test_id,))
                    start_order_index = cursor.fetchone()[0]

                insert_theory_test_from_json(
                    cursor,
                    test_id=test_id,
                    username=username,
                    payload=payload,
                    start_order_index=start_order_index
                )

                conn.commit()
                log_activity(username, f"imported questions into test {test_id} (append={append})")
                import_success = "Import completed successfully."

            except Exception as e:
                conn.rollback()
                import_error = str(e)

            # Reload questions and re-render (same page) with import status
            cursor.execute("""
                SELECT id, question_text, question_type, marks, order_index
                FROM theory_questions WHERE test_id = ? ORDER BY order_index
            """, (test_id,))
            questions = cursor.fetchall()

            questions_with_options = []
            for q in questions:
                cursor.execute("SELECT id, option_text, is_correct, match_pair FROM theory_options WHERE question_id = ?", (q[0],))
                options = cursor.fetchall()
                questions_with_options.append({"q": q, "options": options})

            conn.close()
            return render_template(
                "manage_test_questions.html",
                test=test,
                questions=questions_with_options,
                import_success=import_success,
                import_error=import_error
            )

        conn.close()
        return redirect(url_for("manage_test_questions", test_id=test_id))

    # GET — load questions with their options
    cursor.execute("""
        SELECT id, question_text, question_type, marks, order_index
        FROM theory_questions WHERE test_id = ? ORDER BY order_index
    """, (test_id,))
    questions = cursor.fetchall()

    questions_with_options = []
    for q in questions:
        cursor.execute("SELECT id, option_text, is_correct, match_pair FROM theory_options WHERE question_id = ?", (q[0],))
        options = cursor.fetchall()
        questions_with_options.append({"q": q, "options": options})

    conn.close()
    return render_template("manage_test_questions.html", test=test, questions=questions_with_options)


@app.route("/tests")
def learner_tests():
    """Show available tests to a learner."""
    username = session.get("username")
    if not username:
        return redirect(url_for("login"))

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT group_name FROM users WHERE username = ?", (username,))
    row = cursor.fetchone()
    user_group = row[0] if row else None

    cursor.execute("""
        SELECT t.id, t.title, t.subject, t.time_limit,
               best.best_percentage,
               sub.id as latest_submission_id,
               t.allow_multiple, t.max_attempts,
               COALESCE(cnt.attempt_count, 0) as attempt_count
        FROM theory_tests t
        LEFT JOIN (
            SELECT test_id, MAX(percentage) as best_percentage
            FROM theory_submissions WHERE username = ?
            GROUP BY test_id
        ) best ON t.id = best.test_id
        LEFT JOIN (
            SELECT test_id, id, percentage,
                   ROW_NUMBER() OVER (PARTITION BY test_id ORDER BY submitted_at DESC) as rn
            FROM theory_submissions WHERE username = ?
        ) sub ON t.id = sub.test_id AND sub.rn = 1
        LEFT JOIN (
            SELECT test_id, COUNT(*) as attempt_count
            FROM theory_submissions WHERE username = ?
            GROUP BY test_id
        ) cnt ON t.id = cnt.test_id
        WHERE t.is_active = 1
          AND (
              NOT EXISTS (SELECT 1 FROM theory_test_groups WHERE test_id = t.id)
              OR EXISTS (SELECT 1 FROM theory_test_groups WHERE test_id = t.id AND group_name = ?)
          )
        GROUP BY t.id
        ORDER BY t.created_at DESC
    """, (username, username, username, user_group))
    tests = cursor.fetchall()
    conn.close()
    return render_template("learner_tests.html", tests=tests)


@app.route("/my_tasks")
def learner_tasks():
    username = session.get("username")
    if not username:
        return redirect(url_for("login"))

    conn = get_db()
    cursor = conn.cursor()
    role = get_user_role(username)
    cursor.execute("SELECT group_name FROM users WHERE username = ?", (username,))
    row = cursor.fetchone()
    user_group = row[0] if row else None
    today = datetime.now().date().isoformat()

    if role in ["teacher", "admin"]:
        cursor.execute("""
            SELECT t.id, t.name, t.assign_date, t.task_type, t.allow_multiple,
                   t.max_attempts, t.is_active, t.theory_test_id, t.subject_id, s.name
            FROM tasks t
            JOIN subjects s ON t.subject_id = s.id
            ORDER BY t.assign_date, s.name, t.name
        """)
    else:
        cursor.execute("""
            SELECT t.id, t.name, t.assign_date, t.task_type, t.allow_multiple,
                   t.max_attempts, t.is_active, t.theory_test_id, t.subject_id, s.name
            FROM tasks t
            JOIN subjects s ON t.subject_id = s.id
            JOIN task_groups tg ON t.id = tg.task_id
            WHERE tg.group_name = ? AND t.assign_date <= ? AND t.is_active = 1
            ORDER BY t.assign_date, s.name, t.name
        """, (user_group, today))

    task_rows = cursor.fetchall()
    tasks = []
    for task_id, task_name, assign_date, task_type, allow_multiple, max_attempts, is_active, theory_test_id, subject_id, subject_name in task_rows:
        cursor.execute(
            "SELECT COUNT(*), COALESCE(MAX(score), 0) FROM results WHERE username = ? AND subject = ? AND task = ?",
            (username, subject_name, task_name)
        )
        submission_count, best_score = cursor.fetchone()
        submission_count = submission_count or 0

        tasks.append({
            "id": task_id,
            "name": task_name,
            "assign_date": assign_date,
            "task_type": task_type,
            "allow_multiple": allow_multiple,
            "max_attempts": max_attempts,
            "is_active": is_active,
            "theory_test_id": theory_test_id,
            "subject_id": subject_id,
            "subject": subject_name,
            "submission_count": submission_count,
            "best_score": best_score,
        })

    conn.close()
    return render_template("learner_tasks.html", tasks=tasks, username=username)


@app.route("/take_test/<int:test_id>", methods=["GET", "POST"])
def take_test(test_id):
    username = session.get("username")
    if not username:
        return redirect(url_for("login"))

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT id, title, subject, time_limit, allow_multiple, max_attempts, show_answers FROM theory_tests WHERE id = ? AND is_active = 1", (test_id,))
    test = cursor.fetchone()
    if not test:
        conn.close()
        return "Test not found or not available", 404

    # Check attempt count
    cursor.execute("SELECT COUNT(*) FROM theory_submissions WHERE test_id = ? AND username = ?", (test_id, username))
    attempt_count = cursor.fetchone()[0]
    allow_multiple = test[4]
    max_attempts = test[5]

    if not allow_multiple and attempt_count > 0:
        conn.close()
        return redirect(url_for("learner_tests"))

    if allow_multiple and attempt_count >= max_attempts:
        conn.close()
        return redirect(url_for("learner_tests"))

    cursor.execute("""
        SELECT id, question_text, question_type, marks
        FROM theory_questions WHERE test_id = ? ORDER BY order_index
    """, (test_id,))
    questions = cursor.fetchall()

    if request.method == "GET":
        # Shuffle options and store the order in session so POST uses same order
        questions_with_options = []
        session_order = {}
        for q in questions:
            cursor.execute("SELECT id, option_text, is_correct, match_pair FROM theory_options WHERE question_id = ?", (q[0],))
            options = list(cursor.fetchall())
            q_type = q[2]
            if q_type in ["mcq_single", "mcq_multi"]:
                random.shuffle(options)
            elif q_type == "match":
                # For match questions we only randomize Column B display order.
                # Keep Column A order stable so grading indices still match.
                # Structure of `options` for match questions is:
                #   (id, col_a_text, is_correct, match_pair_col_b_text)
                options = sorted(options, key=lambda o: o[0])
                b_opts = options[:]
                random.shuffle(b_opts)
                # Re-pack so Column A values remain in original order (options),
                # while Column B (match_pair) is shuffled for display.
                options = [
                    (o[0], o[1], o[2], b_opts[i][3])
                    for i, o in enumerate(options)
                ]
            # Store option IDs in shuffled order in session
            session_order[str(q[0])] = [o[0] for o in options]
            questions_with_options.append({"q": q, "options": options})
        session[f"test_order_{test_id}"] = session_order
        conn.close()
        return render_template("take_test.html", test=test, questions=questions_with_options, attempt_number=attempt_count + 1)

    # POST — restore shuffled order from session
    session_order = session.get(f"test_order_{test_id}", {})
    questions_with_options = []
    for q in questions:
        q_id = q[0]
        cursor.execute("SELECT id, option_text, is_correct, match_pair FROM theory_options WHERE question_id = ?", (q_id,))
        all_options = {o[0]: o for o in cursor.fetchall()}
        stored_ids = session_order.get(str(q_id), [])
        if stored_ids:
            options = [all_options[oid] for oid in stored_ids if oid in all_options]
        else:
            options = list(all_options.values())
        questions_with_options.append({"q": q, "options": options})

    # Now mark all questions
    score = 0
    total = 0
    answers_to_save = []

    for item in questions_with_options:
        q = item["q"]
        q_id, q_text, q_type, marks = q
        options = item["options"]
        effective_marks = len([o for o in options if o[3] and o[3] != 'correction']) if q_type == "match" else marks
        total += effective_marks
        awarded = 0
        answer_text = ""

        if q_type == "mcq_single":
            selected = request.form.get(f"q_{q_id}")
            answer_text = selected or ""
            cursor.execute("SELECT option_text FROM theory_options WHERE question_id = ? AND is_correct = 1 LIMIT 1", (q_id,))
            correct_row = cursor.fetchone()
            correct_option = correct_row[0] if correct_row else None
            if selected and selected == correct_option:
                awarded = marks

        elif q_type == "mcq_multi":
            selected = set(request.form.getlist(f"q_{q_id}"))
            cursor.execute("SELECT option_text FROM theory_options WHERE question_id = ? AND is_correct = 1", (q_id,))
            correct = set(row[0] for row in cursor.fetchall())
            answer_text = ", ".join(sorted(selected))
            if selected == correct:
                awarded = marks

        elif q_type == "true_false":
            selected = request.form.get(f"q_{q_id}")
            correction_submitted = request.form.get(f"q_{q_id}_correction", "").strip()
            answer_text = selected or ""
            if correction_submitted:
                answer_text += f" (correction: {correction_submitted})"
            cursor.execute("SELECT option_text FROM theory_options WHERE question_id = ? AND is_correct = 1 LIMIT 1", (q_id,))
            correct_row = cursor.fetchone()
            correct_option = correct_row[0] if correct_row else None
            cursor.execute("SELECT option_text FROM theory_options WHERE question_id = ? AND match_pair = 'correction' LIMIT 1", (q_id,))
            correction_row = cursor.fetchone()
            correction_term = correction_row[0] if correction_row else None
            if selected == correct_option:
                if selected == "False" and correction_term:
                    if correction_submitted.strip().upper() == correction_term.strip().upper():
                        awarded = effective_marks
                else:
                    awarded = effective_marks

        elif q_type == "fill_in":
            answer_text = request.form.get(f"q_{q_id}", "").strip()
            cursor.execute("SELECT option_text FROM theory_options WHERE question_id = ? AND is_correct = 1 LIMIT 1", (q_id,))
            correct_row = cursor.fetchone()
            correct = correct_row[0] if correct_row else ""
            if answer_text.upper() == correct.upper():
                awarded = marks

        elif q_type == "match":
            match_answers = []
            awarded = 0
            for idx, o in enumerate(options, start=1):
                col_a_item = o[1]
                col_b_correct = o[3]
                submitted = request.form.get(f"q_{q_id}_{idx}", "")
                match_answers.append(f"{col_a_item}={submitted}")
                if submitted == col_b_correct:
                    awarded += 1
            answer_text = "; ".join(match_answers)

        score += awarded
        answers_to_save.append((q_id, answer_text, 1 if awarded == effective_marks else 0, awarded))

    percentage = round((score / total) * 100) if total else 0

    cursor.execute("""
        INSERT INTO theory_submissions (test_id, username, score, total, percentage, submitted_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (test_id, username, score, total, percentage, datetime.now().isoformat()))
    submission_id = cursor.lastrowid

    for q_id, answer_text, is_correct, awarded in answers_to_save:
        cursor.execute("""
            INSERT INTO theory_answers (submission_id, question_id, answer_text, is_correct, marks_awarded)
            VALUES (?, ?, ?, ?, ?)
        """, (submission_id, q_id, answer_text, is_correct, awarded))

    conn.commit()
    conn.close()
    session.pop(f"test_order_{test_id}", None)
    log_activity(username, f"completed theory test {test_id} — {percentage}%")
    return redirect(url_for("test_results", submission_id=submission_id))


@app.route("/test_results/<int:submission_id>")
def test_results(submission_id):
    username = session.get("username")
    if not username:
        return redirect(url_for("login"))

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT s.id, s.score, s.total, s.percentage, s.submitted_at, t.title, t.subject,
               t.show_answers, t.allow_multiple, t.max_attempts, t.id as test_id
        FROM theory_submissions s
        JOIN theory_tests t ON s.test_id = t.id
        WHERE s.id = ? AND s.username = ?
    """, (submission_id, username))
    submission = cursor.fetchone()
    if not submission:
        conn.close()
        return "Results not found", 404

    test_id = submission[10]
    show_answers = submission[7]
    allow_multiple = submission[8]
    max_attempts = submission[9]

    # Count attempts and get best score
    cursor.execute("SELECT COUNT(*), MAX(percentage) FROM theory_submissions WHERE test_id = ? AND username = ?", (test_id, username))
    attempt_row = cursor.fetchone()
    attempts_used = attempt_row[0]
    best_percentage = attempt_row[1]
    can_retry = allow_multiple and attempts_used < max_attempts

    cursor.execute("""
        SELECT q.question_text, q.question_type, q.marks,
               a.answer_text, a.is_correct, a.marks_awarded, a.question_id
        FROM theory_answers a
        JOIN theory_questions q ON a.question_id = q.id
        WHERE a.submission_id = ?
        ORDER BY q.order_index
    """, (submission_id,))
    answers = cursor.fetchall()

    detailed = []
    for ans in answers:
        q_text, q_type, marks, answer_text, is_correct, marks_awarded, q_id = ans
        cursor.execute("""
            SELECT option_text, is_correct, match_pair
            FROM theory_options WHERE question_id = ?
        """, (q_id,))
        options = cursor.fetchall()
        detailed.append({
            "question": q_text,
            "type": q_type,
            "marks": marks,
            "answer": answer_text,
            "correct": is_correct,
            "awarded": marks_awarded,
            "options": options
        })

    conn.close()
    return render_template(
        "test_results.html",
        submission=submission,
        detailed=detailed,
        show_answers=show_answers,
        can_retry=can_retry,
        attempts_used=attempts_used,
        max_attempts=max_attempts,
        best_percentage=best_percentage,
        test_id=test_id
    )


@app.route("/manage_tests/<int:test_id>/reuse", methods=["POST"])
def reuse_test(test_id):
    username = session.get("username")
    if not username:
        return redirect(url_for("login"))
    if get_user_role(username) not in ["teacher", "admin"]:
        return "Access denied", 403

    title = request.form.get("title", "").strip()
    subject = request.form.get("subject", "").strip()
    assign_date = request.form.get("assign_date")
    time_limit = int(request.form.get("time_limit") or 0)
    allow_multiple = 1 if request.form.get("allow_multiple") else 0
    max_attempts = int(request.form.get("max_attempts") or 1)
    show_answers = 1 if request.form.get("show_answers") else 0
    groups = request.form.getlist("groups")

    if not title or not assign_date:
        return redirect(url_for("manage_tests"))

    conn = get_db()
    c = conn.cursor()

    # Create the new test
    c.execute("""
        INSERT INTO theory_tests
            (title, subject, assign_date, time_limit, allow_multiple, max_attempts,
             show_answers, created_by, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (title, subject, assign_date, time_limit, allow_multiple, max_attempts,
           show_answers, username, datetime.now().isoformat()))
    new_test_id = c.lastrowid

    for g in groups:
        if g.strip():
            c.execute("INSERT INTO theory_test_groups (test_id, group_name) VALUES (?, ?)", (new_test_id, g))

    # Fetch all questions and options from source test up front to avoid cursor conflicts
    c.execute("""
        SELECT id, question_text, question_type, marks, order_index
        FROM theory_questions WHERE test_id = ? ORDER BY order_index
    """, (test_id,))
    questions = c.fetchall()

    # Fetch all options for all questions at once
    if questions:
        q_ids = [q[0] for q in questions]
        placeholders = ','.join('?' * len(q_ids))
        c.execute(f"""
            SELECT question_id, option_text, is_correct, match_pair
            FROM theory_options WHERE question_id IN ({placeholders})
            ORDER BY question_id, id
        """, q_ids)
        all_options = c.fetchall()
    else:
        all_options = []

    # Group options by question_id
    from collections import defaultdict
    options_by_q = defaultdict(list)
    for opt in all_options:
        options_by_q[opt[0]].append(opt[1:])

    # Insert copied questions and options
    for q_id, q_text, q_type, marks, order_index in questions:
        c.execute("""
            INSERT INTO theory_questions (test_id, question_text, question_type, marks, order_index)
            VALUES (?, ?, ?, ?, ?)
        """, (new_test_id, q_text, q_type, marks, order_index))
        new_q_id = c.lastrowid
        for opt_text, is_correct, match_pair in options_by_q[q_id]:
            c.execute("""
                INSERT INTO theory_options (question_id, option_text, is_correct, match_pair)
                VALUES (?, ?, ?, ?)
            """, (new_q_id, opt_text, is_correct, match_pair))

    conn.commit()
    conn.close()
    log_activity(username, f"reused test {test_id} as '{title}'")
    return redirect(url_for("manage_test_questions", test_id=new_test_id))


if __name__ == "__main__":
    init_db()
    cleanup = threading.Thread(target=cleanup_thread, daemon=True)
    cleanup.start()
    
    app.run(host="0.0.0.0", port=5000, debug=True)

