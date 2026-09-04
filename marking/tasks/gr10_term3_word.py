"""Marks the Word section of Grade 10 Term 3 CAT Task 4."""

from marking.tasks._gr10_term3 import mark_submission


def mark(filepath: str) -> dict:
    return mark_submission(filepath, "word", "CAT Grade 10 Term 3 Task 4: Word Processing")
