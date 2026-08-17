from datetime import datetime, timedelta

from .database import get_db


def get_term_dates():
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT term, start_date, end_date FROM term_dates ORDER BY term")
        rows = cursor.fetchall()
    except Exception:
        rows = []
    conn.close()
    terms = {i: {"start": None, "end": None} for i in range(1, 5)}
    for term, start, end in rows:
        terms[term] = {"start": start, "end": end}
    return terms


def get_active_term_range():
    today = datetime.now().date().isoformat()
    for term_data in get_term_dates().values():
        if term_data["start"] and term_data["end"] and term_data["start"] <= today <= term_data["end"]:
            return term_data["start"], term_data["end"]
    return None


def get_all_term_days():
    days = set()
    for term_data in get_term_dates().values():
        if term_data["start"] and term_data["end"]:
            current = datetime.strptime(term_data["start"], "%Y-%m-%d").date()
            end = min(datetime.strptime(term_data["end"], "%Y-%m-%d").date(), datetime.now().date())
            while current <= end:
                if current.weekday() < 5:
                    days.add(current.strftime("%Y-%m-%d"))
                current += timedelta(days=1)
    return days


def get_last_21_days():
    days = []
    current = datetime.now().date()
    term_days = get_all_term_days()
    limit = 0
    while len(days) < 21 and limit < 365:
        day_str = current.strftime("%Y-%m-%d")
        if current.weekday() < 5 and (not term_days or day_str in term_days):
            days.append(day_str)
        current -= timedelta(days=1)
        limit += 1
    return list(reversed(days))


def get_last_7_days():
    days = []
    current = datetime.now().date()
    term_days = get_all_term_days()
    limit = 0
    while len(days) < 7 and limit < 365:
        day_str = current.strftime("%Y-%m-%d")
        if current.weekday() < 5 and (not term_days or day_str in term_days):
            days.append(day_str)
        current -= timedelta(days=1)
        limit += 1
    return list(reversed(days))


def get_current_year_attendance_days():
    days = []
    current = datetime(datetime.now().year, 1, 1).date()
    today = datetime.now().date()
    while current <= today:
        if current.weekday() < 5:
            days.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)
    return days


def get_days_in_active_term():
    term_range = get_active_term_range()
    if not term_range:
        return []
    start_date, end_date = term_range
    days = []
    current = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()
    while current <= end:
        if current.weekday() < 5:
            days.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)
    return days


def get_low_attendance_learners(limit=10):
    days = get_last_21_days()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT date FROM excluded_dates WHERE group_name IS NULL")
    excluded = {row[0] for row in cursor.fetchall()}
    days = [day for day in days if day not in excluded]

    cursor.execute("SELECT username, full_name FROM users WHERE role = 'student'")
    learners = cursor.fetchall()
    results = []
    for username, full_name in learners:
        present = 0
        for day in days:
            cursor.execute("SELECT 1 FROM login_history WHERE username = ? AND date = ?", (username, day))
            if cursor.fetchone():
                present += 1
                continue
            cursor.execute("SELECT status FROM attendance_override WHERE username = ? AND date = ?", (username, day))
            override = cursor.fetchone()
            if override and override[0] == "present":
                present += 1
        results.append((full_name or username, len(days) - present))

    conn.close()
    results.sort(key=lambda item: item[1], reverse=True)
    return results[:limit]


def attendance_status_counts_as_present(status):
    return (status or "").strip().lower() in {"present", "late"}


def fetch_first_login_times(cursor, usernames, days):
    login_map = {}
    if not usernames or not days:
        return login_map
    user_placeholders = ",".join("?" for _ in usernames)
    day_placeholders = ",".join("?" for _ in days)
    cursor.execute(
        f"""
        SELECT username, date, MIN(login_time)
        FROM login_history
        WHERE username IN ({user_placeholders}) AND date IN ({day_placeholders})
        GROUP BY username, date
        """,
        list(usernames) + list(days),
    )
    for username, day, login_time in cursor.fetchall():
        login_map[(username, day)] = login_time
    return login_map


