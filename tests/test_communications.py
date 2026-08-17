import os
import shutil
import tempfile
import unittest
import importlib.util


def load_entry_app():
    spec = importlib.util.spec_from_file_location(
        "learner_tracking_entry_app",
        os.path.join(os.path.dirname(__file__), "..", "app.py"),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


app_module = load_entry_app()
database_module = importlib.import_module("app.database")


class CommunicationsRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="learner-tracking-test-")
        self.temp_db_path = os.path.join(self.temp_dir, "test_school.db")
        self.original_db_name = database_module.DB_NAME
        database_module.DB_NAME = self.temp_db_path
        app_module.init_db()

        self.client = app_module.app.test_client()
        with self.client.session_transaction() as session:
            session["username"] = "teacher1"

        conn = app_module.get_db()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO users (username, role, last_active, full_name, group_name, teacher_username) VALUES (?, ?, ?, ?, ?, ?)",
            ("teacher1", "teacher", "now", "Teacher One", "Grade 10", "teacher1"),
        )
        cursor.execute(
            "INSERT OR REPLACE INTO users (username, role, last_active, full_name, group_name, teacher_username) VALUES (?, ?, ?, ?, ?, ?)",
            ("student1", "student", "now", "Student One", "Grade 10", "teacher1"),
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        database_module.DB_NAME = self.original_db_name
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_reply_creates_thread_and_message(self):
        conn = app_module.get_db()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO communication_threads (
                student_username, teacher_username, group_name, topic, subject_line,
                attendance_date, theory_test_id, status, chat_session_id, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "student1",
                "teacher1",
                "Grade 10",
                "chat",
                "Chat",
                "",
                None,
                "open",
                "session-1",
                "2026-08-17T09:00:00",
                "2026-08-17T09:00:00",
            ),
        )
        thread_id = cursor.lastrowid
        conn.commit()
        conn.close()

        response = self.client.post(
            "/communications/reply",
            data={
                "thread_id": thread_id,
                "message": "Please review my marks",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)

        conn = app_module.get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM communication_threads")
        self.assertEqual(cursor.fetchone()[0], 1)
        cursor.execute("SELECT COUNT(*) FROM communication_messages")
        self.assertEqual(cursor.fetchone()[0], 1)
        conn.close()


if __name__ == "__main__":
    unittest.main()
