from .helper_common import normalize_question_bank_group_text, safe_int


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


def build_match_review_rows(options, answer_text):
    from .helpers import build_match_review_rows as _impl
    return _impl(options, answer_text)


def clone_bank_question_to_test(cursor, bank_question_id, test_id, order_index):
    from .helpers import clone_bank_question_to_test as _impl
    return _impl(cursor, bank_question_id, test_id, order_index)


def create_generated_match_question(cursor, bank_question_ids, test_id, order_index):
    from .helpers import create_generated_match_question as _impl
    return _impl(cursor, bank_question_ids, test_id, order_index)


def get_question_bank_counts(cursor, modules=None, subjects=None):
    from .helpers import get_question_bank_counts as _impl
    return _impl(cursor, modules=modules, subjects=subjects)


def merge_bank_match_rows_into_test(cursor, bank_question_ids, test_id, order_index):
    from .helpers import merge_bank_match_rows_into_test as _impl
    return _impl(cursor, bank_question_ids, test_id, order_index)


def pick_unique_bank_question_ids(cursor, question_type, needed, modules=None, subjects=None, used_question_texts=None):
    from .helpers import pick_unique_bank_question_ids as _impl
    return _impl(
        cursor,
        question_type,
        needed,
        modules=modules,
        subjects=subjects,
        used_question_texts=used_question_texts,
    )


def regrade_theory_question_answers(test_id, question_id, selected_group=None, learner_username=None):
    from .helpers import regrade_theory_question_answers as _impl
    return _impl(
        test_id,
        question_id,
        selected_group=selected_group,
        learner_username=learner_username,
    )
