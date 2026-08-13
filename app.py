from flask import Flask, request, session, url_for
import threading
import os
from app.helpers import (
    get_student_message_threads,
    get_student_unread_message_count,
    get_teacher_unread_message_count,
)
from app.database import (
    get_db,
    init_db,
    get_user_role,
    init_marking_db,
)
from app.communication_routes import register_communication_routes
from app.admin_routes import register_admin_routes
from app.attendance_routes import register_attendance_routes
from app.dashboard_routes import register_dashboard_routes
from app.lesson_routes import register_lesson_routes
from app.marking_setup_routes import register_marking_setup_routes
from app.results_routes import register_results_routes
from app.session_routes import register_session_routes
from app.task_admin_routes import register_task_admin_routes
from app.task_runtime_routes import register_task_runtime_routes
from app.theory_admin_routes import register_theory_admin_routes
from app.theory_learner_routes import register_theory_learner_routes
from app.theory_runtime_routes import register_theory_runtime_routes
from app.review_routes import register_review_routes
from app.runtime import cleanup_thread

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'dev-key-change-in-prod')
register_session_routes(app)
register_communication_routes(app)
register_admin_routes(app)
register_attendance_routes(app)
register_dashboard_routes(app)
register_lesson_routes(app)
register_marking_setup_routes(app)
register_results_routes(app)
register_task_admin_routes(app)
register_task_runtime_routes(app)
register_theory_admin_routes(app)
register_theory_learner_routes(app)
register_theory_runtime_routes(app)
register_review_routes(app)

@app.after_request
def inject_global_mobile_css(response):
    if response.content_type and response.content_type.startswith("text/html"):
        html = response.get_data(as_text=True)
        changed = False
        viewport_meta = '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
        mobile_css = '<link rel="stylesheet" href="/static/css/mobile_global.css">'
        mobile_nav_script = '''<script>
(function () {
    function closeMenu() {
        document.body.classList.remove('mobile-nav-open');
        document.querySelectorAll('.mobile-menu-toggle').forEach(function (button) {
            button.setAttribute('aria-expanded', 'false');
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        document.querySelectorAll('.topbar').forEach(function (topbar) {
            var links = topbar.querySelector('.topbar-links');
            if (!links) {
                var title = topbar.querySelector('h1, strong');
                var movable = Array.prototype.filter.call(topbar.children, function (child) {
                    return child !== title && !child.classList.contains('mobile-menu-toggle');
                });
                if (!movable.length) return;
                links = document.createElement('div');
                links.className = 'topbar-links';
                movable.forEach(function (child) {
                    links.appendChild(child);
                });
                topbar.appendChild(links);
            }
            if (!links || topbar.querySelector('.mobile-menu-toggle')) return;

            var button = document.createElement('button');
            button.type = 'button';
            button.className = 'mobile-menu-toggle';
            button.setAttribute('aria-label', 'Open menu');
            button.setAttribute('aria-expanded', 'false');
            button.innerHTML = '&#9776;';
            button.addEventListener('click', function (event) {
                event.stopPropagation();
                var isOpen = document.body.classList.toggle('mobile-nav-open');
                button.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
            });
            topbar.insertBefore(button, topbar.firstChild);
        });

        document.addEventListener('click', function (event) {
            if (!document.body.classList.contains('mobile-nav-open')) return;
            if (event.target.closest('.topbar-links') || event.target.closest('.mobile-menu-toggle')) return;
            closeMenu();
        });

        document.addEventListener('keydown', function (event) {
            if (event.key === 'Escape') closeMenu();
        });

        document.querySelectorAll('.topbar-links a').forEach(function (link) {
            link.addEventListener('click', closeMenu);
        });
    });
})();
</script>'''
        if 'name="viewport"' not in html and "</head>" in html:
            html = html.replace("</head>", f"    {viewport_meta}\n</head>", 1)
            changed = True
        if mobile_css not in html and "</head>" in html:
            html = html.replace("</head>", f"    {mobile_css}\n</head>", 1)
            changed = True
        if "mobile-menu-toggle" not in html and "</body>" in html:
            html = html.replace("</body>", f"    {mobile_nav_script}\n</body>", 1)
            changed = True
        if changed:
            response.set_data(html)
            response.headers["Content-Length"] = str(len(response.get_data()))
    return response