def fetch_attendance_override_statuses(cursor, usernames, days):
    override_map = {}
    if not usernames or not days:
        return override_map
    user_placeholders = ",".join("?" for _ in usernames)
    day_placeholders = ",".join("?" for _ in days)
    cursor.execute(
        f"""
        SELECT username, date, status
        FROM attendance_override
        WHERE username IN ({user_placeholders}) AND date IN ({day_placeholders})
        """,
        list(usernames) + list(days),
    )
    for username, day, status in cursor.fetchall():
        override_map[(username, day)] = status
    return override_map


def fetch_group_late_thresholds(cursor, group, days, teacher_username=None):
    late_cutoffs = {day: None for day in days}
    if not group or not days:
        return late_cutoffs
    day_placeholders = ",".join("?" for _ in days)
    params = [group, *days]
    teacher_clause = ""
    if teacher_username:
        teacher_clause = " AND u.teacher_username = ?"
        params.append(teacher_username)
    cursor.execute(
        f"""
        SELECT lh.date, MIN(lh.login_time)
        FROM login_history lh
        JOIN users u ON u.username = lh.username
        WHERE u.group_name = ? AND lh.date IN ({day_placeholders}){teacher_clause}
        GROUP BY lh.date
        """,
        params,
    )
    for day, min_login in cursor.fetchall():
        if not min_login:
            continue
        try:
            min_dt = datetime.fromisoformat(min_login)
        except ValueError:
            min_dt = datetime.strptime(min_login, "%Y-%m-%d %H:%M:%S")
        late_cutoffs[day] = (min_dt + timedelta(minutes=4)).strftime("%H:%M")
    return late_cutoffs


def fetch_class_checked_dates(cursor, group, teacher_username=None, exclude_username=None):
    if not group:
        return set()
    params = [group]
    teacher_clause = ""
    if teacher_username:
        teacher_clause = " AND u.teacher_username = ?"
        params.append(teacher_username)
    exclude_clause = ""
    if exclude_username:
        exclude_clause = " AND lh.username != ?"
        params.append(exclude_username)
    cursor.execute(
        f"""
        SELECT DISTINCT lh.date
        FROM login_history lh
        JOIN users u ON u.username = lh.username
        WHERE u.group_name = ? AND u.role = 'student'{teacher_clause}{exclude_clause}
        """,
        params,
    )
    return {row[0] for row in cursor.fetchall()}


def fetch_group_excluded_dates(cursor, groups):
    excluded_by_group = {group: set() for group in groups if group}
    if not excluded_by_group:
        return excluded_by_group
    placeholders = ",".join("?" for _ in excluded_by_group)
    cursor.execute(
        f"""
        SELECT date, group_name
        FROM excluded_dates
        WHERE group_name IS NULL OR group_name IN ({placeholders})
        """,
        list(excluded_by_group.keys()),
    )
    rows = cursor.fetchall()
    global_dates = {date_str for date_str, group_name in rows if group_name is None}
    for group in excluded_by_group:
        excluded_by_group[group] = set(global_dates)
    for date_str, group_name in rows:
        if group_name in excluded_by_group:
            excluded_by_group[group_name].add(date_str)
    return excluded_by_group


def fetch_present_day_map(cursor, usernames, days):
    present_map = {username: set() for username in usernames}
    if not present_map or not days:
        return present_map
    user_placeholders = ",".join("?" for _ in present_map)
    day_placeholders = ",".join("?" for _ in days)
    cursor.execute(
        f"""
        SELECT DISTINCT username, date
        FROM login_history
        WHERE username IN ({user_placeholders}) AND date IN ({day_placeholders})
        """,
        list(present_map.keys()) + list(days),
    )
    for username, day in cursor.fetchall():
        present_map.setdefault(username, set()).add(day)
    cursor.execute(
        f"""
        SELECT username, date, status
        FROM attendance_override
        WHERE username IN ({user_placeholders}) AND date IN ({day_placeholders})
        """,
        list(present_map.keys()) + list(days),
    )
    for username, day, status in cursor.fetchall():
        if attendance_status_counts_as_present(status):
            present_map.setdefault(username, set()).add(day)
        else:
            present_map.setdefault(username, set()).discard(day)
    return present_map


