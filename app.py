from flask import Flask, request, redirect, url_for, render_template, session
from markupsafe import escape
from datetime import datetime, timedelta
import threading
import time
import os
import sqlite3
from datetime import datetime, timedelta
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
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        subject_id INTEGER,
        name TEXT,
        assign_date TEXT,
        created_by TEXT,
        created_at TEXT,
        FOREIGN KEY (subject_id) REFERENCES subjects (id)
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

# 🔹 Demo marking function (replace later with your real one)
def mark_file(filepath):
    score = 75
    feedback = "Struggled with formatting and formulas"
    weak_skills = ["Formatting", "Formulas"]

    return score, feedback, weak_skills

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

    for user, name, group in learners:
        row = {
            "username": user,
            "name": name,
            "group": group,
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

    # Update active user timestamp
    update_active_user(username)

    # Get user's full name
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT full_name FROM users WHERE username = ?", (username,))
    user_row = cursor.fetchone()
    conn.close()
    
    display_name = user_row[0] if user_row and user_row[0] else username

    averages, overall, recent_results = get_student_dashboard_data(username)
    weaknesses = get_weaknesses(username)

    return render_template(
        "dashboard.html",
        display_name=display_name,
        averages=averages,
        overall=overall,
        recent_results=recent_results,
        weaknesses=weaknesses
    )

# 🔹 Auto-login for bat
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

    # Get task with assign_date
    cursor.execute("SELECT name, assign_date FROM tasks WHERE id = ?", (task_id,))
    task_row = cursor.fetchone()
    if not task_row:
        conn.close()
        return "Task not found", 404
    task_name, assign_date = task_row

    # Get user role and group
    user_role = get_user_role(username)
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
            score, feedback, weak_skills = mark_file(temp_path)
            update_weakness(username, weak_skills)

            save_result(username, subject_name, task_name, score, feedback)
            log_activity(username, f"submitted {subject_name} {task_name}")

        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

        return f"""
        <p><a href="/student_dashboard">← Back to Dashboard</a></p>
        <h2>Result</h2>
        <p>Subject: {escape(subject_name)}</p>
        <p>Task: {escape(task_name)}</p>
        <p>Score: {score}</p>
        <p>Feedback: {escape(feedback)}</p>
        <a href="/subjects/{escape(username)}">Back to Subjects</a>
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

    # Verify the logged-in user is the one accessing
    session_user = session.get("username")
    if session_user != username:
        return "Unauthorized", 401

    # Update active user timestamp
    update_active_user(username)

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT id, name FROM subjects ORDER BY name")
    all_subjects = cursor.fetchall()

    conn.close()

    if not all_subjects:
        return f"""
        <p><a href="/student_dashboard">← Back to Dashboard</a></p>
        <h2>Select Subject</h2>
        <p>No subjects available yet.</p>
        """

    subject_links = ""
    for subj_id, subj_name in all_subjects:
        subject_links += f'<a href="/tasks/{escape(username)}/{subj_id}">📁 {escape(subj_name)}</a><br>\n'

    return f"""
    <p><a href="/student_dashboard">← Back to Dashboard</a></p>
    <h2>Select Subject</h2>
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

@app.route("/teacher_dashboard")
def teacher_dashboard():
    username = session.get("username")
    if not username:
        return redirect(url_for("login"))

    if not username:
        return redirect(url_for("login"))

    role = get_user_role(username)

    if role not in ["teacher", "admin"]:
        return "Access denied", 403

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT u.full_name, u.group_name, r.subject, r.task, r.score, r.feedback, r.timestamp
    FROM results r
    JOIN users u ON r.username = u.username
    ORDER BY r.timestamp DESC
    """)
    all_results = cursor.fetchall()

    cursor.execute("""
    SELECT username, skill, count
    FROM weaknesses
    ORDER BY count DESC
    """)
    all_weaknesses = cursor.fetchall()

    cursor.execute("""
    SELECT username, action, timestamp
    FROM activities
    ORDER BY timestamp DESC
    LIMIT 10
    """)
    recent_activities = cursor.fetchall()

    conn.close()

    return render_template(
        "teacher_dashboard.html",
        results=all_results,
        weaknesses=all_weaknesses,
        recent_activities=recent_activities
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
    if get_user_role(admin_user) not in ["teacher", "admin"]:
        return "Access denied", 403

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT username, full_name, group_name, role FROM users WHERE username = ?", (username,))
    user = cursor.fetchone()
    if not user:
        conn.close()
        return "User not found", 404

    days = get_last_21_days()
    history = []

    cursor.execute("SELECT group_name FROM users WHERE username = ?", (username,))
    group_row = cursor.fetchone()
    user_group = group_row[0] if group_row else None

    for day in days:
        cursor.execute("SELECT MIN(login_time) FROM login_history WHERE username = ? AND date = ?", (username, day))
        login_time = cursor.fetchone()[0]

        cutoff = None
        if user_group:
            cutoff = get_group_late_threshold(user_group, day)

        if login_time:
            time_str = login_time.split(" ")[1][:5]
            late = cutoff is not None and time_str > cutoff
            history.append({
                "date": day,
                "status": "Present",
                "time": time_str,
                "late": late,
                "note": "Auto"
            })
        else:
            cursor.execute("SELECT status FROM attendance_override WHERE username = ? AND date = ?", (username, day))
            override = cursor.fetchone()

            if override and override[0] == "present":
                history.append({
                    "date": day,
                    "status": "Present",
                    "time": "12:00",
                    "late": False,
                    "note": "Manual"
                })
            else:
                history.append({
                    "date": day,
                    "status": "Absent",
                    "time": "",
                    "late": False,
                    "note": "Manual" if override else "None"
                })

    cursor.execute(
        "SELECT subject, task, score, feedback, timestamp FROM results WHERE username = ? ORDER BY timestamp DESC",
        (username,)
    )
    results = cursor.fetchall()

    results_map = {
        (row[0], row[1]): {
            "score": row[2],
            "feedback": row[3],
            "timestamp": row[4]
        }
        for row in results
    }

    task_rows = []
    for subject, task in TASK_DEFINITIONS:
        row = results_map.get((subject, task))
        task_rows.append({
            "subject": subject,
            "task": task,
            "score": row["score"] if row else None,
            "feedback": row["feedback"] if row else None,
            "timestamp": row["timestamp"] if row else None,
            "status": "Submitted" if row else "Not submitted"
        })

    submitted_scores = [task["score"] for task in task_rows if task["score"] is not None]
    average = round(sum(submitted_scores) / len(submitted_scores), 1) if submitted_scores else 0

    conn.close()
    return render_template(
        "learner_record.html",
        user=user,
        history=history,
        task_rows=task_rows,
        average=average
    )

@app.route("/export/results")
def export_results():
    username = session.get("username")

    if get_user_role(username) not in ["teacher", "admin"]:
        return "Access denied", 403

    conn = get_db()

    df = pd.read_sql_query("""
    SELECT u.full_name, u.group_name, r.subject, r.task, r.score, r.feedback, r.timestamp
    FROM results r
    JOIN users u ON r.username = u.username
    """, conn)

    file_path = f"results_export_{username}.xlsx"
    df.to_excel(file_path, index=False)

    log_activity(username, "exported results")

    conn.close()

    return send_file(file_path, as_attachment=True)

@app.route("/export/attendance")
def export_attendance():
    username = session.get("username")

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

@app.route("/export_attendance_form")
def export_attendance_form():
    username = session.get("username")

    if get_user_role(username) not in ["teacher", "admin"]:
        return "Access denied", 403

    all_groups = get_groups()

    return render_template("export_attendance.html", all_groups=all_groups)

@app.route("/export_attendance_multi", methods=["POST"])
def export_attendance_multi():
    username = session.get("username")

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

    return send_file(file_path, as_attachment=True)

@app.route("/reset_attendance", methods=["POST"])
def reset_attendance():
    username = session.get("username")

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

    if get_user_role(username) not in ["teacher", "admin"]:
        return "Access denied", 403

    date = request.form.get("date")
    group = request.form.get("group")  # Can be None for global, or specific group
    reason = request.form.get("reason", "")

    if not date:
        return "Missing date", 400

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

    if get_user_role(username) not in ["teacher", "admin"]:
        return "Access denied", 403

    date = request.form.get("date")
    group = request.form.get("group")  # Can be None for global, or specific group

    if not date:
        return "Missing date", 400

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
                    cursor.execute("DELETE FROM task_groups WHERE task_id IN (SELECT id FROM tasks WHERE subject_id = ?)", (subject_id,))
                    cursor.execute("DELETE FROM tasks WHERE subject_id = ?", (subject_id,))
                    cursor.execute("DELETE FROM subjects WHERE id = ?", (subject_id,))
                    conn.commit()
                    log_activity(username, f"deleted subject {subj[0]}")
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
                    <button type="submit" onclick="return confirm('Delete subject {escape(subj_name)}?')">Delete</button>
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
            groups = request.form.getlist("groups")
            if task_name and assign_date:
                cursor.execute("INSERT INTO tasks (subject_id, name, assign_date, created_by, created_at) VALUES (?, ?, ?, ?, ?)",
                               (subject_id, task_name, assign_date, username, datetime.now().isoformat()))
                task_id = cursor.lastrowid
                for group in groups:
                    cursor.execute("INSERT INTO task_groups (task_id, group_name) VALUES (?, ?)", (task_id, group))
                conn.commit()
                log_activity(username, f"created task {task_name} in {subject_name}")
        elif action == "delete":
            task_id = request.form.get("task_id")
            if task_id:
                cursor.execute("SELECT name FROM tasks WHERE id = ?", (task_id,))
                tsk = cursor.fetchone()
                if tsk:
                    cursor.execute("DELETE FROM task_groups WHERE task_id = ?", (task_id,))
                    cursor.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
                    conn.commit()
                    log_activity(username, f"deleted task {tsk[0]} from {subject_name}")

        conn.close()
        return redirect(url_for("manage_tasks", subject_id=subject_id))

    # Get all groups
    cursor.execute("SELECT DISTINCT group_name FROM users WHERE group_name IS NOT NULL ORDER BY group_name")
    all_groups = [row[0] for row in cursor.fetchall()]

    # Get tasks
    cursor.execute("""
    SELECT t.id, t.name, t.assign_date, GROUP_CONCAT(tg.group_name, ', ')
    FROM tasks t
    LEFT JOIN task_groups tg ON t.id = tg.task_id
    WHERE t.subject_id = ?
    GROUP BY t.id
    ORDER BY t.assign_date, t.name
    """, (subject_id,))
    tasks = cursor.fetchall()
    conn.close()

    task_list = ""
    for task_id, task_name, assign_date, group_list in tasks:
        task_list += f"""
        <tr>
            <td>{escape(task_name)}</td>
            <td>{assign_date}</td>
            <td>{group_list or 'None'}</td>
            <td>
                <form method="post" style="display:inline;">
                    <input type="hidden" name="action" value="delete">
                    <input type="hidden" name="task_id" value="{task_id}">
                    <button type="submit" onclick="return confirm('Delete task {escape(task_name)}?')">Delete</button>
                </form>
            </td>
        </tr>
        """

    group_checkboxes = ""
    for group in all_groups:
        group_checkboxes += f'<input type="checkbox" name="groups" value="{escape(group)}"> {escape(group)}<br>'

    return f"""
    <p><a href="/manage_subjects">← Back to Subjects</a></p>
    <h2>Manage Tasks for {escape(subject_name)}</h2>

    <h3>Create New Task</h3>
    <form method="post">
        <input type="hidden" name="action" value="create">
        <label>Task Name:</label>
        <input type="text" name="task_name" required><br><br>
        <label>Assign Date:</label>
        <input type="date" name="assign_date" required><br><br>
        <label>Assigned Groups:</label><br>
        {group_checkboxes}<br>
        <button type="submit">Create Task</button>
    </form>

    <h3>Existing Tasks</h3>
    <table border="1">
        <tr>
            <th>Task</th>
            <th>Assign Date</th>
            <th>Groups</th>
            <th>Actions</th>
        </tr>
        {task_list}
    </table>
    """

if __name__ == "__main__":
    init_db()
    cleanup = threading.Thread(target=cleanup_thread, daemon=True)
    cleanup.start()
    
    app.run(host="0.0.0.0", port=5000, debug=True)

