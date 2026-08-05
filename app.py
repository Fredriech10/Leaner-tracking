from flask import Flask, session
import threading
import os
from app.helpers import (
    get_student_message_threads,
    get_student_unread_message_count,
    get_teacher_unread_message_count,
)
from app.database import (
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
    return dict(
        session_username=uname,
        session_role=role,
        teacher_unread_messages=teacher_unread_messages,
        student_unread_messages=student_unread_messages,
    )

if __name__ == "__main__":
    init_db()
    init_marking_db()
    cleanup = threading.Thread(target=cleanup_thread, daemon=True)
    cleanup.start()
    
    app.run(host=os.getenv("COMPUTERNAME", "127.0.0.1"), port=5000, debug=True)

