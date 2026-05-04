from flask import Flask, request, redirect, url_for, render_template, session
from markupsafe import escape
from datetime import datetime, timedelta
import threading
import time
import os
import sqlite3
import random
from flask import send_file
import pandas as pd

TIMEOUT = 60

def update_active_user(username):
    """Update the last seen time for a user in the active_users dict"""
    with lock:
        active_users[username] = datetime.now()

def get_last_21_days():
    days = []
    current = datetime.now()

    while len(days) < 21:
        if current.weekday() < 5:  # Mon–Fri only
            days.append(current.strftime("%Y-%m-%d"))
        current -= timedelta(days=1)

    return list(reversed(days))

def get_last_7_days():
    days = []
    current = datetime.now()

    while len(days) < 7:
        if current.weekday() < 5:  # Mon–Fri only
            days.append(current.strftime("%Y-%m-%d"))
        current -= timedelta(days=1)

    return list(reversed(days))

# 🔹 Database setup
DB_NAME = "school.db"

def get_db():
    return sqlite3.connect(DB_NAME)


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
        group_name TEXT
    )
    """)

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
        time_limit INTEGER,
        allow_multiple INTEGER DEFAULT 0,
        max_attempts INTEGER DEFAULT 1,
        show_answers INTEGER DEFAULT 1,
        created_by TEXT,
        created_at TEXT,
        is_active INTEGER DEFAULT 0
    )
    """)

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
        if "is_active" not in columns:
            cursor.execute("ALTER TABLE tasks ADD COLUMN is_active INTEGER DEFAULT 1")
            print("Migration: added is_active column to tasks")
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
    CREATE TABLE IF NOT EXISTS task_groups (
        task_id INTEGER,
        group_name TEXT,
        PRIMARY KEY (task_id, group_name),
        FOREIGN KEY (task_id) REFERENCES tasks (id)
    )
    """)

    # Seed initial subjects if empty
    cursor.execute("SELECT COUNT(*) FROM subjects")
    if cursor.fetchone()[0] == 0:
        initial_subjects = ["Word", "Excel", "Access", "HTML"]
        for subj in initial_subjects:
            cursor.execute("INSERT INTO subjects (name, created_by, created_at) VALUES (?, ?, ?)",
                           (subj, "system", datetime.now().isoformat()))

    # Seed initial tasks if empty
    cursor.execute("SELECT COUNT(*) FROM tasks")
    if cursor.fetchone()[0] == 0:
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

def get_low_attendance_learners(limit=10):
    days = get_last_21_days()
    conn = get_db()
    cursor = conn.cursor()

    # Get excluded dates (global only for cross-group summary)
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

        absent = len(days) - present
        results.append((full_name or username, absent))

    conn.close()
    results.sort(key=lambda x: x[1], reverse=True)
    return results[:limit]

def get_marking_scripts():
    """Return a list of available marking script names from marking/tasks/."""
    tasks_dir = os.path.join(os.path.dirname(__file__), "marking", "tasks")
    scripts = []
    if os.path.exists(tasks_dir):
        for f in sorted(os.listdir(tasks_dir)):
            if f.endswith(".py") and f != "__init__.py":
                scripts.append(f[:-3])  # strip .py
    return scripts

def get_groups():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT DISTINCT group_name FROM users WHERE group_name IS NOT NULL")
    groups = [g[0] for g in cursor.fetchall()]

    conn.close()
    return groups

TASK_DEFINITIONS = [
    ("word", "task1"),
    ("word", "task2"),
    ("word", "task3"),
    ("excel", "task1"),
    ("excel", "task2"),
    ("excel", "task3"),
    ("access", "task1"),
    ("access", "task2"),
    ("access", "task3"),
    ("html", "task1"),
    ("html", "task2"),
    ("html", "task3")
]

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


def get_attendance_data(group, start_date=None, end_date=None):
    conn = get_db()
    cursor = conn.cursor()

    # If no dates provided, use last 7 days
    if not start_date or not end_date:
        days = get_last_7_days()
    else:
        # Generate business days (Mon-Fri) between start_date and end_date
        days = []
        current = datetime.strptime(start_date, "%Y-%m-%d").date()
        end = datetime.strptime(end_date, "%Y-%m-%d").date()
        
        while current <= end:
            if current.weekday() < 5:  # Mon-Fri only
                days.append(current.strftime("%Y-%m-%d"))
            current += timedelta(days=1)

    # Filter out excluded dates
    cursor.execute("""
    SELECT date FROM excluded_dates 
    WHERE group_name IS NULL OR group_name = ?
    """, (group,))
    excluded_dates = {row[0] for row in cursor.fetchall()}
    days = [day for day in days if day not in excluded_dates]

    cursor.execute("""
    SELECT username, full_name, group_name
    FROM users
    WHERE group_name = ?
    """, (group,))
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

    # ─ Missing tasks
    today = datetime.now().date().isoformat()
    cursor.execute("""
        SELECT t.id, s.name as subject_name, t.name, t.assign_date
        FROM tasks t
        JOIN subjects s ON t.subject_id = s.id
        JOIN task_groups tg ON t.id = tg.task_id
        WHERE tg.group_name = ? AND t.assign_date <= ?
        AND t.task_type = 'practical'
        AND NOT EXISTS (
            SELECT 1 FROM results r
            WHERE r.username = ? AND r.subject = s.name AND r.task = t.name
        )
        ORDER BY t.assign_date
        LIMIT 5
    """, (user_group, today, username))
    missing_tasks = cursor.fetchall()

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
        SELECT t.id, t.name, t.assign_date, t.marking_script, t.subject_id
        FROM tasks t WHERE t.id = ? AND t.task_type = 'practical'
    """, (task_id,))
    task = cursor.fetchone()
    if not task:
        conn.close()
        return "Task not found", 404

    subject_id = task[4]

    if request.method == "POST":
        assign_date = request.form.get("assign_date")
        marking_script = request.form.get("marking_script")
        groups = request.form.getlist("groups")

        cursor.execute("""
            UPDATE tasks SET assign_date = ?, marking_script = ? WHERE id = ?
        """, (assign_date, marking_script, task_id))

        cursor.execute("DELETE FROM task_groups WHERE task_id = ?", (task_id,))
        for g in groups:
            if g.strip():
                cursor.execute("INSERT INTO task_groups (task_id, group_name) VALUES (?, ?)", (task_id, g))

        conn.commit()
        conn.close()
        log_activity(username, f"edited task {task[1]}")
        return redirect(url_for("manage_tasks", subject_id=subject_id))

    # GET — load current groups and scripts
    cursor.execute("SELECT group_name FROM task_groups WHERE task_id = ?", (task_id,))
    current_groups = {row[0] for row in cursor.fetchall()}
    all_groups = get_groups()
    available_scripts = get_marking_scripts()
    conn.close()

    return render_template(
        "edit_task.html",
        task=task,
        current_groups=current_groups,
        all_groups=all_groups,
        available_scripts=available_scripts
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


@app.route("/tasks/<int:task_id>/clear_uploads", methods=["POST"])
def clear_task_uploads(task_id):
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

    # Get task with assign_date, marking_script and is_active
    cursor.execute("SELECT name, assign_date, marking_script, is_active FROM tasks WHERE id = ?", (task_id,))
    task_row = cursor.fetchone()
    if not task_row:
        conn.close()
        return "Task not found", 404
    task_name, assign_date, marking_script, task_is_active = task_row

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

    conn.close()

    if request.method == "POST":
        file = request.files.get("file")

        if not file:
            return "No file uploaded", 400

        temp_path = f"temp_{username}.xlsx"
        file.save(temp_path)

        try:
            result = mark_file(temp_path, marking_script)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

        if result["error"]:
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

        correct_list = "".join(f"<li>✅ {escape(r['question'])} ({r['marks_awarded']}/{r['marks_available']})</li>" for r in result["results"] if r["passed"])
        wrong_list = "".join(f"<li>❌ {escape(r['question'])} (0/{r['marks_available']})</li>" for r in result["results"] if not r["passed"])

        return f"""
        <p><a href="/student_dashboard">← Back to Dashboard</a></p>
        <h2>Results – {escape(subject_name)} {escape(task_name)}</h2>
        <p><strong>Score: {result['score']}/{result['total']} ({result['percentage']}%)</strong></p>
        <h3>✅ Correct</h3><ul>{correct_list}</ul>
        <h3>❌ Incorrect</h3><ul>{wrong_list}</ul>
        <a href="/subjects/{escape(username)}">← Back to Subjects</a>
        """

    return f"""
    <p><a href="/student_dashboard">← Back to Dashboard</a></p>
    <h2>Upload - {escape(subject_name).upper()} ({escape(task_name)})</h2>
    <form method="post" enctype="multipart/form-data">
        <input type="file" name="file" required>
        <button type="submit">Upload</button>
    </form>
    """


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

    # Avg attendance % across all students (last 21 days)
    days_21 = get_last_21_days()
    cursor.execute("SELECT COUNT(DISTINCT username) FROM login_history WHERE date IN ({}) ".format(
        ",".join(["?"]*len(days_21))), days_21)
    total_present_slots = cursor.execute(
        "SELECT COUNT(*) FROM login_history WHERE date IN ({})".format(",".join(["?"]*len(days_21))), days_21
    ).fetchone()[0]
    if total_students and len(days_21):
        avg_att_pct = round((total_present_slots / (total_students * len(days_21))) * 100)
    else:
        avg_att_pct = 0

    # ─ Group list
    groups = get_groups()

    # ─ Group attendance summary
    group_att = []
    for g in groups:
        cursor.execute("SELECT COUNT(*) FROM users WHERE group_name = ?", (g,))
        g_count = cursor.fetchone()[0]
        if g_count and days_21:
            cursor.execute(
                "SELECT COUNT(DISTINCT username) FROM login_history WHERE date IN ({}) AND username IN "
                "(SELECT username FROM users WHERE group_name = ?)".format(",".join(["?"]*len(days_21))),
                days_21 + [g]
            )
            g_present = cursor.fetchone()[0]
            g_pct = round((g_present / (g_count * len(days_21))) * 100)
        else:
            g_pct = 0
        group_att.append({"group": g, "students": g_count, "att_pct": g_pct})

    # ─ Low attendance learners
    low_attendance = get_low_attendance_learners(10)

    # ─ Recent activity (last 20)
    cursor.execute("""
        SELECT username, action, timestamp FROM activities
        ORDER BY timestamp DESC LIMIT 20
    """)
    recent_activities = cursor.fetchall()

    # ─ Recent submissions (last 15, best score per student per task)
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
    cursor.execute("""
        SELECT u.group_name, b.subject, ROUND(AVG(b.best_score),1), COUNT(*)
        FROM (
            SELECT username, subject, task, MAX(score) as best_score
            FROM results GROUP BY username, subject, task
        ) b
        JOIN users u ON u.username = b.username
        WHERE u.group_name IS NOT NULL
        GROUP BY u.group_name, b.subject
        ORDER BY u.group_name, b.subject
    """)
    class_avgs_raw = cursor.fetchall()

    from collections import defaultdict
    class_avgs = defaultdict(list)
    for group_name, subject, avg, cnt in class_avgs_raw:
        class_avgs[group_name].append((subject, avg, cnt))
    class_avgs = dict(class_avgs)

    # ─ Theory averages per subject per group (best attempt per student per test)
    cursor.execute("""
        SELECT u.group_name, tt.subject, ROUND(AVG(b.best_pct),1), COUNT(*)
        FROM (
            SELECT username, test_id, MAX(percentage) as best_pct
            FROM theory_submissions GROUP BY username, test_id
        ) b
        JOIN theory_tests tt ON b.test_id = tt.id
        JOIN users u ON u.username = b.username
        WHERE u.group_name IS NOT NULL AND tt.subject IS NOT NULL AND tt.subject != ''
        GROUP BY u.group_name, tt.subject
        ORDER BY u.group_name, tt.subject
    """)
    theory_avgs_raw = cursor.fetchall()
    theory_class_avgs = defaultdict(list)
    for group_name, subject, avg, cnt in theory_avgs_raw:
        theory_class_avgs[group_name].append((subject, avg, cnt))
    theory_class_avgs = dict(theory_class_avgs)

    # ─ Recent theory submissions (best per student per test)
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

    # ─ At-risk: low marks (<50%) using best score per task
    cursor.execute("""
        SELECT u.username, u.full_name, u.group_name,
               ROUND(AVG(b.best_score),1) as avg_score
        FROM users u
        LEFT JOIN (
            SELECT username, subject, task, MAX(score) as best_score
            FROM results GROUP BY username, subject, task
        ) b ON u.username = b.username
        WHERE u.role = 'student'
        GROUP BY u.username
        HAVING avg_score < 50 OR avg_score IS NULL
        ORDER BY avg_score ASC LIMIT 10
    """)
    at_risk_marks = cursor.fetchall()

    # At-risk by attendance (< 60% in last 21 days)
    at_risk_att = [(name, absent) for name, absent in low_attendance
                   if len(days_21) > 0 and (len(days_21) - absent) / len(days_21) < 0.6]

    # ─ Missing tasks count per group
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
        class_avgs=class_avgs,
        theory_class_avgs=theory_class_avgs,
        top_performers=top_performers,
        bottom_performers=bottom_performers,
        at_risk_marks=at_risk_marks,
        at_risk_att=at_risk_att,
        missing_by_group=missing_by_group
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

def calculate_attendance_percentage(data, days):
    total_cells = len(data) * len(days)
    present = 0

    for row in data:
        for d in days:
            if row["days"].get(d):
                present += 1

    return round((present / total_cells) * 100) if total_cells else 0

@app.route("/attendance")
def attendance():
    username = session.get("username")
    if not username:
        return redirect(url_for("login"))

    if get_user_role(username) not in ["teacher", "admin"]:
        return "Access denied", 403

    selected_group = request.args.get("group")
    edit_mode = request.args.get("edit") == "1"   # ✅ key line

    groups = get_groups()

    days = []
    data = []

    if selected_group:
        days, data = get_attendance_data(selected_group)

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

    return render_template(
        "attendance.html",
        groups=groups,
        selected_group=selected_group,
        days=days,
        data=data,
        edit_mode=edit_mode,
        today=datetime.now().strftime("%Y-%m-%d"),   # ✅ add today's date
        excluded_dates=excluded_dates
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
    SELECT username, full_name, group_name, role, last_active
    FROM users
    WHERE 1=1
    """
    params = []

    # Remove server-side search filtering to enable client-side live search
    # if search:
    #     query += " AND (username LIKE ? OR full_name LIKE ? OR group_name LIKE ? OR role LIKE ?)"
    #     search_term = f"%{search}%"
    #     params.extend([search_term, search_term, search_term, search_term])

    if group:
        query += " AND group_name = ?"
        params.append(group)

    query += f" ORDER BY {valid_sorts[sort]} {order.upper()}"

    cursor.execute(query, params)
    users = cursor.fetchall()

    # Get group list for dropdown
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

    cursor.execute("SELECT username, action, strftime('%Y-%m-%d %H:%M:%S', timestamp) FROM activities ORDER BY timestamp DESC LIMIT 100")
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

    if request.method == "POST":
        full_name = request.form.get("full_name")
        group_name = request.form.get("group_name")

        cursor.execute("""
        UPDATE users
        SET full_name = ?, group_name = ?
        WHERE username = ?
        """, (full_name, group_name, username))

        conn.commit()
        log_activity(admin_user, f"edited user {username}")
        conn.close()
        if next_url:
            return redirect(next_url)
        return redirect(url_for("admin_panel"))

    cursor.execute("SELECT username, full_name, group_name FROM users WHERE username = ?", (username,))
    user = cursor.fetchone()
    conn.close()

    return render_template("edit_user.html", user=user, next_url=next_url)

@app.route("/learner_record/<username>")
def learner_record(username):
    admin_user = session.get("username")
    if not admin_user:
        return redirect(url_for("login"))
    if get_user_role(admin_user) not in ["teacher", "admin"]:
        return "Access denied", 403

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT username, full_name, group_name, role, last_active FROM users WHERE username = ?", (username,))
    user = cursor.fetchone()
    if not user:
        conn.close()
        return "User not found", 404

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


@app.route("/export/results")
def export_results():
    username = session.get("username")
    if not username:
        return redirect(url_for("login"))

    if get_user_role(username) not in ["teacher", "admin"]:
        return "Access denied", 403

    all_groups = get_groups()
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
    days, data = get_attendance_data(group)

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

@app.route("/group_results")
def group_results():
    username = session.get("username")
    if not username:
        return redirect(url_for("login"))

    if get_user_role(username) not in ["teacher", "admin"]:
        return "Access denied", 403

    selected_group = request.args.get("group")
    groups = get_groups()

    if not selected_group:
        return render_template("group_results.html", groups=groups, selected_group=None)

    conn = get_db()
    cursor = conn.cursor()

    # Get all students in the group
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

    if get_user_role(username) not in ["teacher", "admin"]:
        return "Access denied", 403

    all_groups = get_groups()

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

    with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
        for group in selected_groups:
            days, data = get_attendance_data(group)

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
    SELECT username FROM users WHERE group_name = ?
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
    SELECT username FROM users WHERE group_name = ?
    """, (group,))
    users = [u[0] for u in cursor.fetchall()]

    if users:
        # 🔹 Mark all as present (insert/update overrides)
        for user in users:
            cursor.execute("""
            INSERT INTO attendance_override (username, date, status)
            VALUES (?, ?, ?)
            ON CONFLICT(username, date)
            DO UPDATE SET status = excluded.status
            """, (user, date, "present"))

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
        cursor.execute("""
        INSERT INTO attendance_override (username, date, status)
        VALUES (?, ?, ?)
        ON CONFLICT(username, date)
        DO UPDATE SET status = excluded.status
        """, (user, day, status))

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
    SELECT username FROM users WHERE group_name = ?
    """, (group,))
    users = [u[0] for u in cursor.fetchall()]

    if users:
        # 🔹 Mark all as absent (insert/update overrides)
        for user in users:
            cursor.execute("""
            INSERT INTO attendance_override (username, date, status)
            VALUES (?, ?, ?)
            ON CONFLICT(username, date)
            DO UPDATE SET status = excluded.status
            """, (user, date, "absent"))

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

    days, data = get_attendance_data(group, start_date, end_date)

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

        return redirect(url_for("manage_subjects"))

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM subjects ORDER BY name")
    subjects = cursor.fetchall()
    conn.close()

    subject_list = ""
    for subj_id, subj_name in subjects:
        subject_list += f"""
        <tr>
            <td>{escape(subj_name)}</td>
            <td><a href="/manage_tasks/{subj_id}">Manage Tasks</a></td>
            <td>
                <form method="post" style="display:inline;">
                    <input type="hidden" name="action" value="delete">
                    <input type="hidden" name="subject_id" value="{subj_id}">
                    <button type="submit" onclick="return confirm('Delete subject {escape(subj_name)} and ALL related tasks and results? This cannot be undone!')">Delete</button>
                </form>
            </td>
        </tr>
        """

    return f"""
    <p><a href="/teacher_dashboard">← Back to Teacher Dashboard</a></p>
    <h2>Manage Subjects</h2>

    <h3>Create New Subject</h3>
    <form method="post">
        <input type="hidden" name="action" value="create">
        <label>Subject Name:</label>
        <input type="text" name="subject_name" required>
        <button type="submit">Create</button>
    </form>

    <h3>Existing Subjects</h3>
    <table border="1">
        <tr>
            <th>Subject</th>
            <th>Tasks</th>
            <th>Actions</th>
        </tr>
        {subject_list}
    </table>
    """

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
            groups = request.form.getlist("groups")
            if task_name and assign_date:
                cursor.execute("INSERT INTO tasks (subject_id, name, assign_date, marking_script, task_type, created_by, created_at) VALUES (?, ?, ?, ?, 'practical', ?, ?)",
                               (subject_id, task_name, assign_date, marking_script, username, datetime.now().isoformat()))
                task_id = cursor.lastrowid
                for group in groups:
                    cursor.execute("INSERT INTO task_groups (task_id, group_name) VALUES (?, ?)", (task_id, group))
                conn.commit()
                log_activity(username, f"created task {task_name} in {subject_name}")
        elif action == "assign_theory":
            task_name = request.form.get("task_name")
            assign_date = request.form.get("assign_date")
            theory_test_id = request.form.get("theory_test_id")
            groups = request.form.getlist("groups")
            if task_name and assign_date and theory_test_id:
                cursor.execute("INSERT INTO tasks (subject_id, name, assign_date, theory_test_id, task_type, created_by, created_at) VALUES (?, ?, ?, ?, 'theory', ?, ?)",
                               (subject_id, task_name, assign_date, theory_test_id, username, datetime.now().isoformat()))
                task_id = cursor.lastrowid
                for group in groups:
                    cursor.execute("INSERT INTO task_groups (task_id, group_name) VALUES (?, ?)", (task_id, group))
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

    # Get all groups
    cursor.execute("SELECT DISTINCT group_name FROM users WHERE group_name IS NOT NULL ORDER BY group_name")
    all_groups = [row[0] for row in cursor.fetchall()]

    # Get available marking scripts
    available_scripts = get_marking_scripts()

    # Get available theory tests
    cursor.execute("SELECT id, title, subject FROM theory_tests ORDER BY title")
    available_theory_tests = cursor.fetchall()

    # Get tasks
    cursor.execute("""
    SELECT t.id, t.name, t.assign_date, t.marking_script, t.task_type, t.theory_test_id, t.is_active, GROUP_CONCAT(tg.group_name, ', ')
    FROM tasks t
    LEFT JOIN task_groups tg ON t.id = tg.task_id
    WHERE t.subject_id = ?
    GROUP BY t.id
    ORDER BY t.assign_date, t.name
    """, (subject_id,))
    tasks = cursor.fetchall()
    conn.close()

    task_list = ""
    for task_id, task_name, assign_date, marking_script, task_type, theory_test_id, is_active, group_list in tasks:
        if task_type == "theory":
            type_label = '<span style="background:#0078D4;color:white;padding:2px 6px;border-radius:10px;font-size:0.8em;">📝 Theory</span>'
            script_label = f'Test ID: {theory_test_id}'
        else:
            type_label = '<span style="background:#107C10;color:white;padding:2px 6px;border-radius:10px;font-size:0.8em;">📁 Practical</span>'
            script_label = marking_script if marking_script else '<span style="color:red;">None assigned</span>'

        status_badge = '<span style="background:#c8f7c5;color:#107C10;padding:2px 8px;border-radius:10px;font-size:0.8em;">Active</span>' if is_active else '<span style="background:#f7c5c5;color:#A4262C;padding:2px 8px;border-radius:10px;font-size:0.8em;">Inactive</span>'
        toggle_label = '⏸ Deactivate' if is_active else '▶ Activate'
        toggle_style = 'background:#ff8c00;color:white;' if is_active else 'background:#107C10;color:white;'

        task_list += f"""
        <tr>
            <td>{escape(task_name)} {type_label}</td>
            <td>{assign_date}</td>
            <td>{group_list or 'None'}</td>
            <td>{script_label}</td>
            <td>{status_badge}</td>
            <td style="display:flex;gap:5px;flex-wrap:wrap;">
                {'<a href="/tasks/' + str(task_id) + '/edit" style="padding:4px 10px;border:none;border-radius:4px;cursor:pointer;font-size:0.85em;background:#0078D4;color:white;text-decoration:none;">✏️ Edit</a>' if task_type == 'practical' else ''}
                <form method="post" action="/tasks/{task_id}/toggle" style="display:inline;">
                    <input type="hidden" name="subject_id" value="{subject_id}">
                    <button type="submit" style="padding:4px 10px;border:none;border-radius:4px;cursor:pointer;font-size:0.85em;{toggle_style}">{toggle_label}</button>
                </form>
                <form method="post" action="/tasks/{task_id}/clear_uploads" style="display:inline;"
                      onsubmit="return confirm('Clear ALL uploads for {escape(task_name)}? This cannot be undone.')">
                    <input type="hidden" name="subject_id" value="{subject_id}">
                    <button type="submit" style="padding:4px 10px;border:none;border-radius:4px;cursor:pointer;font-size:0.85em;background:#A4262C;color:white;">🗑 Clear Uploads</button>
                </form>
                <form method="post" style="display:inline;" onsubmit="return confirm('⚠️ WARNING: Delete task {escape(task_name)} and ALL STUDENT SUBMISSIONS?\n\nThis will permanently remove:\n- All student uploads and scores\n- Task from Group Results\n\nThis action CANNOT be undone!')">
                    <input type="hidden" name="action" value="delete">
                    <input type="hidden" name="task_id" value="{task_id}">
                    <button type="submit" style="padding:4px 10px;border:none;border-radius:4px;cursor:pointer;font-size:0.85em;background:#555;color:white;">Delete</button>
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

    return f"""
    <p><a href="/manage_subjects">← Back to Subjects</a></p>
    <h2>Manage Tasks for {escape(subject_name)}</h2>

    <h3>Add New Task</h3>
    <div style="margin-bottom:15px;">
        <button type="button" onclick="showPanel('practical')" id="btn_practical"
                style="padding:8px 18px;background:#0078D4;color:white;border:none;border-radius:4px 0 0 4px;cursor:pointer;font-size:0.95em;">
            📁 Practical Task
        </button>
        <a href="/manage_tests"
           style="padding:8px 18px;background:#ccc;color:#333;border:none;border-radius:0 4px 4px 0;cursor:pointer;font-size:0.95em;text-decoration:none;display:inline-block;">
            📝 Theory Tests →
        </a>
    </div>

    <div id="panel_practical" style="background:#f9f9f9;border:1px solid #ddd;padding:20px;border-radius:6px;">
        <form method="post">
            <input type="hidden" name="action" value="create">
            <label>Task Name:</label><br>
            <input type="text" name="task_name" required style="padding:7px;width:300px;margin-bottom:10px;"><br>
            <label>Assign Date:</label><br>
            <input type="date" name="assign_date" required style="padding:7px;margin-bottom:10px;"><br>
            <label>Marking Script:</label><br>
            <select name="marking_script" style="padding:7px;margin-bottom:10px;">{script_options}</select><br>
            <label>Assigned Groups:</label><br>
            <div style="margin:8px 0;">{group_checkboxes}</div>
            <button type="submit" style="padding:8px 16px;background:#107C10;color:white;border:none;border-radius:4px;cursor:pointer;">Create Practical Task</button>
        </form>
    </div>

    <script>
    function showPanel(type) {{
        document.getElementById('panel_practical').style.display = type === 'practical' ? 'block' : 'none';
        document.getElementById('btn_practical').style.background = type === 'practical' ? '#0078D4' : '#ccc';
        document.getElementById('btn_practical').style.color = type === 'practical' ? 'white' : '#333';
    }}
    </script>

    <h3>Existing Tasks</h3>
    <table border="1" style="border-collapse:collapse;width:100%;">
        <tr>
            <th>Task</th>
            <th>Assign Date</th>
            <th>Groups</th>
            <th>Marking / Test</th>
            <th>Status</th>
            <th>Actions</th>
        </tr>
        {task_list}
    </table>
    """

# ── Theory Test Routes ───────────────────────────────────────────────────────

@app.route("/manage_tests")
def manage_tests():
    username = session.get("username")
    if not username:
        return redirect(url_for("login"))
    if get_user_role(username) not in ["teacher", "admin"]:
        return "Access denied", 403

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT t.id, t.title, t.subject, t.time_limit, t.is_active,
               COUNT(DISTINCT q.id) as question_count,
               GROUP_CONCAT(DISTINCT tg.group_name) as groups,
               t.allow_multiple, t.max_attempts, t.show_answers
        FROM theory_tests t
        LEFT JOIN theory_questions q ON t.id = q.test_id
        LEFT JOIN theory_test_groups tg ON t.id = tg.test_id
        GROUP BY t.id
        ORDER BY t.created_at DESC
    """)
    tests = cursor.fetchall()
    groups = get_groups()
    conn.close()
    return render_template("manage_tests.html", tests=tests, groups=groups)


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
    time_limit = request.form.get("time_limit", 0)
    allow_multiple = 1 if request.form.get("allow_multiple") else 0
    max_attempts = int(request.form.get("max_attempts", 1))
    show_answers = 1 if request.form.get("show_answers") else 0

    if not title:
        return "Test title is required", 400

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO theory_tests (title, subject, time_limit, allow_multiple, max_attempts, show_answers, created_by, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (title, subject, time_limit, allow_multiple, max_attempts, show_answers, username, datetime.now().isoformat()))
    test_id = cursor.lastrowid
    for g in groups:
        if g.strip():
            cursor.execute("INSERT INTO theory_test_groups (test_id, group_name) VALUES (?, ?)", (test_id, g))
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

    cursor.execute("SELECT id, title, subject, time_limit, allow_multiple, max_attempts, show_answers FROM theory_tests WHERE id = ?", (test_id,))
    test = cursor.fetchone()
    if not test:
        conn.close()
        return "Test not found", 404

    if request.method == "POST":
        allow_multiple = 1 if request.form.get("allow_multiple") else 0
        max_attempts = int(request.form.get("max_attempts", 1))
        show_answers = 1 if request.form.get("show_answers") else 0
        groups = request.form.getlist("groups")

        cursor.execute("""
            UPDATE theory_tests
            SET allow_multiple = ?, max_attempts = ?, show_answers = ?
            WHERE id = ?
        """, (allow_multiple, max_attempts, show_answers, test_id))

        cursor.execute("DELETE FROM theory_test_groups WHERE test_id = ?", (test_id,))
        for g in groups:
            if g.strip():
                cursor.execute("INSERT INTO theory_test_groups (test_id, group_name) VALUES (?, ?)", (test_id, g))

        conn.commit()
        conn.close()
        log_activity(username, f"edited theory test settings for test {test_id}")
        return redirect(url_for("manage_tests"))

    # GET — load current groups
    cursor.execute("SELECT group_name FROM theory_test_groups WHERE test_id = ?", (test_id,))
    current_groups = {row[0] for row in cursor.fetchall()}
    all_groups = get_groups()
    conn.close()

    return render_template("edit_test.html", test=test, current_groups=current_groups, all_groups=all_groups)


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
                random.shuffle(options)
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


if __name__ == "__main__":
    init_db()
    cleanup = threading.Thread(target=cleanup_thread, daemon=True)
    cleanup.start()
    
    app.run(host="0.0.0.0", port=5000, debug=True)

