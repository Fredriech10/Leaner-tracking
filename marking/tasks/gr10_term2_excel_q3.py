from marking.tasks._gr10_term2 import mark_submission


def mark(filepath: str) -> dict:
    return mark_submission(filepath, "3Uber Ride Bookings.xlsx", "excel", "CAT Grade 10 Term 2: Spreadsheet Question 3")