def build_attendance_history(cursor, username, group_name, days, login_map=None, override_map=None, late_cutoffs=None, class_checked_dates=None, excluded_dates=None):
    history = []
    login_map = login_map or {}
    override_map = override_map or {}
    late_cutoffs = late_cutoffs or {}
    class_checked_dates = class_checked_dates or set()
    excluded_dates = excluded_dates or set()

    for day in days:
        weekday = datetime.strptime(day, "%Y-%m-%d").weekday()
        login_time = login_map.get((username, day))
        override_status = (override_map.get((username, day)) or "").strip().lower()
        if day in excluded_dates:
            history.append({"date": day, "status": "Normal", "time": "", "late": False, "note": "", "weekday": weekday})
            continue

        if attendance_status_counts_as_present(override_status):
            manual_time = "12:00" if override_status == "present" else ""
            history.append({"date": day, "status": "Present", "time": manual_time, "late": override_status == "late", "note": "Manual", "weekday": weekday})
            continue

        if override_status == "absent":
            history.append({"date": day, "status": "Absent", "time": "", "late": False, "note": "Manual", "weekday": weekday})
            continue

        if login_time:
            time_str = login_time.split(" ")[1][:5]
            cutoff = late_cutoffs.get(day)
            late = cutoff is not None and time_str > cutoff
            history.append({"date": day, "status": "Present", "time": time_str, "late": late, "note": "Auto", "weekday": weekday})
            continue

        if day in class_checked_dates:
            note = "Manual" if override_status == "absent" else "Class checked in"
            history.append({"date": day, "status": "Absent", "time": "", "late": False, "note": note, "weekday": weekday})
        else:
            history.append({"date": day, "status": "Normal", "time": "", "late": False, "note": "", "weekday": weekday})

    return history


def summarize_attendance_history(history):
    counted_history = [item for item in history if item["status"] in ("Present", "Absent")]
    total_days = len(counted_history)
    present_days = sum(1 for item in history if item["status"] == "Present")
    absent_days = sum(1 for item in history if item["status"] == "Absent")
    late_days = sum(1 for item in history if item["late"])
    attendance_pct = round((present_days / total_days) * 100) if total_days else 0
    return {
        "total_days": total_days,
        "present_days": present_days,
        "absent_days": absent_days,
        "late_days": late_days,
        "attendance_pct": attendance_pct,
    }


def build_attendance_group_summary(cursor, groups, teacher_username=None, days=None):
    summaries = []
    days = days or get_last_21_days()
    for group_name in groups:
        if not group_name:
            continue
        if teacher_username:
            cursor.execute(
                """
                SELECT username, full_name
                FROM users
                WHERE group_name = ? AND role = 'student' AND teacher_username = ?
                ORDER BY full_name
                """,
                (group_name, teacher_username),
            )
        else:
            cursor.execute(
                """
                SELECT username, full_name
                FROM users
                WHERE group_name = ? AND role = 'student'
                ORDER BY full_name
                """,
                (group_name,),
            )
        learners = cursor.fetchall()
        usernames = [row[0] for row in learners]
        auto_exclude_empty_attendance_days(cursor, [group_name], created_by=teacher_username or "system", days=get_current_year_attendance_days())
        excluded_dates = fetch_group_excluded_dates(cursor, [group_name]).get(group_name, set())
        filtered_days = [day for day in days if day not in excluded_dates]
        login_map = fetch_first_login_times(cursor, usernames, filtered_days)
        override_map = fetch_attendance_override_statuses(cursor, usernames, filtered_days)
        late_cutoffs = fetch_group_late_thresholds(cursor, group_name, filtered_days, teacher_username=teacher_username)
        class_checked_dates = fetch_class_checked_dates(cursor, group_name, teacher_username=teacher_username)

        present_total = 0
        absent_total = 0
        late_total = 0
        counted_total = 0
        for uname in usernames:
            history = build_attendance_history(
                cursor,
                uname,
                group_name,
                filtered_days,
                login_map=login_map,
                override_map=override_map,
                late_cutoffs=late_cutoffs,
                class_checked_dates=class_checked_dates,
                excluded_dates=excluded_dates,
            )
            summary = summarize_attendance_history(history)
            present_total += summary["present_days"]
            absent_total += summary["absent_days"]
            late_total += summary["late_days"]
            counted_total += summary["total_days"]

        attendance_pct = round((present_total / counted_total) * 100) if counted_total else 0
        summaries.append(
            {
                "group": group_name,
                "students": len(learners),
                "attendance_pct": attendance_pct,
                "present_days": present_total,
                "absent_days": absent_total,
                "late_days": late_total,
            }
        )
    return summaries


