import sqlite3
from collections import defaultdict

from app.helper_common import normalize_question_bank_group_text, parse_module_names
from app.helper_theory import build_bank_option_signature


DB_PATH = "school.db"
LESSON_SLIDE_TYPES = {"content_slide", "title_slide", "heading_slide"}


def unique_preserve(items):
    seen = set()
    ordered = []
    for item in items:
        cleaned = (item or "").strip()
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(cleaned)
    return ordered


def load_bank_metadata(cursor):
    cursor.execute(
        """
        SELECT id, question_text, question_type, COALESCE(subject, ''), COALESCE(modules, '')
        FROM question_bank_questions
        """
    )
    bank_rows = cursor.fetchall()

    option_map = {}
    cursor.execute(
        """
        SELECT bank_question_id, option_text, is_correct, match_pair
        FROM question_bank_options
        ORDER BY bank_question_id, id
        """
    )
    for bank_question_id, option_text, is_correct, match_pair in cursor.fetchall():
        option_map.setdefault(bank_question_id, []).append((option_text, is_correct, match_pair))

    exact_map = defaultdict(list)
    match_pair_map = defaultdict(list)
    for bank_question_id, question_text, question_type, subject, modules in bank_rows:
        options = option_map.get(bank_question_id, [])
        normalized_text = normalize_question_bank_group_text(question_text)
        signature = build_bank_option_signature(question_type, options)
        exact_key = (question_type, normalized_text, signature)
        exact_map[exact_key].append(
            {
                "id": bank_question_id,
                "subject": subject,
                "modules": parse_module_names(modules),
            }
        )

        if question_type == "match":
            for option_text, _is_correct, match_pair in options:
                pair_key = (
                    normalize_question_bank_group_text(option_text),
                    normalize_question_bank_group_text(match_pair),
                )
                if pair_key[0] and pair_key[1]:
                    match_pair_map[pair_key].append(
                        {
                            "id": bank_question_id,
                            "subject": subject,
                            "modules": parse_module_names(modules),
                        }
                    )

    return exact_map, match_pair_map


def main():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    exact_map, match_pair_map = load_bank_metadata(cursor)

    cursor.execute(
        """
        SELECT id, question_text, question_type, COALESCE(source_subject, '') AS source_subject,
               COALESCE(source_modules, '') AS source_modules, bank_question_id
        FROM theory_questions
        ORDER BY test_id, order_index, id
        """
    )
    theory_rows = cursor.fetchall()

    option_map = defaultdict(list)
    cursor.execute(
        """
        SELECT question_id, option_text, is_correct, match_pair
        FROM theory_options
        ORDER BY question_id, id
        """
    )
    for question_id, option_text, is_correct, match_pair in cursor.fetchall():
        option_map[question_id].append((option_text, is_correct, match_pair))

    matched_exact = 0
    matched_match = 0
    updated = 0
    unchanged = 0
    unmatched = 0

    for row in theory_rows:
        q_id = row["id"]
        q_type = row["question_type"]
        if q_type in LESSON_SLIDE_TYPES:
            unchanged += 1
            continue

        current_subject = row["source_subject"]
        current_modules = parse_module_names(row["source_modules"])
        current_bank_question_id = row["bank_question_id"]
        options = option_map.get(q_id, [])

        new_bank_question_id = current_bank_question_id
        subjects = unique_preserve([current_subject])
        modules = list(current_modules)

        if q_type == "match":
            pair_candidates = []
            for option_text, _is_correct, match_pair in options:
                pair_key = (
                    normalize_question_bank_group_text(option_text),
                    normalize_question_bank_group_text(match_pair),
                )
                if pair_key[0] and pair_key[1]:
                    pair_candidates.extend(match_pair_map.get(pair_key, []))

            candidate_ids = unique_preserve([str(item["id"]) for item in pair_candidates])
            candidate_records = {}
            for item in pair_candidates:
                candidate_records[item["id"]] = item
                if item["subject"]:
                    subjects.append(item["subject"])
                modules.extend(item["modules"])

            if len(candidate_ids) == 1:
                new_bank_question_id = int(candidate_ids[0])
            if candidate_ids:
                matched_match += 1
        else:
            exact_key = (
                q_type,
                normalize_question_bank_group_text(row["question_text"]),
                build_bank_option_signature(q_type, options),
            )
            candidates = exact_map.get(exact_key, [])
            if candidates:
                for item in candidates:
                    if item["subject"]:
                        subjects.append(item["subject"])
                    modules.extend(item["modules"])
                candidate_ids = unique_preserve([str(item["id"]) for item in candidates])
                if len(candidate_ids) == 1:
                    new_bank_question_id = int(candidate_ids[0])
                matched_exact += 1
            else:
                unmatched += 1
                continue

        if q_type == "match" and not modules and not subjects and not new_bank_question_id:
            unmatched += 1
            continue

        new_subject = ", ".join(unique_preserve(subjects))
        new_modules = ", ".join(unique_preserve(modules))

        if (
            new_subject != (current_subject or "")
            or new_modules != ", ".join(current_modules)
            or new_bank_question_id != current_bank_question_id
        ):
            cursor.execute(
                """
                UPDATE theory_questions
                SET source_subject = ?, source_modules = ?, bank_question_id = ?
                WHERE id = ?
                """,
                (new_subject, new_modules, new_bank_question_id, q_id),
            )
            updated += 1
        else:
            unchanged += 1

    conn.commit()
    print(f"Updated: {updated}")
    print(f"Unchanged: {unchanged}")
    print(f"Matched exact: {matched_exact}")
    print(f"Matched match: {matched_match}")
    print(f"Unmatched: {unmatched}")
    conn.close()


if __name__ == "__main__":
    main()
