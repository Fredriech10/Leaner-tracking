from .helper_common import normalize_question_bank_group_text, parse_module_names, safe_int
from .database import get_db


def normalize_review_text(value):
    return " ".join((value or "").strip().lower().split())


def parse_true_false_answer_text(answer_text):
    raw = (answer_text or "").strip()
    if "(correction:" in raw:
        selected, correction = raw.split("(correction:", 1)
        return selected.strip(), correction.rstrip(") ").strip()
    return raw, ""


def get_true_false_option_data(options):
    correct_choice = ""
    accepted_corrections = []
    for option in options:
        option_text = option[1] if len(option) > 1 else ""
        is_correct = option[2] if len(option) > 2 else 0
        match_pair = option[3] if len(option) > 3 else None
        if is_correct == 1 and match_pair != "correction":
            correct_choice = option_text
        if match_pair == "correction" and option_text:
            accepted_corrections.append(option_text)
    return correct_choice, accepted_corrections


def score_true_false_answer(selected, correction_submitted, options, effective_marks):
    correct_choice, accepted_corrections = get_true_false_option_data(options)
    if selected != correct_choice:
        return 0
    if selected == "False" and accepted_corrections:
        submitted_key = normalize_review_text(correction_submitted)
        accepted_keys = {normalize_review_text(item) for item in accepted_corrections if item}
        return effective_marks if submitted_key and submitted_key in accepted_keys else 0
    return effective_marks


def get_fill_in_accepted_answers(options):
    return [option[1] for option in options if len(option) > 2 and option[2] == 1 and option[1]]


def score_fill_in_answer(answer_text, options, marks):
    submitted_key = normalize_review_text(answer_text)
    accepted_keys = {normalize_review_text(item) for item in get_fill_in_accepted_answers(options)}
    return marks if submitted_key and submitted_key in accepted_keys else 0


def compute_theory_answer_award(question_type, marks, options, answer_text):
    if question_type == "mcq_single":
        correct_values = {option[1] for option in options if len(option) > 2 and option[2] == 1}
        return marks if answer_text in correct_values else 0
    if question_type == "mcq_multi":
        correct_values = sorted(option[1] for option in options if len(option) > 2 and option[2] == 1)
        selected_values = sorted([item.strip() for item in (answer_text or "").split(",") if item.strip()])
        return marks if selected_values == correct_values else 0
    if question_type == "true_false":
        selected, correction = parse_true_false_answer_text(answer_text)
        return score_true_false_answer(selected, correction, options, marks)
    if question_type == "fill_in":
        return score_fill_in_answer(answer_text, options, marks)
    if question_type == "match":
        learner_map = {}
        for pair in (answer_text or "").split(";"):
            if "=" not in pair:
                continue
            left, chosen = pair.split("=", 1)
            learner_map[left.strip()] = chosen.strip()
        indexed_awarded = 0
        indexed_present = False
        for idx, option in enumerate(options, start=1):
            if len(option) <= 3 or not option[3] or option[3] == "correction":
                continue
            if str(idx) in learner_map:
                indexed_present = True
                if learner_map.get(str(idx), "") == option[1]:
                    indexed_awarded += 1
        if indexed_present:
            return indexed_awarded
        legacy_map = {option[1]: option[3] for option in options if len(option) > 3 and option[3] and option[3] != "correction"}
        swapped_map = {option[3]: option[1] for option in options if len(option) > 3 and option[3] and option[3] != "correction"}
        legacy_awarded = sum(1 for left, accepted in legacy_map.items() if learner_map.get(left, "") == accepted)
        swapped_awarded = sum(1 for left, accepted in swapped_map.items() if learner_map.get(left, "") == accepted)
        return max(legacy_awarded, swapped_awarded)
    return 0


def build_bank_option_signature(question_type, options):
    normalized = []
    for option_text, is_correct, match_pair in options:
        normalized.append((
            (option_text or "").strip().lower(),
            safe_int(is_correct, 0),
            (match_pair or "").strip().lower(),
        ))
    if question_type == "match":
        normalized.sort()
    return tuple(normalized)


