"""Modular rule checker package for Marking Experiment."""

from .word import check_word_rule, get_word_rule_checker

__all__ = [
    "check_word_rule",
    "get_rule_checker",
]


def get_rule_checker(program: str):
    return get_word_rule_checker(program)
