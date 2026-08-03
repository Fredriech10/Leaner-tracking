import os
import tempfile
import unittest

import app as app_module


class CommunicationsRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_db.close()
        self.original_db_name = app_module.DB_NAME
        app_module.DB_NAME = self.temp_db.name
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
        app_module.DB_NAME = self.original_db_name
        if os.path.exists(self.temp_db.name):
            os.remove(self.temp_db.name)

    def test_reply_creates_thread_and_message(self):
        response = self.client.post(
            "/communications/reply",
            data={
                "student_username": "student1",
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
