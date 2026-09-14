from marking.tasks._gr12_prelim_p1 import mark_question


def mark_for_learner(filepath: str, learner_name: str) -> dict:
    return mark_question(filepath, "2", learner_name)


def mark(filepath: str) -> dict:
    return mark_question(filepath, "2")
