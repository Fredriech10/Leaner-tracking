"""Utilities to import theory tests from a JSON structure into the DB.

Expected input format (example):
{
  "questions": [
    {
      "type": "true_false",
      "question": "CPU is an output device",
      "answer": false,
      "correction": "processing"
    },
    {
      "type": "multiple_choice",
      "question": "Which device is used for input?",
      "options": ["Mouse", "Printer", "Speaker", "Monitor"],
      "answer": "Mouse"
    },
    {
      "type": "matching",
      "question": "Match devices to their function",
      "pairs": [
        { "A": "CPU", "B": "Processing" },
        { "A": "Keyboard", "B": "Input" }
      ]
    },
    {
      "type": "fill_blank",
      "question": "The CPU performs ______ operations",
      "answer": "processing"
    }
  ]
}
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


VALID_TYPE_MAP = {
    # JSON -> internal
    "true_false": "true_false",
    "multiple_choice": "mcq_single",
    "multiple_choice_single": "mcq_single",
    "multiple_select": "mcq_multi",
    "fill_blank": "fill_in",
    "fill_in_blank": "fill_in",
    "matching": "match",
    "match": "match",
}


@dataclass
class ImportError:
    message: str
    context: Optional[dict] = None


def _ensure_bool(x: Any) -> bool:
    if isinstance(x, bool):
        return x
    if isinstance(x, str):
        v = x.strip().lower()
        if v in {"true", "t", "1", "yes", "y"}:
            return True
        if v in {"false", "f", "0", "no", "n"}:
            return False
    raise ValueError(f"Expected boolean, got: {x!r}")


def _clean_str(x: Any, *, field: str) -> str:
    if x is None:
        raise ValueError(f"Missing required field: {field}")
    if not isinstance(x, str):
        # allow numbers etc by stringifying
        x = str(x)
    x = x.strip()
    if not x:
        raise ValueError(f"Field {field} must be non-empty")
    return x


def _parse_json_payload(payload: str) -> Dict[str, Any]:
    try:
        obj = json.loads(payload)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e.msg} (line {e.lineno}, col {e.colno})")
    if not isinstance(obj, dict):
        raise ValueError("Top-level JSON must be an object")
    if "questions" not in obj:
        raise ValueError("Missing top-level key: 'questions'")
    if not isinstance(obj["questions"], list):
        raise ValueError("'questions' must be a list")
    return obj


def validate_and_normalize_questions(payload: str) -> List[Dict[str, Any]]:
    """Validate the incoming JSON string and normalize each question.

    Returns a list of normalized question dicts ready for DB insertion.
    """
    obj = _parse_json_payload(payload)
    questions = obj["questions"]

    normalized: List[Dict[str, Any]] = []

    for idx, q in enumerate(questions):
        if not isinstance(q, dict):
            raise ValueError(f"Question at index {idx} must be an object")

        q_type_raw = q.get("type")
        if not q_type_raw:
            raise ValueError(f"Missing 'type' for question at index {idx}")

        if not isinstance(q_type_raw, str):
            raise ValueError(f"'type' must be a string for question at index {idx}")

        q_type_raw = q_type_raw.strip()
        if q_type_raw not in VALID_TYPE_MAP:
            raise ValueError(
                f"Unsupported question type '{q_type_raw}' at index {idx}. "
                f"Supported: {sorted(set(VALID_TYPE_MAP.keys()))}"
            )

        internal_type = VALID_TYPE_MAP[q_type_raw]

        q_text = _clean_str(q.get("question"), field="question")
        marks = q.get("marks", 1)
        try:
            marks = int(marks)
        except Exception:
            raise ValueError(f"Invalid 'marks' for question at index {idx}; must be integer")
        if marks < 1:
            raise ValueError(f"'marks' must be >= 1 for question at index {idx}")

        base = {
            "question_text": q_text,
            "question_type": internal_type,
            "marks": marks,
        }

        if internal_type == "true_false":
            ans = q.get("answer")
            tf = _ensure_bool(ans)
            correction = q.get("correction")
            correction_term = None
            if correction is not None and str(correction).strip():
                correction_term = _clean_str(correction, field="correction")
            base["tf_correct"] = "True" if tf else "False"
            base["correction_term"] = correction_term

        elif internal_type in {"mcq_single", "mcq_multi"}:
            options = q.get("options")
            if not isinstance(options, list) or not options:
                raise ValueError(f"Question at index {idx} requires non-empty 'options' list")
            options_clean = [_clean_str(opt, field="options[]") for opt in options]

            answer = q.get("answer")
            if internal_type == "mcq_single":
                correct_val = _clean_str(answer, field="answer")
                if correct_val not in options_clean:
                    raise ValueError(
                        f"Answer '{correct_val}' not found in options for question at index {idx}"
                    )
                base["mcq_correct_values"] = [correct_val]
            else:
                # mcq_multi: allow answer to be either list or a single string
                if isinstance(answer, list):
                    answers_list = [_clean_str(a, field="answer[]") for a in answer]
                else:
                    answers_list = [_clean_str(answer, field="answer")]
                for av in answers_list:
                    if av not in options_clean:
                        raise ValueError(
                            f"Multi answer '{av}' not found in options for question at index {idx}"
                        )
                # de-dup
                base["mcq_correct_values"] = list(dict.fromkeys(answers_list))

            base["mcq_options"] = options_clean

        elif internal_type == "fill_in":
            ans = q.get("answer")
            fill_ans = _clean_str(ans, field="answer")
            base["fill_answer"] = fill_ans

        elif internal_type == "match":
            pairs = q.get("pairs")
            if not isinstance(pairs, list) or not pairs:
                raise ValueError(f"Question at index {idx} requires non-empty 'pairs' list")
            normalized_pairs: List[Tuple[str, str]] = []
            for pidx, p in enumerate(pairs):
                if not isinstance(p, dict):
                    raise ValueError(f"Pair at index {pidx} for question {idx} must be an object")
                a = _clean_str(p.get("A"), field="pairs[].A")
                b = _clean_str(p.get("B"), field="pairs[].B")
                normalized_pairs.append((a, b))
            base["match_pairs"] = normalized_pairs

        else:
            raise ValueError(f"Unhandled internal type: {internal_type}")

        normalized.append(base)

    return normalized


def insert_theory_test_from_json(
    cursor,
    *,
    test_id: int,
    username: str,
    payload: str,
    start_order_index: int = 0,
) -> None:
    """Insert theory questions/options into DB for a given test_id.

    start_order_index is useful for appending questions while preserving ordering.
    """
    questions = validate_and_normalize_questions(payload)

    # Insert each question and its options
    for order_idx, q in enumerate(questions):
        effective_order_index = start_order_index + order_idx
        cursor.execute(
            """
            INSERT INTO theory_questions (test_id, question_text, question_type, marks, order_index)
            VALUES (?, ?, ?, ?, ?)
            """,
            (test_id, q["question_text"], q["question_type"], q["marks"], effective_order_index),
        )
        q_id = cursor.lastrowid

        qt = q["question_type"]

        if qt == "true_false":
            cursor.execute(
                """
                INSERT INTO theory_options (question_id, option_text, is_correct)
                VALUES (?, 'True', ?)
                """,
                (q_id, 1 if q["tf_correct"] == "True" else 0),
            )
            cursor.execute(
                """
                INSERT INTO theory_options (question_id, option_text, is_correct)
                VALUES (?, 'False', ?)
                """,
                (q_id, 1 if q["tf_correct"] == "False" else 0),
            )
            if q.get("correction_term"):
                cursor.execute(
                    """
                    INSERT INTO theory_options (question_id, option_text, is_correct, match_pair)
                    VALUES (?, ?, 0, 'correction')
                    """,
                    (q_id, q["correction_term"]),
                )

        elif qt in {"mcq_single", "mcq_multi"}:
            options = q["mcq_options"]
            correct_vals = set(q["mcq_correct_values"])
            for opt in options:
                cursor.execute(
                    """
                    INSERT INTO theory_options (question_id, option_text, is_correct)
                    VALUES (?, ?, ?)
                    """,
                    (q_id, opt, 1 if opt in correct_vals else 0),
                )

        elif qt == "fill_in":
            cursor.execute(
                """
                INSERT INTO theory_options (question_id, option_text, is_correct)
                VALUES (?, ?, 1)
                """,
                (q_id, q["fill_answer"]),
            )

        elif qt == "match":
            for a, b in q["match_pairs"]:
                cursor.execute(
                    """
                    INSERT INTO theory_options (question_id, option_text, is_correct, match_pair)
                    VALUES (?, ?, 1, ?)
                    """,
                    (q_id, a, b),
                )

        else:
            raise ValueError(f"Unhandled internal type during insert: {qt}")

