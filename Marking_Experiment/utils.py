"""Utilities for deterministic unit conversions and numeric comparisons.

This module centralizes all unit conversion and numeric comparison logic
to ensure consistency and avoid floating-point precision errors.
"""

from __future__ import annotations

from typing import Literal, Optional, Tuple


# Unit conversion constants (EMU = English Metric Units, used by Word)
EMU_PER_PT = 12700
EMU_PER_CM = 360000
PT_PER_INCH = 72
CM_PER_INCH = 2.54
TWIPS_PER_PT = 20  # Twips are used in some Word properties

# Standard tolerances for numeric comparisons (in original units)
TOLERANCE_PT = 0.5  # ±0.5 points for font size, border width, etc.
TOLERANCE_CM = 0.05  # ±0.05 cm for margins, indentation, etc.
TOLERANCE_LINES = 0.1  # ±0.1 lines for line spacing


def pt_to_emu(pt: float) -> int:
    """Convert points to EMU (English Metric Units)."""
    return int(round(pt * EMU_PER_PT))


def emu_to_pt(emu: int) -> float:
    """Convert EMU to points."""
    return round(emu / EMU_PER_PT, 2)


def cm_to_emu(cm: float) -> int:
    """Convert centimeters to EMU."""
    return int(round(cm * EMU_PER_CM))


def emu_to_cm(emu: int) -> float:
    """Convert EMU to centimeters."""
    return round(emu / EMU_PER_CM, 2)


def pt_to_cm(pt: float) -> float:
    """Convert points to centimeters."""
    return round(pt / PT_PER_INCH * CM_PER_INCH, 2)


def cm_to_pt(cm: float) -> float:
    """Convert centimeters to points."""
    return round(cm * PT_PER_INCH / CM_PER_INCH, 2)


def twips_to_pt(twips: float) -> float:
    """Convert twips (1/20 point) to points."""
    return round(twips / TWIPS_PER_PT, 2)


def pt_to_twips(pt: float) -> int:
    """Convert points to twips."""
    return int(round(pt * TWIPS_PER_PT))


def normalize_numeric(value: Optional[float], unit: str = "pt") -> Optional[float]:
    """Normalize a numeric value to a standard representation.
    
    Args:
        value: The numeric value to normalize.
        unit: The unit of the value ('pt', 'cm', 'lines', 'emu', 'twips').
    
    Returns:
        The value in standard units (pt for most, cm for margins/indentation, lines for spacing).
    """
    if value is None:
        return None
    
    unit_lower = str(unit).lower().strip()
    if unit_lower == "pt":
        return round(float(value), 2)
    elif unit_lower == "cm":
        return round(float(value), 2)
    elif unit_lower == "lines":
        return round(float(value), 2)
    elif unit_lower == "emu":
        return emu_to_pt(int(value))
    elif unit_lower == "twips":
        return twips_to_pt(float(value))
    else:
        return round(float(value), 2)


def compare_numeric(
    actual: Optional[float],
    expected: Optional[float],
    tolerance: float = TOLERANCE_PT,
    unit: str = "pt",
) -> bool:
    """Compare two numeric values with a standard tolerance.
    
    Args:
        actual: The actual value.
        expected: The expected value.
        tolerance: The tolerance (in same units as actual/expected).
        unit: The unit for context ('pt', 'cm', 'lines', etc.). Affects default tolerance.
    
    Returns:
        True if abs(actual - expected) <= tolerance, False otherwise.
    """
    if actual is None or expected is None:
        return actual == expected
    
    # Use unit-specific tolerance if not explicitly provided
    if tolerance == TOLERANCE_PT:
        if unit == "cm":
            tolerance = TOLERANCE_CM
        elif unit == "lines":
            tolerance = TOLERANCE_LINES
    
    actual_f = float(actual)
    expected_f = float(expected)
    diff = abs(actual_f - expected_f)
    
    return diff <= tolerance


def compare_numeric_dict(
    actual: Optional[dict],
    expected: Optional[dict],
    keys_to_compare: Optional[list] = None,
    tolerance_map: Optional[dict] = None,
) -> bool:
    """Compare two dicts of numeric values.
    
    Args:
        actual: Actual dict of values.
        expected: Expected dict of values.
        keys_to_compare: Which keys to compare (default: all keys in expected).
        tolerance_map: Map of key -> tolerance (default: TOLERANCE_PT for all).
    
    Returns:
        True if all specified keys match within their tolerances.
    """
    if actual is None or expected is None:
        return actual == expected
    
    actual_dict = dict(actual)
    expected_dict = dict(expected)
    keys = keys_to_compare or list(expected_dict.keys())
    tolerance_map = tolerance_map or {}
    
    for key in keys:
        if key not in expected_dict:
            continue
        act_val = actual_dict.get(key)
        exp_val = expected_dict.get(key)
        tol = tolerance_map.get(key, TOLERANCE_PT)
        
        if not compare_numeric(act_val, exp_val, tolerance=tol):
            return False
    
    return True


def normalize_hex_color(color: Optional[str]) -> Optional[str]:
    """Normalize a hex color to uppercase 6-char format.
    
    Args:
        color: Hex color (with or without #).
    
    Returns:
        Uppercase 6-char hex string, or None if invalid.
    """
    if not color:
        return None
    
    value = str(color).strip().upper().lstrip("#")
    return value if len(value) == 6 else None


def parse_unit_value(text: str) -> Tuple[Optional[float], Optional[str]]:
    """Parse a value with unit from text.
    
    Examples:
        "12.5 pt" -> (12.5, "pt")
        "2.5cm" -> (2.5, "cm")
        "1.5 lines" -> (1.5, "lines")
    
    Args:
        text: Text to parse.
    
    Returns:
        Tuple of (value, unit) or (None, None) if unparseable.
    """
    import re
    
    text = str(text).strip()
    match = re.search(r"([\d.]+)\s*([a-zA-Z%]+)?", text)
    if not match:
        return None, None
    
    try:
        value = float(match.group(1))
        unit = match.group(2).lower() if match.group(2) else None
        return value, unit
    except (ValueError, AttributeError):
        return None, None
