import sqlite3
from datetime import datetime

DB_NAME = "school.db"


def get_db():
    return sqlite3.connect(DB_NAME)


def get_user_role(username):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT role FROM users WHERE username = ?", (username,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else "student"


def log_login(username):
    conn = get_db()
    cursor = conn.cursor()
    now = datetime.now()
    cursor.execute("INSERT INTO login_history (username, login_time, date) VALUES (?, ?, ?)",
                   (username, str(now), now.strftime("%Y-%m-%d")))
    conn.commit()
    conn.close()


def log_activity(username, action):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO activities (username, action, timestamp) VALUES (?, ?, ?)",
                   (username, action, datetime.now().isoformat()))
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


def update_last_active(username):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET last_active = ? WHERE username = ?",
                   (str(datetime.now()), username))
    conn.commit()
    conn.close()


def update_weakness(username, skills):
    conn = get_db()
    cursor = conn.cursor()
    for skill in skills:
        cursor.execute("""
        INSERT INTO weaknesses (username, skill, count) VALUES (?, ?, 1)
        ON CONFLICT(username, skill) DO UPDATE SET count = count + 1
        """, (username, skill))
    conn.commit()
    conn.close()


def save_result(username, subject, task, score, feedback):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO results (username, subject, task, score, feedback, timestamp)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (username, subject, task, score, feedback, str(datetime.now())))
    conn.commit()
    conn.close()


def get_groups():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT group_name FROM users WHERE group_name IS NOT NULL")
    groups = [g[0] for g in cursor.fetchall()]
    conn.close()
    return groups


