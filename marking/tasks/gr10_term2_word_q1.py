from marking.tasks._gr10_term2 import mark_submission


def mark(filepath: str) -> dict:
    return mark_submission(filepath, "1Uber Service.docx", "word", "CAT Grade 10 Term 2: Word Question 1")