def build_attendance_months(history):
    attendance_months = []
    for item in history:
        month_key = item["date"][:7]
        if not attendance_months or attendance_months[-1]["key"] != month_key:
            month_date = datetime.strptime(item["date"], "%Y-%m-%d")
            attendance_months.append({"key": month_key, "name": month_date.strftime("%B"), "days": []})
        attendance_months[-1]["days"].append(item)
    return attendance_months


def auto_exclude_empty_attendance_days(cursor, groups, created_by="system", days=None):
    groups = [group for group in groups if group]
    if not groups:
        return 0

    if days is None:
        days = get_current_year_attendance_days()
    today = datetime.now().date()
    filtered_days = []
    for day in days:
        try:
            day_obj = datetime.strptime(day, "%Y-%m-%d").date()
        except ValueError:
            continue
        if day_obj >= today:
            continue
        if day_obj.weekday() >= 5:
            continue
        filtered_days.append(day)

    days = filtered_days
    if not days:
        return 0

    group_placeholders = ",".join("?" for _ in groups)
    day_placeholders = ",".join("?" for _ in days)

    cursor.execute(
        f"""
        SELECT u.group_name, lh.date, COUNT(DISTINCT lh.username)
        FROM login_history lh
        JOIN users u ON u.username = lh.username
        WHERE u.group_name IN ({group_placeholders})
          AND u.role = 'student'
          AND lh.date IN ({day_placeholders})
        GROUP BY u.group_name, lh.date
        """,
        [*groups, *days],
    )
    login_counts = {(group_name, day): count for group_name, day, count in cursor.fetchall()}

    cursor.execute(
        f"""
        SELECT u.group_name, ao.date, COUNT(DISTINCT ao.username)
        FROM attendance_override ao
        JOIN users u ON u.username = ao.username
        WHERE u.group_name IN ({group_placeholders})
          AND u.role = 'student'
          AND ao.date IN ({day_placeholders})
          AND LOWER(COALESCE(ao.status, '')) IN ('present', 'late')
        GROUP BY u.group_name, ao.date
        """,
        [*groups, *days],
    )
    override_counts = {(group_name, day): count for group_name, day, count in cursor.fetchall()}

    cursor.execute(
        f"""
        SELECT date, group_name
        FROM excluded_dates
        WHERE (group_name IN ({group_placeholders}) OR group_name IS NULL)
          AND date IN ({day_placeholders})
        """,
        [*groups, *days],
    )
    existing = {(date_str, group_name) for date_str, group_name in cursor.fetchall()}

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    inserted = 0
    for group_name in groups:
        for day in days:
            if (day, group_name) in existing or (day, None) in existing:
                continue
            if login_counts.get((group_name, day), 0) > 0:
                continue
            if override_counts.get((group_name, day), 0) > 0:
                continue
            cursor.execute(
                """
                INSERT OR IGNORE INTO excluded_dates (date, group_name, reason, created_by, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (day, group_name, "Auto excluded: no class attendance recorded", created_by, timestamp),
            )
            if cursor.rowcount:
                inserted += 1
    return inserted


def get_low_attendance_learners_filtered(limit=10, groups=None, teacher_username=None):
    days = get_last_21_days()
    conn = get_db()
    cursor = conn.cursor()

    if teacher_username:
        cursor.execute(
            """
            SELECT username, full_name, group_name
            FROM users
            WHERE role = 'student' AND teacher_username = ?
            ORDER BY group_name, full_name, username
            """,
            (teacher_username,),
        )
    elif groups:
        placeholders = ",".join("?" for _ in groups)
        cursor.execute(
            f"""
            SELECT username, full_name, group_name
            FROM users
            WHERE role = 'student' AND group_name IN ({placeholders})
            ORDER BY group_name, full_name, username
            """,
            groups,
        )
    else:
        cursor.execute(
            """
            SELECT username, full_name, group_name
            FROM users
            WHERE role = 'student'
            ORDER BY group_name, full_name, username
            """
        )
    learners = cursor.fetchall()

    learner_groups = sorted({row[2] for row in learners if row[2]})
    excluded_by_group = fetch_group_excluded_dates(cursor, learner_groups)
    login_map = fetch_first_login_times(cursor, [row[0] for row in learners], days)
    override_map = fetch_attendance_override_statuses(cursor, [row[0] for row in learners], days)
    late_cutoffs_by_group = {
        group_name: fetch_group_late_thresholds(cursor, group_name, days, teacher_username=teacher_username)
        for group_name in learner_groups
    }
    class_checked_by_group = {}
    for group_name in learner_groups:
        class_checked_by_group[group_name] = fetch_class_checked_dates(
            cursor,
            group_name,
            teacher_username=teacher_username,
        )

    results = []
    for username, full_name, group_name in learners:
        excluded_dates = excluded_by_group.get(group_name, set())
        group_days = [day for day in days if day not in excluded_dates]
        history = build_attendance_history(
            cursor,
            username,
            group_name,
            group_days,
            login_map=login_map,
            override_map=override_map,
            late_cutoffs=late_cutoffs_by_group.get(group_name, {}),
            class_checked_dates=class_checked_by_group.get(group_name, set()),
            excluded_dates=excluded_dates,
        )
        absent = summarize_attendance_history(history)["absent_days"]
        results.append((full_name or username, username, absent))

    conn.close()
    results.sort(key=lambda item: item[2], reverse=True)
    return results[:limit]


def add_learner_note_entry(cursor, username, note, created_by, flag=""):
    cursor.execute(
        """
        INSERT INTO learner_notes (username, note, flag, created_by, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (username, note, flag, created_by, datetime.now().isoformat()),
    )


def get_group_late_threshold(group, date):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT MIN(login_time)
        FROM login_history
        WHERE date = ?
          AND username IN (
              SELECT username FROM users WHERE group_name = ?
          )
        """,
        (date, group),
    )
    min_login = cursor.fetchone()[0]
    conn.close()

    if not min_login:
        return None

    try:
        min_dt = datetime.fromisoformat(min_login)
    except ValueError:
        min_dt = datetime.strptime(min_login, "%Y-%m-%d %H:%M:%S")

    late_cutoff = min_dt + timedelta(minutes=4)
    return late_cutoff.strftime("%H:%M")


def is_attendance_editable(date_str, role="teacher"):
    if role == "admin":
        return True
    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
        days_diff = (datetime.now().date() - date_obj).days
        return days_diff <= 10
    except ValueError:
        return False


def get_attendance_data(group, start_date=None, end_date=None, teacher_username=None):
    conn = get_db()
    cursor = conn.cursor()
    term_days = get_all_term_days()
    explicit_range = bool(start_date and end_date)

    if not start_date or not end_date:
        term_range = get_active_term_range()
        if term_range:
            start_date, end_date = term_range
            current = datetime.strptime(start_date, "%Y-%m-%d").date()
            end = datetime.strptime(end_date, "%Y-%m-%d").date()
            days = []
            while current <= end:
                if current.weekday() < 5:
                    days.append(current.strftime("%Y-%m-%d"))
                current += timedelta(days=1)
        else:
            days = get_last_7_days()
    else:
        days = []
        current = datetime.strptime(start_date, "%Y-%m-%d").date()
        end = datetime.strptime(end_date, "%Y-%m-%d").date()
        while current <= end:
            if current.weekday() < 5:
                days.append(current.strftime("%Y-%m-%d"))
            current += timedelta(days=1)

    if term_days and not explicit_range:
        days = [day for day in days if day in term_days]

    today_str = datetime.now().date().isoformat()
    days = [day for day in days if day <= today_str]

    auto_exclude_empty_attendance_days(cursor, [group], created_by=teacher_username or "system", days=days)
    cursor.execute(
        """
        SELECT date FROM excluded_dates
        WHERE group_name IS NULL OR group_name = ?
        """,
        (group,),
    )
    excluded_dates = {row[0] for row in cursor.fetchall()}
    days = [day for day in days if day not in excluded_dates]

    year_days = [day for day in get_current_year_attendance_days() if day <= today_str and day not in excluded_dates]
    auto_exclude_empty_attendance_days(cursor, [group], created_by=teacher_username or "system", days=year_days)
    cursor.execute(
        """
        SELECT date FROM excluded_dates
        WHERE group_name IS NULL OR group_name = ?
        """,
        (group,),
    )
    excluded_dates = {row[0] for row in cursor.fetchall()}
    days = [day for day in days if day not in excluded_dates]
    year_days = [day for day in get_current_year_attendance_days() if day <= today_str and day not in excluded_dates]

    query = """
    SELECT username, full_name, group_name
    FROM users
    WHERE group_name = ? AND role = 'student'
    """
    params = [group]
    if teacher_username:
        query += " AND teacher_username = ?"
        params.append(teacher_username)

    cursor.execute(query, params)
    learners = cursor.fetchall()

    attendance = []
    late_cutoffs = fetch_group_late_thresholds(cursor, group, days, teacher_username=teacher_username)
    year_late_cutoffs = fetch_group_late_thresholds(cursor, group, year_days, teacher_username=teacher_username)
    usernames = [user for user, _, _ in learners]
    login_map = fetch_first_login_times(cursor, usernames, days)
    override_map = fetch_attendance_override_statuses(cursor, usernames, days)
    year_login_map = fetch_first_login_times(cursor, usernames, year_days)
    year_override_map = fetch_attendance_override_statuses(cursor, usernames, year_days)
    class_checked_dates = fetch_class_checked_dates(cursor, group, teacher_username=teacher_username)

    for user, name, user_group_name in learners:
        history = build_attendance_history(
            cursor,
            user,
            group,
            days,
            login_map=login_map,
            override_map=override_map,
            late_cutoffs=late_cutoffs,
            class_checked_dates=class_checked_dates,
        )
        year_history = build_attendance_history(
            cursor,
            user,
            group,
            year_days,
            login_map=year_login_map,
            override_map=year_override_map,
            late_cutoffs=year_late_cutoffs,
            class_checked_dates=class_checked_dates,
        )
        summary = summarize_attendance_history(history)
        year_summary = summarize_attendance_history(year_history)
        row = {
            "username": user,
            "name": name,
            "group": user_group_name,
            "days": {},
            "attendance_pct": summary["attendance_pct"],
            "present_days": summary["present_days"],
            "absent_days": year_summary["absent_days"],
            "year_present_days": year_summary["present_days"],
            "year_attendance_pct": year_summary["attendance_pct"],
            "year_total_days": year_summary["total_days"],
            "late_days": summary["late_days"],
        }
        for item in history:
            if item["status"] == "Present":
                row["days"][item["date"]] = {"time": item["time"], "late": item["late"], "manual": item["note"] == "Manual"}
            elif item["status"] == "Absent":
                row["days"][item["date"]] = None
            else:
                row["days"][item["date"]] = None

        attendance.append(row)

    conn.commit()
    conn.close()
    return days, attendance


def calculate_attendance_percentage(data, days):
    total_cells = len(data) * len(days)
    present = 0

    for row in data:
        for day in days:
            if row["days"].get(day):
                present += 1

    return round((present / total_cells) * 100) if total_cells else 0
