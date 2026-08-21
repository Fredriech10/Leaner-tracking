import sqlite3
from datetime import datetime

from .database import get_db


def get_teacher_quick_action_catalog():
    return [
        {"key": "manage_subjects", "label": "Practical", "icon": "📁", "href": "/manage_subjects", "kind": "link"},
        {"key": "manage_lessons", "label": "Lesson Setup", "icon": "📘", "href": "/manage_lessons", "kind": "link"},
        {"key": "manage_tests", "label": "Theory Tests", "icon": "📝", "href": "/manage_tests", "kind": "link"},
        {"key": "response_review", "label": "Review Responses", "icon": "🧾", "href": "/response_review", "kind": "link"},
        {"key": "marking_setup", "label": "Marking Setup", "icon": "🛠️", "href": "/marking_setup", "kind": "link"},
        {"key": "attendance", "label": "Attendance", "icon": "📅", "href": "/attendance", "kind": "link"},
        {"key": "group_results", "label": "Results", "icon": "📊", "href": "/group_results", "kind": "link"},
        {"key": "communications", "label": "Messages", "icon": "💬", "href": "/communications", "kind": "link"},
        {"key": "export", "label": "Export", "icon": "⬇️", "kind": "export"},
        {"key": "view_group", "label": "View Group", "icon": "👁", "kind": "view_group"},
    ]


def get_teacher_selected_quick_actions(username):
    catalog = get_teacher_quick_action_catalog()
    catalog_map = {item["key"]: item for item in catalog}
    default_keys = ["manage_subjects", "manage_tests", "attendance", "communications", "response_review", "export", "view_group"]
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT action_key
        FROM teacher_quick_actions
        WHERE username = ?
        ORDER BY rowid
        """,
        (username,),
    )
    stored_keys = [row[0] for row in cursor.fetchall()]
    conn.close()
    selected = [catalog_map[key] for key in stored_keys if key in catalog_map]
    if not selected:
        selected = [catalog_map[key] for key in default_keys if key in catalog_map]
    selected_keys = {item["key"] for item in selected}
    available = [dict(item, selected=item["key"] in selected_keys) for item in catalog]
    return selected, available


def get_teacher_unread_message_count(username):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT COUNT(*)
        FROM communication_threads t
        WHERE t.teacher_username = ?
          AND EXISTS (
              SELECT 1
              FROM communication_messages m
              WHERE m.thread_id = t.id
                AND COALESCE(m.sender_role, '') = 'student'
                AND (t.teacher_read_at IS NULL OR COALESCE(m.created_at, '') > t.teacher_read_at)
          )
        """,
        (username,),
    )
    count = cursor.fetchone()[0] or 0
    conn.close()
    return count


def get_student_unread_message_count(username):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT COUNT(*)
        FROM communication_threads t
        WHERE t.student_username = ?
          AND EXISTS (
              SELECT 1
              FROM communication_messages m
              WHERE m.thread_id = t.id
                AND COALESCE(m.sender_role, '') IN ('teacher', 'admin')
                AND (t.student_read_at IS NULL OR COALESCE(m.created_at, '') > t.student_read_at)
          )
        """,
        (username,),
    )
    count = cursor.fetchone()[0] or 0
    conn.close()
    return count


def student_has_fresh_teacher_reply(username):
    return get_student_unread_message_count(username) > 0


def get_student_message_threads(username):
    conn = get_db()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT *
        FROM communication_threads
        WHERE student_username = ?
        ORDER BY COALESCE(updated_at, created_at) DESC, id DESC
        """,
        (username,),
    )
    threads = []
    for row in cursor.fetchall():
        thread = dict(row)
        cursor.execute(
            """
            SELECT *
            FROM communication_messages
            WHERE thread_id = ?
            ORDER BY COALESCE(created_at, '') ASC, id ASC
            """,
            (thread["id"],),
        )
        thread["messages"] = [dict(message_row) for message_row in cursor.fetchall()]
        threads.append(thread)
    conn.close()
    return threads


def mark_student_threads_read(username):
    now_text = datetime.now().isoformat()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE communication_threads
        SET student_read_at = ?
        WHERE student_username = ?
        """,
        (now_text, username),
    )
    conn.commit()
    conn.close()


def create_communication_thread(
    cursor,
    student_username,
    topic,
    subject_line="",
    attendance_date="",
    initial_message="",
    chat_session_id="",
    theory_test_id=None,
):
    created_at = datetime.now().isoformat()
    cursor.execute("SELECT full_name, group_name, teacher_username FROM users WHERE username = ?", (student_username,))
    user_row = cursor.fetchone()
    group_name = user_row[1] if user_row else ""
    teacher_username = user_row[2] if user_row else ""
    cursor.execute(
        """
        INSERT INTO communication_threads (
            student_username, teacher_username, group_name, topic, subject_line,
            attendance_date, theory_test_id, status, chat_session_id, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?)
        """,
        (
            student_username,
            teacher_username,
            group_name,
            topic,
            subject_line,
            attendance_date,
            theory_test_id,
            chat_session_id,
            created_at,
            created_at,
        ),
    )
    thread_id = cursor.lastrowid
    if initial_message:
        add_communication_message(cursor, thread_id, student_username, "student", initial_message)
    return thread_id


def add_communication_message(cursor, thread_id, sender_username, sender_role, message):
    created_at = datetime.now().isoformat()
    cursor.execute(
        """
        INSERT INTO communication_messages (thread_id, sender_username, sender_role, message, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (thread_id, sender_username, sender_role, message, created_at),
    )
    cursor.execute(
        """
        UPDATE communication_threads
        SET updated_at = ?,
            teacher_read_at = CASE WHEN ? IN ('teacher', 'admin') THEN ? ELSE teacher_read_at END,
            student_read_at = CASE WHEN ? = 'student' THEN ? ELSE student_read_at END
        WHERE id = ?
        """,
        (created_at, sender_role, created_at, sender_role, created_at, thread_id),
    )
