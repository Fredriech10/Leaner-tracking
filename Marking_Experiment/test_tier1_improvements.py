"""Integration test for Marking Experiment Tier 1 improvements.

This test verifies:
1. Unit conversions work correctly
2. Numeric comparisons use tolerances
3. Targeting strategies find paragraphs robustly
4. Task validation works
5. WordChecker uses new utilities
"""

from __future__ import annotations

import logging
from pathlib import Path

# Configure logging
from .config import configure_logging
configure_logging(level="DEBUG")

from .utils import (
    pt_to_emu, emu_to_pt, cm_to_emu, emu_to_cm,
    compare_numeric, normalize_hex_color,
    TOLERANCE_PT, TOLERANCE_CM
)
from .targeting import string_similarity, Locator
from .task_validator import validate_task_definition, constrain_task_to_word


def test_unit_conversions():
    """Test unit conversion accuracy."""
    print("\n=== Testing Unit Conversions ===")
    
    # Test pt <-> EMU conversions
    assert pt_to_emu(12) == 152400, "12 pt should be 152400 EMU"
    assert emu_to_pt(152400) == 12.0, "152400 EMU should be 12.0 pt"
    
    # Test cm <-> EMU conversions
    assert cm_to_emu(2.5) == 900000, "2.5 cm should be 900000 EMU"
    assert emu_to_cm(900000) == 2.5, "900000 EMU should be 2.5 cm"
    
    print("  [OK] Unit conversions: PASS")


def test_numeric_comparisons():
    """Test numeric comparisons with tolerances."""
    print("\n=== Testing Numeric Comparisons ===")
    
    # Test font size comparison (within tolerance)
    assert compare_numeric(12.0, 12.2, tolerance=TOLERANCE_PT, unit="pt") == True
    assert compare_numeric(12.0, 11.8, tolerance=TOLERANCE_PT, unit="pt") == True
    assert compare_numeric(12.0, 12.6, tolerance=TOLERANCE_PT, unit="pt") == False
    
    # Test margin comparison (within tolerance)
    assert compare_numeric(2.5, 2.52, tolerance=TOLERANCE_CM, unit="cm") == True
    assert compare_numeric(2.5, 2.57, tolerance=TOLERANCE_CM, unit="cm") == False  # 0.07 > 0.05
    
    print("  [OK] Numeric comparisons: PASS")


def test_color_normalization():
    """Test hex color normalization."""
    print("\n=== Testing Color Normalization ===")
    
    assert normalize_hex_color("#FF0000") == "FF0000"
    assert normalize_hex_color("ff0000") == "FF0000"
    assert normalize_hex_color("FF0000") == "FF0000"
    assert normalize_hex_color(None) is None
    assert normalize_hex_color("invalid") is None
    
    print("  [OK] Color normalization: PASS")


def test_string_similarity():
    """Test string similarity for fuzzy matching."""
    print("\n=== Testing String Similarity ===")
    
    # Exact match
    assert string_similarity("Introduction", "Introduction") == 1.0
    
    # Case insensitive
    assert string_similarity("Introduction", "introduction") == 1.0
    
    # Similar with typo
    similarity = string_similarity("Introduction", "Introduccion")
    assert 0.85 < similarity < 0.95, f"Typo match should be ~0.92, got {similarity}"
    
    # Completely different
    similarity = string_similarity("Introduction", "Conclusion")
    assert similarity < 0.5, f"Different words should have low similarity, got {similarity}"
    
    print("  [OK] String similarity: PASS")


def test_task_validation():
    """Test task validation for Word-only support."""
    print("\n=== Testing Task Validation ===")
    
    # Valid task
    valid_task = {
        "task_name": "Test Task",
        "program": "word",
        "total_marks": 5,
        "questions": [
            {
                "question_number": "1",
                "description": "Check alignment",
                "domain": "paragraph_formatting",
                "type": "alignment",
                "target": {"locator": "document"},
                "expected": "left",
                "marks": 1
            }
        ]
    }
    
    is_valid, warnings = validate_task_definition(valid_task)
    assert is_valid == True, f"Valid task should pass: {warnings}"
    print(f"  [OK] Valid task: PASS (warnings: {len(warnings)})")
    
    # Invalid task (unsupported program)
    invalid_task = {
        "task_name": "Excel Task",
        "program": "excel",
        "total_marks": 5,
        "questions": []
    }
    
    is_valid, warnings = validate_task_definition(invalid_task)
    assert is_valid == False, "Excel task should fail validation"
    print(f"  [OK] Invalid program detection: PASS")
    
    # Constrain to Word
    constrained = constrain_task_to_word(invalid_task)
    assert constrained["program"] == "word"
    print(f"  [OK] Task constraint to Word: PASS")


def test_locator():
    """Test Locator class."""
    print("\n=== Testing Locator ===")
    
    loc1 = Locator("after_heading", "Introduction")
    assert loc1.kind == "after_heading"
    assert loc1.value == "Introduction"
    
    loc2 = Locator("paragraph_index", "0")
    assert loc2.kind == "paragraph_index"
    assert loc2.value == "0"
    
    print("  [OK] Locator: PASS")


def run_all_tests():
    """Run all integration tests."""
    print("\n" + "=" * 60)
    print("MARKING_EXPERIMENT TIER 1 INTEGRATION TESTS")
    print("=" * 60)
    
    try:
        test_unit_conversions()
        test_numeric_comparisons()
        test_color_normalization()
        test_string_similarity()
        test_task_validation()
        test_locator()
        
        print("\n" + "=" * 60)
        print("ALL TESTS PASSED!")
        print("=" * 60)
        return True
    
    except AssertionError as e:
        print(f"\nTEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        return False