def bank_question_exists(cursor, question_text, question_type, subject, modules, options):
    normalized_text = normalize_question_bank_group_text(question_text)
    normalized_subject = (subject or "").strip().lower()
    normalized_modules = (modules or "").strip().lower()
    target_signature = build_bank_option_signature(question_type, options)

    cursor.execute(
        """
        SELECT id, question_text
        FROM question_bank_questions
        WHERE question_type = ?
          AND LOWER(TRIM(COALESCE(subject, ''))) = ?
          AND LOWER(TRIM(COALESCE(modules, ''))) = ?
        """,
        (question_type, normalized_subject, normalized_modules),
    )
    candidate_rows = cursor.fetchall()
    for candidate_id, candidate_text in candidate_rows:
        if normalize_question_bank_group_text(candidate_text) != normalized_text:
            continue
        cursor.execute(
            """
            SELECT option_text, is_correct, match_pair
            FROM question_bank_options
            WHERE bank_question_id = ?
            ORDER BY id
            """,
            (candidate_id,),
        )
        candidate_signature = build_bank_option_signature(question_type, cursor.fetchall())
        if candidate_signature == target_signature:
            return True
    return False


QUESTION_BANK_SUPPORTED_TYPES = ["mcq_single", "fill_in", "true_false", "match"]


def get_question_bank_counts(cursor, modules=None, subjects=None):
    modules = parse_module_names(",".join(modules or []))
    subjects = [item.strip() for item in (subjects or []) if item and item.strip()]
    counts = {}
    for q_type in QUESTION_BANK_SUPPORTED_TYPES:
        where_parts = ["question_type = ?"]
        params = [q_type]
        if modules:
            module_filters = " OR ".join(["LOWER(COALESCE(modules, '')) LIKE ?" for _ in modules])
            where_parts.append(f"({module_filters})")
            params.extend(f"%{module.lower()}%" for module in modules)
        if subjects:
            subject_filters = " OR ".join(["LOWER(COALESCE(subject, '')) = ?" for _ in subjects])
            where_parts.append(f"({subject_filters})")
            params.extend(subject.lower() for subject in subjects)
        cursor.execute(
            f"""
            SELECT COUNT(*)
            FROM question_bank_questions
            WHERE {' AND '.join(where_parts)}
            """,
            params,
        )
        counts[q_type] = cursor.fetchone()[0] or 0
    return counts


def build_match_review_rows(options, answer_text):
    learner_map = {}
    for pair in (answer_text or "").split(";"):
        if "=" in pair:
            left, chosen = pair.split("=", 1)
            learner_map[left.strip()] = chosen.strip()
    indexed_rows = []
    for idx, option in enumerate(options, start=1):
        if len(option) <= 3 or not option[3] or option[3] == "correction":
            continue
        if str(idx) in learner_map:
            indexed_rows.append(
                {
                    "left": option[3],
                    "learner_match": learner_map.get(str(idx), "") or "No answer",
                    "correct_match": option[1],
                    "is_correct": learner_map.get(str(idx), "") == option[1],
                }
            )
    if indexed_rows:
        return indexed_rows, {row["left"]: row["correct_match"] for row in indexed_rows}
    legacy_map = {option[1]: option[3] for option in options if len(option) > 3 and option[3] and option[3] != "correction"}
    swapped_map = {option[3]: option[1] for option in options if len(option) > 3 and option[3] and option[3] != "correction"}
    legacy_score = sum(1 for left, accepted in legacy_map.items() if learner_map.get(left, "") == accepted)
    swapped_score = sum(1 for left, accepted in swapped_map.items() if learner_map.get(left, "") == accepted)
    active_map = swapped_map if swapped_score > legacy_score else legacy_map
    rows = []
    for left, accepted in active_map.items():
        chosen = learner_map.get(left, "")
        rows.append(
            {
                "left": left,
                "learner_match": chosen or "No answer",
                "correct_match": accepted,
                "is_correct": chosen == accepted,
            }
        )
    return rows, active_map


