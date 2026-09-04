"""Marks Grade 10 Term 2 test Question 3 from one uploaded workbook."""

from marking.tasks._gr10_term2_test import mark_question


def mark(filepath: str) -> dict:
    return mark_question(filepath, 3)
