from datetime import datetime

from flask import flash, redirect, render_template, request, session, url_for

from app.database import (
    create_user_if_not_exists,
    get_db,
    get_groups,
    get_user_role,
    get_teachers,
    infer_grade_from_group,
    log_activity,
    log_login,
    verify_user_password,
    update_last_active,
)
from app.runtime import active_users, lock


def should_record_attendance_login(login_source="remote"):
    return login_source == "auto_login"


def get_user_profile_row(username):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT username, full_name, group_name, teacher_username, role FROM users WHERE username = ?",
        (username,),
    )
    row = cursor.fetchone()
    conn.close()
    return row


def student_needs_registration(username):
    user = get_user_profile_row(username)
    if not user:
        return False
    role = user[4] or "student"
    full_name = (user[1] or "").strip()
    return role == "student" and not full_name


def post_login_redirect(username):
    role = get_user_role(username)
    if role in ["teacher", "admin"]:
        return redirect(url_for("teacher_dashboard"))
    if student_needs_registration(username):
        return redirect(url_for("complete_registration"))
    return redirect(url_for("student_dashboard"))


def register_session_routes(app):
    @app.route("/", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            username = request.form.get("username", "").strip().upper()
            password = request.form.get("password", "")

            if username and len(username) <= 20 and username.isalnum():
                create_user_if_not_exists(username)
                if not verify_user_password(username, password):
                    flash("Invalid username or password.", "error")
                    return render_template("login.html"), 401

                session["username"] = username
                session["login_source"] = "remote"
                update_last_active(username)
                if get_user_role(username) == "student" and should_record_attendance_login("remote"):
                    log_login(username)
                log_activity(username, "logged in via portal")

                with lock:
                    active_users[username] = datetime.now()

                return post_login_redirect(username)
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
            session["login_source"] = "auto_login"

            create_user_if_not_exists(username)
            update_last_active(username)
            if get_user_role(username) == "student" and should_record_attendance_login("auto_login"):
                log_login(username)
            log_activity(username, "logged in via auto-login")

            with lock:
                active_users[username] = datetime.now()

            return post_login_redirect(username)

        return "Invalid auto-login", 400

    @app.route("/complete_registration", methods=["GET", "POST"])
    def complete_registration():
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))

        user = get_user_profile_row(username)
        if not user:
            session.clear()
            return redirect(url_for("login"))

        role = user[4] or "student"
        if role in ["teacher", "admin"]:
            return redirect(url_for("teacher_dashboard"))
        if not student_needs_registration(username):
            return redirect(url_for("student_dashboard"))

        teacher_rows = get_teachers()
        teacher_options = [
            {"username": teacher_username, "full_name": full_name or teacher_username}
            for teacher_username, full_name in teacher_rows
            if teacher_username
        ]
        group_options = [group_name for group_name in get_groups() if group_name and group_name.strip()]

        if request.method == "POST":
            first_name = (request.form.get("first_name") or "").strip()
            surname = (request.form.get("surname") or "").strip()
            teacher_username = (request.form.get("teacher_username") or "").strip()
            group_name = (request.form.get("group_name") or "").strip()

            valid_teachers = {item["username"] for item in teacher_options}
            valid_groups = set(group_options)

            if not first_name or not surname or not teacher_username or not group_name:
                flash("All fields are required.", "error")
            elif teacher_username not in valid_teachers:
                flash("Please select a valid teacher.", "error")
            elif group_name not in valid_groups:
                flash("Please select a valid group.", "error")
            else:
                full_name = f"{surname.upper()}, {first_name.upper()}"
                conn = get_db()
                cursor = conn.cursor()
                cursor.execute(
                    """
                    UPDATE users
                    SET full_name = ?, teacher_username = ?, group_name = ?, grade = ?
                    WHERE username = ?
                    """,
                    (full_name, teacher_username, group_name, infer_grade_from_group(group_name), username),
                )
                conn.commit()
                conn.close()
                log_activity(username, "completed first-time registration")
                flash("Registration completed.", "success")
                return redirect(url_for("student_dashboard"))

        return render_template(
            "complete_registration.html",
            username=username,
            teacher_options=teacher_options,
            group_options=group_options,
        )

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
