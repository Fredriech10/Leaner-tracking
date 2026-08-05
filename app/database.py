import sqlite3
from datetime import datetime

DB_NAME = "school.db"
MARKING_DB_NAME = "marking_experiment.db"
SQLITE_BUSY_TIMEOUT_MS = 30000


def _connect_sqlite(path):
    conn = sqlite3.connect(path, timeout=30)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
    except sqlite3.DatabaseError:
        pass
    return conn


def get_db():
    return _connect_sqlite(DB_NAME)


def get_marking_db():
    return _connect_sqlite(MARKING_DB_NAME)


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


def init_marking_db():
    conn = get_marking_db()
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS marking_setups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        created_by TEXT,
        created_at TEXT,
        updated_at TEXT,
        question_paper_filename TEXT,
        question_paper_blob BLOB,
        memo_filename TEXT,
        memo_blob BLOB,
        json_script_filename TEXT,
        json_script_blob BLOB,
        llm_model TEXT,
        generation_warnings TEXT,
        generation_error TEXT,
        notes TEXT
    )
    """)
    try:
        cursor.execute("PRAGMA table_info(marking_setups)")
        columns = [col[1] for col in cursor.fetchall()]
        for column_name, definition in [
            ("memo_filename", "TEXT"),
            ("memo_blob", "BLOB"),
            ("llm_model", "TEXT"),
            ("generation_warnings", "TEXT"),
            ("generation_error", "TEXT"),
        ]:
            if column_name not in columns:
                cursor.execute(f"ALTER TABLE marking_setups ADD COLUMN {column_name} {definition}")
    except Exception as exc:
        print(f"Note: marking_setups migration: {exc}")
    conn.commit()
    conn.close()


def get_groups(username=None):
    conn = get_db()
    cursor = conn.cursor()

    if username:
        role = get_user_role(username)
        if role == "teacher":
            group_set = set()
            cursor.execute("SELECT group_name FROM group_teachers WHERE teacher_username = ?", (username,))
            group_set.update(g[0] for g in cursor.fetchall() if g[0])
            cursor.execute(
                "SELECT DISTINCT group_name FROM users WHERE role = 'student' AND teacher_username = ? AND group_name IS NOT NULL",
                (username,),
            )
            group_set.update(g[0] for g in cursor.fetchall() if g[0])
            conn.close()
            return sorted(group_set)

    cursor.execute("SELECT DISTINCT group_name FROM users WHERE group_name IS NOT NULL")
    groups = [g[0] for g in cursor.fetchall()]
    conn.close()
    return groups


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
        recent_results or [],
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


def get_teachers():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT username, full_name FROM users WHERE role = 'teacher' ORDER BY full_name")
    teachers = cursor.fetchall()
    conn.close()
    return teachers


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


def import_users_from_excel():
    try:
        import pandas as pd

        df = pd.read_excel("Users/grade12.xlsx")

        conn = get_db()
        cursor = conn.cursor()

        imported_count = 0
        updated_count = 0

        for _, row in df.iterrows():
            username = str(row["username"]).strip().upper()
            full_name = str(row["full_name"]).strip()
            group_name = str(row["group"]).strip()

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
        status TEXT,
        PRIMARY KEY (username, date)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS communication_threads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_username TEXT NOT NULL,
        teacher_username TEXT,
        group_name TEXT,
        topic TEXT NOT NULL,
        subject_line TEXT,
        attendance_date TEXT,
        status TEXT DEFAULT 'open',
        chat_session_id TEXT,
        created_at TEXT,
        updated_at TEXT,
        teacher_read_at TEXT,
        student_read_at TEXT
    )
    """)

    try:
        cursor.execute("PRAGMA table_info(communication_threads)")
        thread_cols = [c[1] for c in cursor.fetchall()]
        if "teacher_read_at" not in thread_cols:
            cursor.execute("ALTER TABLE communication_threads ADD COLUMN teacher_read_at TEXT")
        if "student_read_at" not in thread_cols:
            cursor.execute("ALTER TABLE communication_threads ADD COLUMN student_read_at TEXT")
    except Exception as e:
        print(f"Note: communication_threads migration check: {e}")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS communication_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        thread_id INTEGER NOT NULL,
        sender_username TEXT NOT NULL,
        sender_role TEXT,
        message TEXT NOT NULL,
        created_at TEXT,
        FOREIGN KEY(thread_id) REFERENCES communication_threads(id)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS teacher_quick_actions (
        username TEXT NOT NULL,
        action_key TEXT NOT NULL,
        PRIMARY KEY (username, action_key)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS excluded_dates (
        date TEXT,
        group_name TEXT,
        reason TEXT,
        created_by TEXT,
        created_at TEXT,
        PRIMARY KEY (date, group_name)
    )
    """)

    try:
        cursor.execute("PRAGMA table_info(excluded_dates)")
        columns = cursor.fetchall()
        column_names = [col[1] for col in columns]
        if "group_name" not in column_names:
            print("Migrating excluded_dates table...")
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
            cursor.execute("""
            INSERT INTO excluded_dates_new (date, group_name, reason, created_by, created_at)
            SELECT date, NULL, reason, created_by, created_at FROM excluded_dates
            """)
            cursor.execute("DROP TABLE excluded_dates")
            cursor.execute("ALTER TABLE excluded_dates_new RENAME TO excluded_dates")
            print("Migration completed successfully")
    except Exception as e:
        print(f"Note: Migration check completed with: {e}")

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
        background_image TEXT,
        background_fit TEXT DEFAULT 'cover',
        assign_date TEXT,
        time_limit INTEGER,
        allow_multiple INTEGER DEFAULT 0,
        max_attempts INTEGER DEFAULT 1,
        show_answers INTEGER DEFAULT 1,
        created_by TEXT,
        created_at TEXT,
        is_active INTEGER DEFAULT 0
    )
    """)

    try:
        cursor.execute("PRAGMA table_info(theory_tests)")
        cols = [c[1] for c in cursor.fetchall()]
        if "assign_date" not in cols:
            cursor.execute("ALTER TABLE theory_tests ADD COLUMN assign_date TEXT")
            print("Migration: added assign_date column to theory_tests")
    except Exception as e:
        print(f"Note: theory_tests assign_date migration: {e}")

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
            if "background_image" not in cols:
                cursor.execute("ALTER TABLE theory_tests ADD COLUMN background_image TEXT")
            if "background_fit" not in cols:
                cursor.execute("ALTER TABLE theory_tests ADD COLUMN background_fit TEXT DEFAULT 'cover'")
    except Exception as e:
        print(f"Note: theory_tests migration: {e}")

    try:
        cursor.execute("PRAGMA table_info(theory_tests)")
        cols = [c[1] for c in cursor.fetchall()]
        if "background_image" not in cols:
            cursor.execute("ALTER TABLE theory_tests ADD COLUMN background_image TEXT")
        if "background_fit" not in cols:
            cursor.execute("ALTER TABLE theory_tests ADD COLUMN background_fit TEXT DEFAULT 'cover'")
    except Exception as e:
        print(f"Note: theory_tests background migration: {e}")

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

    try:
        cursor.execute("PRAGMA table_info(theory_questions)")
        theory_question_cols = [c[1] for c in cursor.fetchall()]
        if "bank_question_id" not in theory_question_cols:
            cursor.execute("ALTER TABLE theory_questions ADD COLUMN bank_question_id INTEGER")
        if "source_subject" not in theory_question_cols:
            cursor.execute("ALTER TABLE theory_questions ADD COLUMN source_subject TEXT")
        if "source_modules" not in theory_question_cols:
            cursor.execute("ALTER TABLE theory_questions ADD COLUMN source_modules TEXT")
    except Exception as e:
        print(f"Note: theory_questions source migration: {e}")

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
    CREATE TABLE IF NOT EXISTS question_bank_questions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        question_text TEXT,
        question_type TEXT,
        marks INTEGER DEFAULT 1,
        subject TEXT,
        modules TEXT,
        created_by TEXT,
        created_at TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS question_bank_options (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        bank_question_id INTEGER,
        option_text TEXT,
        is_correct INTEGER DEFAULT 0,
        match_pair TEXT,
        FOREIGN KEY (bank_question_id) REFERENCES question_bank_questions (id)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS theory_progress (
        test_id INTEGER,
        username TEXT,
        current_slide INTEGER DEFAULT 0,
        max_slide INTEGER DEFAULT 0,
        time_spent_seconds INTEGER DEFAULT 0,
        completed INTEGER DEFAULT 0,
        updated_at TEXT,
        PRIMARY KEY (test_id, username),
        FOREIGN KEY (test_id) REFERENCES theory_tests (id)
    )
    """)

    try:
        cursor.execute("PRAGMA table_info(theory_progress)")
        progress_cols = [c[1] for c in cursor.fetchall()]
        if "max_slide" not in progress_cols:
            cursor.execute("ALTER TABLE theory_progress ADD COLUMN max_slide INTEGER DEFAULT 0")
        if "time_spent_seconds" not in progress_cols:
            cursor.execute("ALTER TABLE theory_progress ADD COLUMN time_spent_seconds INTEGER DEFAULT 0")
    except Exception as e:
        print(f"Note: theory_progress migration: {e}")

    try:
        cursor.execute("PRAGMA table_info(theory_submissions)")
        sub_cols = [c[1] for c in cursor.fetchall()]
        if "time_spent_seconds" not in sub_cols:
            cursor.execute("ALTER TABLE theory_submissions ADD COLUMN time_spent_seconds INTEGER DEFAULT 0")
        if "submission_type" not in sub_cols:
            cursor.execute("ALTER TABLE theory_submissions ADD COLUMN submission_type TEXT DEFAULT 'test'")
    except Exception as e:
        print(f"Note: theory_submissions time/type migration: {e}")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS theory_lesson_groups (
        lesson_id INTEGER,
        group_name TEXT,
        PRIMARY KEY (lesson_id, group_name),
        FOREIGN KEY (lesson_id) REFERENCES theory_lessons (id)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS theory_lesson_teachers (
        lesson_id INTEGER,
        teacher_username TEXT,
        PRIMARY KEY (lesson_id, teacher_username),
        FOREIGN KEY (lesson_id) REFERENCES theory_lessons (id)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS theory_lesson_checkpoints (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lesson_id INTEGER,
        slide_number INTEGER,
        question_text TEXT,
        option_a TEXT,
        option_b TEXT,
        option_c TEXT,
        option_d TEXT,
        correct_option TEXT,
        explanation TEXT,
        sort_order INTEGER DEFAULT 0,
        FOREIGN KEY (lesson_id) REFERENCES theory_lessons (id)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS theory_lesson_progress (
        lesson_id INTEGER,
        username TEXT,
        current_slide INTEGER DEFAULT 1,
        completed_at TEXT,
        PRIMARY KEY (lesson_id, username),
        FOREIGN KEY (lesson_id) REFERENCES theory_lessons (id)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS theory_lesson_checkpoint_answers (
        lesson_id INTEGER,
        checkpoint_id INTEGER,
        username TEXT,
        selected_option TEXT,
        is_correct INTEGER DEFAULT 0,
        answered_at TEXT,
        PRIMARY KEY (checkpoint_id, username),
        FOREIGN KEY (lesson_id) REFERENCES theory_lessons (id),
        FOREIGN KEY (checkpoint_id) REFERENCES theory_lesson_checkpoints (id)
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
        marking_setup_id INTEGER,
        created_by TEXT,
        created_at TEXT,
        FOREIGN KEY (subject_id) REFERENCES subjects (id)
    )
    """)

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
        if "marking_setup_id" not in columns:
            cursor.execute("ALTER TABLE tasks ADD COLUMN marking_setup_id INTEGER")
            print("Migration: added marking_setup_id column to tasks")
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
        term INTEGER PRIMARY KEY,
        start_date TEXT,
        end_date TEXT
    )
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_results_user_subject_task ON results (username, subject, task)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_results_user_timestamp ON results (username, timestamp)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_login_history_user_date ON login_history (username, date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_login_history_date_user ON login_history (date, username)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_attendance_override_user_date ON attendance_override (username, date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_role_teacher_group ON users (role, teacher_username, group_name)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_group_role ON users (group_name, role)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_theory_submissions_user_test ON theory_submissions (username, test_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_theory_submissions_test_user ON theory_submissions (test_id, username)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_task_groups_group_task ON task_groups (group_name, task_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_theory_test_groups_group_test ON theory_test_groups (group_name, test_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tasks_assign_type ON tasks (assign_date, task_type)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_theory_tests_assign_date ON theory_tests (assign_date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_excluded_dates_group_date ON excluded_dates (group_name, date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_communication_threads_teacher_updated ON communication_threads (teacher_username, updated_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_communication_messages_thread_created ON communication_messages (thread_id, created_at)")

    cursor.execute("SELECT COUNT(*) FROM subjects")
    if cursor.fetchone()[0] == 0:
        initial_subjects = ["Word", "Excel", "Access", "HTML"]
        for subj in initial_subjects:
            cursor.execute("INSERT INTO subjects (name, created_by, created_at) VALUES (?, ?, ?)",
                           (subj, "system", datetime.now().isoformat()))

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
                cursor.execute("SELECT DISTINCT group_name FROM users WHERE group_name IS NOT NULL")
                groups = cursor.fetchall()
                for group_row in groups:
                    cursor.execute("INSERT INTO task_groups (task_id, group_name) VALUES (?, ?)", (task_id, group_row[0]))

    conn.commit()
    conn.close()