def pick_unique_bank_question_ids(cursor, question_type, needed, modules=None, subjects=None, used_question_texts=None):
    modules = parse_module_names(",".join(modules or []))
    subjects = [item.strip() for item in (subjects or []) if item and item.strip()]
    used_question_texts = {item.strip().lower() for item in (used_question_texts or set()) if item}
    where_parts = ["question_type = ?"]
    params = [question_type]
    if modules:
        module_filters = " OR ".join(["LOWER(COALESCE(modules, '')) LIKE ?" for _ in modules])
        where_parts.append(f"({module_filters})")
        params.extend(f"%{module.lower()}%" for module in modules)
    if subjects:
        subject_filters = " OR ".join(["LOWER(COALESCE(subject, '')) = ?" for _ in subjects])
        where_parts.append(f"({subject_filters})")
        params.extend(subject.lower() for subject in subjects)
    cursor.execute(
        f"""
        SELECT id, question_text
        FROM question_bank_questions
        WHERE {' AND '.join(where_parts)}
        ORDER BY RANDOM()
        """,
        params,
    )
    picked_ids = []
    seen_texts = set(used_question_texts)
    seen_match_pairs = set()
    for bank_question_id, question_text in cursor.fetchall():
        normalized_text = (question_text or "").strip().lower()
        if question_type != "match" and normalized_text in seen_texts:
            continue
        if question_type == "match":
            cursor.execute(
                """
                SELECT option_text, match_pair
                FROM question_bank_options
                WHERE bank_question_id = ?
                ORDER BY id
                LIMIT 1
                """,
                (bank_question_id,),
            )
            option_row = cursor.fetchone()
            if not option_row:
                continue
            pair_signature = ((option_row[0] or "").strip().lower(), (option_row[1] or "").strip().lower())
            if pair_signature in seen_match_pairs:
                continue
            seen_match_pairs.add(pair_signature)
        else:
            seen_texts.add(normalized_text)
        picked_ids.append(bank_question_id)
        if len(picked_ids) >= needed:
            break
    return picked_ids, seen_texts


def clone_bank_question_to_test(cursor, bank_question_id, test_id, order_index):
    cursor.execute(
        """
        SELECT question_text, question_type, marks, subject, modules
        FROM question_bank_questions
        WHERE id = ?
        """,
        (bank_question_id,),
    )
    row = cursor.fetchone()
    if not row:
        return None
    question_text, question_type, marks, subject, modules = row
    cursor.execute(
        """
        INSERT INTO theory_questions (test_id, question_text, question_type, marks, order_index, bank_question_id, source_subject, source_modules)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (test_id, question_text, question_type, marks, order_index, bank_question_id, subject, modules),
    )
    new_question_id = cursor.lastrowid
    cursor.execute(
        """
        SELECT option_text, is_correct, match_pair
        FROM question_bank_options
        WHERE bank_question_id = ?
        ORDER BY id
        """,
        (bank_question_id,),
    )
    for option_text, is_correct, match_pair in cursor.fetchall():
        cursor.execute(
            """
            INSERT INTO theory_options (question_id, option_text, is_correct, match_pair)
            VALUES (?, ?, ?, ?)
            """,
            (new_question_id, option_text, is_correct, match_pair),
        )
    return new_question_id


def create_generated_match_question(cursor, bank_question_ids, test_id, order_index):
    merged_count, _ = merge_bank_match_rows_into_test(cursor, bank_question_ids, test_id, order_index)
    return merged_count


def merge_bank_match_rows_into_test(cursor, bank_question_ids, test_id, order_index):
    if not bank_question_ids:
        return 0, order_index

    placeholders = ",".join("?" for _ in bank_question_ids)
    cursor.execute(
        f"""
        SELECT qbq.id, qbq.question_text, qbo.option_text, qbo.is_correct, qbo.match_pair
        FROM question_bank_questions qbq
        JOIN question_bank_options qbo ON qbo.bank_question_id = qbq.id
        WHERE qbq.id IN ({placeholders})
          AND qbq.question_type = 'match'
          AND COALESCE(qbo.match_pair, '') != ''
        ORDER BY qbq.id, qbo.id
        """,
        bank_question_ids,
    )
    rows = cursor.fetchall()
    if not rows:
        return 0, order_index

    all_pairs = []
    seen_pairs = set()
    question_labels = []
    source_subjects = set()
    source_modules_set = set()
    for bank_question_id, question_text, option_text, is_correct, match_pair in rows:
        if question_text:
            question_labels.append(question_text)
        cursor.execute("SELECT subject, modules FROM question_bank_questions WHERE id = ?", (bank_question_id,))
        source_row = cursor.fetchone()
        if source_row:
            if source_row[0]:
                source_subjects.add(source_row[0])
            source_modules_set.update(parse_module_names(source_row[1] or ""))
        pair_signature = ((option_text or "").strip().lower(), (match_pair or "").strip().lower())
        if not pair_signature[0] or not pair_signature[1] or pair_signature in seen_pairs:
            continue
        seen_pairs.add(pair_signature)
        all_pairs.append((option_text, is_correct, match_pair))

    if not all_pairs:
        return 0, order_index

    cursor.execute(
        """
        SELECT id, COALESCE(source_modules, '')
        FROM theory_questions
        WHERE test_id = ?
          AND question_type = 'match'
        ORDER BY order_index, id
        LIMIT 1
        """,
        (test_id,),
    )
    existing_question = cursor.fetchone()

    if existing_question:
        question_id = existing_question[0]
        source_modules_set.update(parse_module_names(existing_question[1] or ""))
    else:
        source_subject = next(iter(source_subjects), "")
        source_modules = ", ".join(sorted(source_modules_set, key=str.lower))
        question_text = question_labels[0] if question_labels else "Match Column A to B"
        cursor.execute(
            """
            INSERT INTO theory_questions (test_id, question_text, question_type, marks, order_index, source_subject, source_modules)
            VALUES (?, ?, 'match', 0, ?, ?, ?)
            """,
            (test_id, question_text, order_index, source_subject, source_modules),
        )
        question_id = cursor.lastrowid
        order_index += 1

    cursor.execute(
        """
        SELECT option_text, match_pair
        FROM theory_options
        WHERE question_id = ?
          AND COALESCE(match_pair, '') != ''
        """,
        (question_id,),
    )
    existing_pairs = {
        ((option_text or "").strip().lower(), (match_pair or "").strip().lower())
        for option_text, match_pair in cursor.fetchall()
    }

    inserted = 0
    for option_text, is_correct, match_pair in all_pairs:
        pair_signature = ((option_text or "").strip().lower(), (match_pair or "").strip().lower())
        if pair_signature in existing_pairs:
            continue
        cursor.execute(
            """
            INSERT INTO theory_options (question_id, option_text, is_correct, match_pair)
            VALUES (?, ?, ?, ?)
            """,
            (question_id, option_text, is_correct, match_pair),
        )
        existing_pairs.add(pair_signature)
        inserted += 1

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM theory_options
        WHERE question_id = ?
          AND COALESCE(match_pair, '') != ''
        """,
        (question_id,),
    )
    total_pairs = cursor.fetchone()[0] or 0
    cursor.execute(
        """
        UPDATE theory_questions
        SET marks = ?, source_modules = ?
        WHERE id = ?
        """,
        (total_pairs, ", ".join(sorted(source_modules_set, key=str.lower)), question_id),
    )

    return inserted, order_index


