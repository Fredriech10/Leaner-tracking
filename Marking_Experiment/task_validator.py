"""Task definition validator for Marking Experiment.

Ensures task definitions are well-formed and only reference supported programs
and check types (currently Word only).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from .marking_experiment import MARKING_SCHEMA

logger = logging.getLogger(__name__)

# Programs that are currently fully implemented
SUPPORTED_PROGRAMS = {"word"}

# Valid domain/type combinations for each program
VALID_COMBINATIONS = {}
for program, domains in MARKING_SCHEMA.items():
    VALID_COMBINATIONS[program] = set()
    for domain, types in domains.items():
        if isinstance(types, dict):
            for check_type in types.keys():
                VALID_COMBINATIONS[program].add((domain, check_type))
        else:
            # Legacy format with string values
            VALID_COMBINATIONS[program].add((domain, types))


def validate_task_definition(task_def: Dict[str, Any]) -> tuple[bool, List[str]]:
    """Validate a task definition for correctness and supportability.
    
    Args:
        task_def: Task definition dict.
    
    Returns:
        Tuple of (is_valid, list_of_warnings).
        is_valid is False if there are critical errors; True if task can run.
        warnings lists all issues found (critical and non-critical).
    """
    warnings: List[str] = []
    
    # Check task structure
    if not isinstance(task_def, dict):
        warnings.append("Task definition must be a dict.")
        return False, warnings
    
    if "task_name" not in task_def:
        warnings.append("Missing 'task_name' field.")
    
    # Check program
    program = str(task_def.get("program", "word")).lower()
    if program not in SUPPORTED_PROGRAMS:
        warnings.append(
            f"Program '{program}' is not fully implemented. "
            f"Supported programs: {sorted(SUPPORTED_PROGRAMS)}. "
            f"Task will not run correctly."
        )
        return False, warnings
    
    if "total_marks" not in task_def:
        warnings.append("Missing 'total_marks' field.")
    
    if "questions" not in task_def:
        warnings.append("Missing 'questions' field.")
        return False, warnings
    
    questions = task_def.get("questions", [])
    if not isinstance(questions, list):
        warnings.append("'questions' must be a list.")
        return False, warnings
    
    if not questions:
        warnings.append("Task has no questions.")
    
    # Validate each question
    for idx, question in enumerate(questions, start=1):
        q_warnings = _validate_question(question, idx, program)
        warnings.extend(q_warnings)
    
    # Count errors vs warnings
    critical_errors = [w for w in warnings if "not fully implemented" in w or "not supported" in w]
    
    return len(critical_errors) == 0, warnings


def _validate_question(question: Dict[str, Any], question_idx: int, program: str) -> List[str]:
    """Validate a single question within a task.
    
    Args:
        question: Question dict.
        question_idx: Index of question (1-based).
        program: Program being used (e.g., "word").
    
    Returns:
        List of warnings/errors for this question.
    """
    warnings: List[str] = []
    
    if not isinstance(question, dict):
        warnings.append(f"Question {question_idx}: not a dict.")
        return warnings
    
    # Check structure
    for required_field in ["question_number", "description", "domain", "type", "target", "expected", "marks"]:
        if required_field not in question:
            warnings.append(f"Question {question_idx}: missing '{required_field}' field.")
    
    # Check domain and type
    domain = str(question.get("domain", "")).lower()
    check_type = str(question.get("type", "")).lower()
    
    if not domain or not check_type:
        return warnings  # Already warned about missing fields
    
    valid_combos = VALID_COMBINATIONS.get(program, set())
    if (domain, check_type) not in valid_combos:
        warnings.append(
            f"Question {question_idx}: ({domain}, {check_type}) is not a valid combination "
            f"for program '{program}'. Task may fail during execution."
        )
    
    # Check target
    target = question.get("target", {})
    if not isinstance(target, dict):
        warnings.append(f"Question {question_idx}: 'target' must be a dict.")
    
    # Check marks
    try:
        marks = int(question.get("marks", 1))
        if marks <= 0:
            warnings.append(f"Question {question_idx}: 'marks' must be > 0.")
    except (ValueError, TypeError):
        warnings.append(f"Question {question_idx}: 'marks' must be numeric.")
    
    return warnings


def constrain_task_to_word(task_def: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure task only references Word program.
    
    If the program is not 'word', forces it to 'word'.
    If there are unsupported (domain, type) combinations, removes them.
    
    Args:
        task_def: Task definition dict.
    
    Returns:
        Modified task definition (safe copy).
    """
    task = dict(task_def)
    
    # Force program to word
    if str(task.get("program", "word")).lower() != "word":
        logger.warning(f"Changing program from '{task.get('program')}' to 'word'")
        task["program"] = "word"
    
    # Filter questions to only valid Word combinations
    valid_combos = VALID_COMBINATIONS.get("word", set())
    filtered_questions = []
    
    for question in task.get("questions", []):
        domain = str(question.get("domain", "")).lower()
        check_type = str(question.get("type", "")).lower()
        
        if (domain, check_type) in valid_combos:
            filtered_questions.append(question)
        else:
            logger.warning(
                f"Removing question {question.get('question_number')}: "
                f"({domain}, {check_type}) not supported for Word"
            )
    
    task["questions"] = filtered_questions
    
    # Recalculate total_marks
    total_marks = sum(int(q.get("marks", 1)) for q in filtered_questions)
    task["total_marks"] = total_marks
    
    return task