def init_db():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT, subject TEXT, task TEXT,
        score INTEGER, feedback TEXT, timestamp TEXT
    )""")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS weaknesses (
        username TEXT, skill TEXT, count INTEGER,
        PRIMARY KEY (username, skill)
    )""")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY, role TEXT,
        last_active TEXT, full_name TEXT, group_name TEXT
    )""")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS login_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT, login_time TEXT, date TEXT
    )""")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS attendance_override (
        username TEXT, date TEXT, status TEXT,
        PRIMARY KEY (username, date)
    )""")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS excluded_dates (
        date TEXT, group_name TEXT, reason TEXT,
        created_by TEXT, created_at TEXT,
        PRIMARY KEY (date, group_name)
    )""")

    # Migration: excluded_dates group_name column
    try:
        cursor.execute("PRAGMA table_info(excluded_dates)")
        cols = [c[1] for c in cursor.fetchall()]
        if 'group_name' not in cols:
            cursor.execute("""CREATE TABLE excluded_dates_new (
                date TEXT, group_name TEXT, reason TEXT,
                created_by TEXT, created_at TEXT,
                PRIMARY KEY (date, group_name))""")
            cursor.execute("""INSERT INTO excluded_dates_new (date, group_name, reason, created_by, created_at)
                SELECT date, NULL, reason, created_by, created_at FROM excluded_dates""")
            cursor.execute("DROP TABLE excluded_dates")
            cursor.execute("ALTER TABLE excluded_dates_new RENAME TO excluded_dates")
    except Exception as e:
        print(f"Note: excluded_dates migration: {e}")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS activities (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT, action TEXT, timestamp TEXT
    )""")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS subjects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE, created_by TEXT, created_at TEXT
    )""")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS theory_tests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT, subject TEXT, assign_date TEXT,
        time_limit INTEGER, allow_multiple INTEGER DEFAULT 0,
        max_attempts INTEGER DEFAULT 1, show_answers INTEGER DEFAULT 1,
        created_by TEXT, created_at TEXT, is_active INTEGER DEFAULT 0
    )""")

    # theory_tests migrations
    try:
        cursor.execute("PRAGMA table_info(theory_tests)")
        cols = [c[1] for c in cursor.fetchall()]
        if "assign_date" not in cols:
            cursor.execute("ALTER TABLE theory_tests ADD COLUMN assign_date TEXT")
        if "group_name" in cols:
            cursor.execute("""CREATE TABLE theory_tests_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT, subject TEXT, time_limit INTEGER,
                allow_multiple INTEGER DEFAULT 0, max_attempts INTEGER DEFAULT 1,
                show_answers INTEGER DEFAULT 1, created_by TEXT,
                created_at TEXT, is_active INTEGER DEFAULT 0)""")
            cursor.execute("INSERT INTO theory_tests_new (id,title,subject,time_limit,created_by,created_at,is_active) SELECT id,title,subject,time_limit,created_by,created_at,is_active FROM theory_tests")
            cursor.execute("DROP TABLE theory_tests")
            cursor.execute("ALTER TABLE theory_tests_new RENAME TO theory_tests")
        else:
            for col in ["allow_multiple", "max_attempts", "show_answers"]:
                if col not in cols:
                    default = "0" if col != "max_attempts" else "1"
                    cursor.execute(f"ALTER TABLE theory_tests ADD COLUMN {col} INTEGER DEFAULT {default}")
    except Exception as e:
        print(f"Note: theory_tests migration: {e}")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS theory_test_groups (
        test_id INTEGER, group_name TEXT,
        PRIMARY KEY (test_id, group_name),
        FOREIGN KEY (test_id) REFERENCES theory_tests (id)
    )""")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS theory_questions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        test_id INTEGER, question_text TEXT, question_type TEXT,
        marks INTEGER DEFAULT 1, order_index INTEGER DEFAULT 0,
        FOREIGN KEY (test_id) REFERENCES theory_tests (id)
    )""")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS theory_options (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        question_id INTEGER, option_text TEXT,
        is_correct INTEGER DEFAULT 0, match_pair TEXT,
        FOREIGN KEY (question_id) REFERENCES theory_questions (id)
    )""")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS theory_submissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        test_id INTEGER, username TEXT, score INTEGER,
        total INTEGER, percentage INTEGER, submitted_at TEXT,
        FOREIGN KEY (test_id) REFERENCES theory_tests (id)
    )""")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS theory_answers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        submission_id INTEGER, question_id INTEGER,
        answer_text TEXT, is_correct INTEGER DEFAULT 0,
        marks_awarded INTEGER DEFAULT 0,
        FOREIGN KEY (submission_id) REFERENCES theory_submissions (id),
        FOREIGN KEY (question_id) REFERENCES theory_questions (id)
    )""")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        subject_id INTEGER, name TEXT, assign_date TEXT,
        marking_script TEXT, theory_test_id INTEGER,
        task_type TEXT DEFAULT 'practical',
        allow_multiple INTEGER DEFAULT 0, max_attempts INTEGER DEFAULT 1,
        is_active INTEGER DEFAULT 1, created_by TEXT, created_at TEXT,
        FOREIGN KEY (subject_id) REFERENCES subjects (id)
    )""")

    # tasks migrations
    try:
        cursor.execute("PRAGMA table_info(tasks)")
        cols = [c[1] for c in cursor.fetchall()]
        for col, defn in [("marking_script", "TEXT"), ("theory_test_id", "INTEGER"),
                          ("task_type", "TEXT DEFAULT 'practical'"),
                          ("allow_multiple", "INTEGER DEFAULT 0"),
                          ("max_attempts", "INTEGER DEFAULT 1"),
                          ("is_active", "INTEGER DEFAULT 1"),
                          ("sample_file", "BLOB"), ("sample_file_name", "TEXT")]:
            if col not in cols:
                cursor.execute(f"ALTER TABLE tasks ADD COLUMN {col} {defn}")
    except Exception as e:
        print(f"Note: tasks migration: {e}")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS learner_notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT, note TEXT, flag TEXT,
        created_by TEXT, created_at TEXT
    )""")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS result_removals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT, task_type TEXT, subject TEXT,
        task_name TEXT, test_id INTEGER, removed_by TEXT,
        reason TEXT, removed_at TEXT
    )""")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS task_groups (
        task_id INTEGER, group_name TEXT,
        PRIMARY KEY (task_id, group_name),
        FOREIGN KEY (task_id) REFERENCES tasks (id)
    )""")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS term_dates (
        term INTEGER PRIMARY KEY,
        start_date TEXT, end_date TEXT
    )""")

    # Seed subjects
    cursor.execute("SELECT COUNT(*) FROM subjects")
    if cursor.fetchone()[0] == 0:
        for subj in ["Word", "Excel", "Access", "HTML"]:
            cursor.execute("INSERT INTO subjects (name, created_by, created_at) VALUES (?, ?, ?)",
                           (subj, "system", datetime.now().isoformat()))

    conn.commit()
    conn.close()