@app.context_processor
def inject_session_user():
    from flask import session as _s
    uname = _s.get('username', '')
    role = ''
    teacher_unread_messages = 0
    student_unread_messages = 0
    if uname:
        try:
            role = get_user_role(uname)
            if role in ["teacher", "admin"]:
                teacher_unread_messages = get_teacher_unread_message_count(uname)
            elif role == "student":
                student_unread_messages = get_student_unread_message_count(uname)
        except Exception:
            pass

    def infer_current_page():
        endpoint = request.endpoint or ""
        teacher_map = {
            "teacher_dashboard": "teacher_dashboard",
            "attendance": "attendance",
            "group_results": "group_results",
            "risk_learners": "risk_learners",
            "weakness_summary": "weakness_summary",
            "manage_subjects": "manage_subjects",
            "manage_tasks": "manage_subjects",
            "edit_task": "manage_subjects",
            "task_preview": "manage_subjects",
            "manage_tests": "manage_tests",
            "manage_test_questions": "manage_tests",
            "edit_test": "manage_tests",
            "generate_theory_test": "manage_tests",
            "question_bank": "manage_tests",
            "manage_lessons": "manage_lessons",
            "manage_lesson_questions": "manage_lessons",
            "edit_lesson": "manage_lessons",
            "response_review": "response_review",
            "response_review_learner": "response_review",
            "communications": "communications",
            "marking_setup": "marking_setup",
            "edit_marking_setup": "marking_setup",
            "admin_panel": "admin",
            "recent_activity": "admin",
            "edit_user": "admin",
            "learner_record": "admin",
            "view_as_student": "teacher_dashboard",
        }
        student_map = {
            "student_dashboard": "student_dashboard",
            "learner_tasks": "my_tasks",
            "my_results": "my_results",
            "student_messages": "student_messages",
            "my_weaknesses": "my_weaknesses",
            "learner_lessons": "lessons",
            "lesson_tests": "lessons",
            "lesson_view": "lessons",
            "learner_tests": "tests",
            "preview_test": "tests",
            "take_test": "tests",
            "test_results": "tests",
        }
        page_map = teacher_map if role in ["teacher", "admin"] else student_map
        return page_map.get(endpoint, "")

    def resolve_task_subject_id(task_id):
        if not task_id:
            return None
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT subject_id FROM tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            conn.close()
            return row[0] if row else None
        except Exception:
            return None

    def build_logical_back():
        fallback_url = url_for("teacher_dashboard") if role in ["teacher", "admin"] else url_for("student_dashboard")
        fallback_label = "Back to Dashboard"
        endpoint = request.endpoint or ""

        if endpoint in {"teacher_dashboard", "student_dashboard", "dashboard"}:
            return {"url": fallback_url, "label": fallback_label, "hidden": True}

        if endpoint == "manage_tasks":
            return {"url": url_for("manage_subjects"), "label": "Back to Practical", "hidden": False}
        if endpoint in {"manage_tests", "question_bank", "generate_theory_test"}:
            return {"url": url_for("manage_tests"), "label": "Back to Theory Tests", "hidden": endpoint == "manage_tests"}
        if endpoint in {"manage_test_questions", "edit_test"}:
            return {"url": url_for("manage_tests"), "label": "Back to Theory Tests", "hidden": False}
        if endpoint in {"manage_lessons", "manage_lesson_questions", "edit_lesson"}:
            return {"url": url_for("manage_lessons"), "label": "Back to Lesson Setup", "hidden": endpoint == "manage_lessons"}
        if endpoint in {"marking_setup", "edit_marking_setup"}:
            return {"url": url_for("marking_setup"), "label": "Back to Marking Setup", "hidden": endpoint == "marking_setup"}
        if endpoint in {"response_review", "response_review_learner"}:
            return {"url": url_for("response_review", **request.args.to_dict(flat=True)), "label": "Back to Review", "hidden": endpoint == "response_review"}
        if endpoint in {"communications"}:
            return {"url": url_for("communications"), "label": "Back to Messages", "hidden": endpoint == "communications"}
        if endpoint in {"attendance", "term_dates", "export_attendance"}:
            if endpoint == "attendance":
                return {"url": url_for("attendance", **request.args.to_dict(flat=True)), "label": "Back to Attendance", "hidden": True}
            return {"url": url_for("attendance", **request.args.to_dict(flat=True)), "label": "Back to Attendance", "hidden": False}
        if endpoint in {"group_results", "export_results"}:
            if endpoint == "group_results":
                return {"url": url_for("group_results", **request.args.to_dict(flat=True)), "label": "Back to Results", "hidden": True}
            return {"url": url_for("group_results", **request.args.to_dict(flat=True)), "label": "Back to Results", "hidden": False}
        if endpoint == "risk_learners":
            return {"url": url_for("risk_learners", **request.args.to_dict(flat=True)), "label": "Back to Learners At Risk", "hidden": True}
        if endpoint == "weakness_summary":
            return {"url": url_for("weakness_summary", **request.args.to_dict(flat=True)), "label": "Back to Weaknesses", "hidden": True}
        if endpoint in {"admin_panel", "recent_activity"}:
            return {"url": url_for("admin_panel", **request.args.to_dict(flat=True)), "label": "Back to Admin", "hidden": endpoint == "admin_panel"}
        if endpoint == "view_as_student":
            return {"url": url_for("teacher_dashboard", **request.args.to_dict(flat=True)), "label": "Back to Dashboard", "hidden": False}

        if endpoint in {"edit_user", "learner_record"}:
            next_url = request.args.get("next") or request.form.get("next")
            if next_url:
                return {"url": next_url, "label": "Back", "hidden": False}
            if role == "student":
                return {"url": url_for("student_dashboard"), "label": "Back to Dashboard", "hidden": False}
            return {"url": url_for("admin_panel"), "label": "Back to Admin", "hidden": False}

        if endpoint in {"edit_task", "task_preview"}:
            task_id = (request.view_args or {}).get("task_id")
            subject_id = resolve_task_subject_id(task_id)
            if subject_id is not None:
                return {"url": url_for("manage_tasks", subject_id=subject_id), "label": "Back to Tasks", "hidden": False}
            return {"url": url_for("manage_subjects"), "label": "Back to Practical", "hidden": False}

        if endpoint in {"learner_tasks", "upload", "upload_result"}:
            return {"url": url_for("learner_tasks"), "label": "Back to Practical Tasks", "hidden": endpoint == "learner_tasks"}
        if endpoint in {"learner_tests", "preview_test", "take_test", "test_results"}:
            return {"url": url_for("learner_tests"), "label": "Back to Theory Tests", "hidden": endpoint == "learner_tests"}
        if endpoint in {"learner_lessons", "lesson_tests", "lesson_view"}:
            return {"url": url_for("learner_lessons"), "label": "Back to Lessons", "hidden": endpoint == "learner_lessons"}
        if endpoint in {"my_results", "my_weaknesses", "student_messages"}:
            return {"url": url_for("student_dashboard"), "label": "Back to Dashboard", "hidden": False}

        return {"url": fallback_url, "label": fallback_label, "hidden": False}

    current_page = infer_current_page()
    logical_back = build_logical_back()
    if not uname:
        header_nav_items = []
    elif role in ["teacher", "admin"]:
        header_nav_items = [
            {"key": "teacher_dashboard", "href": url_for("teacher_dashboard"), "label": "Dashboard"},
            {"key": "attendance", "href": url_for("attendance"), "label": "Attendance"},
            {"key": "group_results", "href": url_for("group_results"), "label": "Results"},
            {"key": "risk_learners", "href": url_for("risk_learners"), "label": "Learners At Risk"},
            {"key": "weakness_summary", "href": url_for("weakness_summary"), "label": "Weaknesses"},
            {"key": "manage_subjects", "href": url_for("manage_subjects"), "label": "Practical"},
            {"key": "manage_tests", "href": url_for("manage_tests"), "label": "Theory Tests"},
            {"key": "manage_lessons", "href": url_for("manage_lessons"), "label": "Lesson Setup"},
            {"key": "response_review", "href": url_for("response_review"), "label": "Review"},
            {"key": "communications", "href": url_for("communications"), "label": f"Messages{' *' if teacher_unread_messages else ''}"},
            {"key": "marking_setup", "href": url_for("marking_setup"), "label": "Marking Setup"},
            {"key": "admin", "href": url_for("admin_panel"), "label": "Admin"},
        ]
    else:
        header_nav_items = [
            {"key": "student_dashboard", "href": url_for("student_dashboard"), "label": "Dashboard"},
            {"key": "my_tasks", "href": url_for("learner_tasks"), "label": "Practical Tasks"},
            {"key": "my_results", "href": url_for("my_results"), "label": "Results"},
            {"key": "student_messages", "href": url_for("student_messages"), "label": f"Messages{' *' if student_unread_messages else ''}"},
            {"key": "my_weaknesses", "href": url_for("my_weaknesses"), "label": "Weaknesses"},
            {"key": "lessons", "href": url_for("learner_lessons"), "label": "Lessons"},
            {"key": "tests", "href": url_for("learner_tests"), "label": "Theory Tests"},
        ]
    return dict(
        session_username=uname,
        session_role=role,
        teacher_unread_messages=teacher_unread_messages,
        student_unread_messages=student_unread_messages,
        default_current_page=current_page,
        logical_back_url=logical_back["url"],
        logical_back_label=logical_back["label"],
        logical_back_hidden=logical_back["hidden"],
        header_nav_items=header_nav_items,
    )

if __name__ == "__main__":
    init_db()
    init_marking_db()
    cleanup = threading.Thread(target=cleanup_thread, daemon=True)
    cleanup.start()
    
    app.run(host=os.getenv("COMPUTERNAME", "127.0.0.1"), port=5000, debug=True)

