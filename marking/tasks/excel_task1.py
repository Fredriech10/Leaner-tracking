"""
tasks/excel_task1.py
────────────────────────────────────────────────────────────────────────────────
HOW TO USE THIS FILE AS A TEMPLATE:
  1. Copy this file and rename it  e.g. excel_task2.py / word_task1.py
  2. Change TASK_NAME and FILE_TYPE
  3. Import the checker functions you need at the top
  4. Fill in the QUESTIONS list — one dict per mark
  5. Do NOT touch anything else — base_marker handles the rest

AVAILABLE CHECKERS:
  from marking.checkers.excel  import *
  from marking.checkers.word   import *
  from marking.checkers.html   import *
  from marking.checkers.access import *
────────────────────────────────────────────────────────────────────────────────
"""

from marking.base_marker import mark_task
from marking.checkers.excel import (
    cells_merged,
    cell_has_background,
    range_number_format,
    cell_starts_with,
    cell_number_format,
    formula_contains,
    sheet_exists,
    chart_exists,
    chart_is_pie,
    chart_uses_range,
    page_is_landscape,
    print_area_is,
    repeat_columns_is,
)

# ── Task identity ─────────────────────────────────────────────────────────────

TASK_NAME = "Excel Task 1 – Spreadsheet Basics"
FILE_TYPE = ".xlsx"

# ── Questions ─────────────────────────────────────────────────────────────────
# Each question is a dict:
#   question : str       — description shown to the learner
#   marks    : int       — marks awarded if correct (default 1)
#   check    : callable  — checker function to call
#   params   : dict      — keyword args passed to the checker (NOT filepath)

QUESTIONS = [
    {
        "question": "A1:A6 are merged and centered",
        "marks": 1,
        "check": cells_merged,
        "params": {"merge_range": "A1:A6"},
    },
    {
        "question": "A1:A6 have a non-white/blank background colour",
        "marks": 1,
        "check": cell_has_background,
        "params": {"cell": "A1"},
    },
    {
        "question": "C2:C45 are formatted as currency",
        "marks": 1,
        "check": range_number_format,
        "params": {
            "start_row": 2,
            "end_row": 45,
            "col": "C",
            "keywords": ["$", "€", "£", "¥", "CURRENCY", "#,##0", "ACCOUNTING"],
        },
    },
    {
        "question": "B3 value starts with 0",
        "marks": 1,
        "check": cell_starts_with,
        "params": {"cell": "B3", "prefix": "0"},
    },
    {
        "question": "B3 is formatted as text (@)",
        "marks": 1,
        "check": cell_number_format,
        "params": {"cell": "B3", "expected_format": "@"},
    },
    {
        "question": "M2 contains =SUM",
        "marks": 1,
        "check": formula_contains,
        "params": {"cell": "M2", "expected": "=SUM"},
    },
    {
        "question": "M2 SUM range is (D2:D45)",
        "marks": 1,
        "check": formula_contains,
        "params": {"cell": "M2", "expected": "(D2:D45)"},
    },
    {
        "question": "M3 contains =IF",
        "marks": 1,
        "check": formula_contains,
        "params": {"cell": "M3", "expected": "=IF"},
    },
    {
        "question": "M3 IF condition is (E3>5",
        "marks": 1,
        "check": formula_contains,
        "params": {"cell": "M3", "expected": "E3>5"},
    },
    {
        "question": 'M3 IF true result is "Cheap"',
        "marks": 1,
        "check": formula_contains,
        "params": {"cell": "M3", "expected": ",CHEAP,"},
    },
    {
        "question": 'M3 IF false result is "Expensive"',
        "marks": 1,
        "check": formula_contains,
        "params": {"cell": "M3", "expected": ",EXPENSIVE)"},
    },
    {
        "question": 'Sheet named "budget" exists',
        "marks": 1,
        "check": sheet_exists,
        "params": {"sheet_name": "budget"},
    },
    {
        "question": "A chart exists on the sheet",
        "marks": 1,
        "check": chart_exists,
        "params": {},
    },
    {
        "question": "Chart is a pie chart",
        "marks": 1,
        "check": chart_is_pie,
        "params": {},
    },
    {
        "question": "Chart uses data range A2:E45",
        "marks": 1,
        "check": chart_uses_range,
        "params": {"expected_range": "A2:E45"},
    },
    {
        "question": "Page layout is landscape",
        "marks": 1,
        "check": page_is_landscape,
        "params": {},
    },
    {
        "question": "Print area is A1:E45",
        "marks": 1,
        "check": print_area_is,
        "params": {"expected_range": "A1:E45"},
    },
    {
        "question": "Column A set as repeating print header ($A:$A)",
        "marks": 1,
        "check": repeat_columns_is,
        "params": {"expected": "$A:$A"},
    },
]


# ── Entry point called by Flask (app.py) ──────────────────────────────────────

def mark(filepath):
    return mark_task(filepath, FILE_TYPE, TASK_NAME, QUESTIONS)
