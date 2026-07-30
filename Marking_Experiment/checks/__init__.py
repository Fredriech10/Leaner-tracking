"""Modular rule checker package for Marking Experiment."""

from .word import check_word_rule, get_word_rule_checker
from .hyperlink import check_hyperlink_rule
from .cross_reference import check_cross_reference_rule

__all__ = [
    "check_word_rule",
    "get_rule_checker",
    "check_hyperlink_rule",
    "check_cross_reference_rule",
]



def get_rule_checker(program: str):
    return get_word_rule_checker(program)