def regrade_theory_question_answers(test_id, question_id, selected_group=None, learner_username=None):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT question_type, marks
        FROM theory_questions
        WHERE id = ? AND test_id = ?
        """,
        (question_id, test_id),
    )
    question_row = cursor.fetchone()
    if not question_row:
        conn.close()
        return 0

    q_type, marks = question_row
    cursor.execute(
        """
        SELECT id, option_text, is_correct, match_pair
        FROM theory_options
        WHERE question_id = ?
        ORDER BY id
        """,
        (question_id,),
    )
    options = cursor.fetchall()

    query = """
        SELECT a.id, a.answer_text, a.submission_id
        FROM theory_answers a
        JOIN theory_submissions s ON s.id = a.submission_id
        JOIN users u ON u.username = s.username
        WHERE s.test_id = ? AND a.question_id = ?
    """
    params = [test_id, question_id]
    if selected_group:
        query += " AND u.group_name = ?"
        params.append(selected_group)
    if learner_username:
        query += " AND s.username = ?"
        params.append(learner_username)
    cursor.execute(query, params)
    answer_rows = cursor.fetchall()

    updated = 0
    submission_ids = set()
    for answer_id, answer_text, submission_id in answer_rows:
        awarded = compute_theory_answer_award(q_type, marks, options, answer_text)
        is_correct = 1 if awarded == marks else 0
        if q_type == "match":
            expected_total = len([option for option in options if len(option) > 3 and option[3] and option[3] != "correction"])
            is_correct = 1 if awarded == expected_total else 0
        cursor.execute(
            """
            UPDATE theory_answers
            SET marks_awarded = ?, is_correct = ?
            WHERE id = ?
            """,
            (awarded, is_correct, answer_id),
        )
        updated += cursor.rowcount
        submission_ids.add(submission_id)

    for submission_id in submission_ids:
        cursor.execute(
            """
            SELECT COALESCE(SUM(marks_awarded), 0)
            FROM theory_answers
            WHERE submission_id = ?
            """,
            (submission_id,),
        )
        score = cursor.fetchone()[0] or 0
        cursor.execute("SELECT total FROM theory_submissions WHERE id = ?", (submission_id,))
        total_row = cursor.fetchone()
        total = total_row[0] if total_row and total_row[0] else 0
        percentage = round((score / total) * 100) if total else 0
        cursor.execute(
            """
            UPDATE theory_submissions
            SET score = ?, percentage = ?
            WHERE id = ?
            """,
            (score, percentage, submission_id),
        )

    conn.commit()
    conn.close()
    return updated
