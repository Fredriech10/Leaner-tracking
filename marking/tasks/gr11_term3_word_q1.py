"""Marks Grade 11 Term 3 Task 4 Question 1 from one uploaded Word document."""

from marking.tasks._gr11_term3 import mark_question


def mark(filepath: str) -> dict:
    return mark_question(filepath, 1)
