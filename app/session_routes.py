from datetime import datetime

from flask import redirect, render_template, request, session, url_for

from app.database import (
    create_user_if_not_exists,
    get_user_role,
    log_activity,
    log_login,
    update_last_active,
)
from app.runtime import active_users, lock


def should_record_attendance_login():
    return True


def register_session_routes(app):
    @app.route("/", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            username = request.form.get("username", "").strip().upper()

            if username and len(username) <= 20 and username.isalnum():
                session["username"] = username

                create_user_if_not_exists(username)
                update_last_active(username)
                if get_user_role(username) == "student" and should_record_attendance_login():
                    log_login(username)
                log_activity(username, "logged in")

                with lock:
                    active_users[username] = datetime.now()

                role = get_user_role(username)
                if role in ["teacher", "admin"]:
                    return redirect(url_for("teacher_dashboard"))
                return redirect(url_for("student_dashboard"))
            return "Invalid username", 400

        return render_template("login.html")

    @app.route("/heartbeat/<username>")
    def heartbeat(username):
        with lock:
            if username in active_users:
                active_users[username] = datetime.now()
                update_last_active(username)
            else:
                return "Invalid", 401
        return "OK"

    @app.route("/auto_login")
    def auto_login():
        username = request.args.get("username", "").strip().upper()

        if username and len(username) <= 20 and username.isalnum():
            session["username"] = username

            create_user_if_not_exists(username)
            update_last_active(username)
            if get_user_role(username) == "student" and should_record_attendance_login():
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

        with lock:
            active_users.pop(username, None)

        session.clear()
        return redirect(url_for("login"))

    @app.route("/manage_tests_simple")
    def legacy_manage_tests_simple():
        return redirect(url_for("manage_tests"))

    @app.route("/manage_test_questions_simple/<int:test_id>")
    def legacy_manage_test_questions_simple(test_id):
        return redirect(url_for("manage_test_questions", test_id=test_id))

    @app.route("/take_test_simple/<int:test_id>", methods=["GET", "POST"])
    def legacy_take_test_simple(test_id):
        return redirect(url_for("take_test", test_id=test_id), code=307 if request.method == "POST" else 302)
