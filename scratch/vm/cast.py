"""
Cast — Scratch data-type coercion and comparison.

Faithful Python port of the official scratch-vm ``Cast`` class.

Scratch behaves subtly differently from Python/JavaScript in many respects,
and these differences are encapsulated here.  For example::

    Cast.to_number("hello")  → 0       # Python float("hello") → ValueError
    Cast.to_number("")       → 0       # Python float("") → ValueError
    Cast.to_number(None)     → 0       # Python float(None) → TypeError
    Cast.to_number(True)     → 1       # Python float(True) → 1.0
    Cast.to_number(False)    → 0       # Python float(False) → 0.0
    Cast.to_number(float("nan")) → 0   # Python leaves NaN as-is
    Cast.to_string(None)     → ""      # Python str(None) → "None"
    Cast.to_string(-0.0)     → "0"     # Python str(-0.0) → "-0.0"
    Cast.to_boolean("false") → False   # Python bool("false") → True
    Cast.to_boolean("0")     → False   # Python bool("0") → True
"""

from __future__ import annotations

import math
import random
import re
from typing import Any

# ── Sentinels ────────────────────────────────────────────────────────────

LIST_INVALID: int = 0
"""Sentinel value meaning ``"the index is invalid"``.

Zero is never a valid 1-based index, making it a natural INVALID sentinel
for our int-returning ``to_list_index``.  The official VM uses the string
``"INVALID"``.
"""

LIST_ALL: str = "ALL"
"""Special sentinel meaning ``"all items in the list"``.

This is returned by ``to_list_index`` when *accept_all* is True and the
user passes ``"all"`` as the index.
"""


# ═════════════════════════════════════════════════════════════════════════
#  Core coercion
# ═════════════════════════════════════════════════════════════════════════


def to_number(value: Any) -> float:
    """Scratch cast to number.  NaN → 0.

    Mirrors ``Cast.toNumber()`` in scratch-vm.
    """
    if isinstance(value, float):
        if math.isnan(value):
            return 0.0
        return value
    if isinstance(value, int):
        return float(value)
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if value is None:
        return 0.0
    try:
        n = float(value)
    except (ValueError, TypeError):
        return 0.0
    if math.isnan(n):
        return 0.0
    return n


def to_boolean(value: Any) -> bool:
    """Scratch cast to boolean.

    Mirrors ``Cast.toBoolean()`` in scratch-vm.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        # In Scratch the strings '' '0' 'false' (case-insensitive) are false.
        return value not in ("", "0") and value.lower() != "false"
    return bool(value)


def to_string(value: Any) -> str:
    """Scratch cast to string.

    Mirrors ``Cast.toString()`` in scratch-vm.

    Extensions beyond the official VM:
    * ``None`` → ``""`` (Python's ``str(None)`` → ``"None"``, wrong for Scratch)
    * ``-0.0`` → ``"0"`` (Python's ``str(-0.0)`` → ``"-0.0"``)
    * Booleans → ``"true"`` / ``"false"`` (Scratch convention)
    * Floats → ``:g``-formatted (no trailing zeros)
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        if value == -0.0:
            value = 0.0
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
        if math.isnan(value):
            return "NaN"
        return f"{value:g}"
    if isinstance(value, int):
        return str(value)
    return str(value)


# ═════════════════════════════════════════════════════════════════════════
#  Type introspection
# ═════════════════════════════════════════════════════════════════════════


def is_whitespace(val: Any) -> bool:
    """Check if a Scratch argument is whitespace / null / empty.

    Mirrors ``Cast.isWhiteSpace()`` in scratch-vm.
    """
    return val is None or (isinstance(val, str) and val.strip() == "")


def is_int(val: Any) -> bool:
    """Determine if a Scratch argument represents a round integer.

    Mirrors ``Cast.isInt()`` in scratch-vm::

        is_int(42) → True
        is_int(3.14) → False
        is_int("5") → True
        is_int("5.0") → False   (contains '.')
        is_int(NaN) → True
        is_int(True) → True
        is_int(False) → True
    """
    if isinstance(val, (bool, int)):
        return True
    if isinstance(val, float):
        if math.isnan(val):
            return True
        return val == int(val)
    if isinstance(val, str):
        return "." not in val
    return False


def is_nan(val: Any) -> bool:
    """Check if a value is NaN or casts to NaN in Scratch."""
    if isinstance(val, float) and math.isnan(val):
        return True
    if isinstance(val, str):
        if val.strip() == "":
            return True
        try:
            n = float(val)
        except (ValueError, TypeError):
            return True
        return math.isnan(n)
    if val is None:
        return True
    try:
        n = float(val)
    except (ValueError, TypeError):
        return True
    return math.isnan(n)


# ═════════════════════════════════════════════════════════════════════════
#  Comparison
# ═════════════════════════════════════════════════════════════════════════


def _raw_number(value: Any) -> float:
    """Like JavaScript ``Number()`` — returns NaN for anything non-numeric.

    This is used internally by ``compare()`` which needs to distinguish
    between "casts to 0" and "casts to NaN" — something ``to_number()``
    deliberately erases (NaN → 0).
    """
    if value is None:
        return float("nan")
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (ValueError, TypeError):
        return float("nan")


def compare(v1: Any, v2: Any) -> int:
    """Compare two values using Scratch rules.

    Returns ``-1`` / ``0`` / ``1`` (negative / equal / positive).

    Mirrors ``Cast.compare()`` in scratch-vm:
    1. Try to cast both to numbers (raw ``Number()`` — preserves NaN).
    2. If either result is exactly 0 AND the original is whitespace,
       treat that value as NaN instead.
    3. If either is NaN, compare case-insensitively as strings.
    4. ``Infinity == Infinity``, ``-Infinity == -Infinity``.
    5. Otherwise compare as numbers.
    """
    n1 = _raw_number(v1)
    n2 = _raw_number(v2)
    # Whitespace/None → NaN in the compare path (even though to_number
    # would give 0 — that's the arithmetic path).
    if n1 == 0.0 and is_whitespace(v1):
        n1 = float("nan")
    if n2 == 0.0 and is_whitespace(v2):
        n2 = float("nan")

    if math.isnan(n1) or math.isnan(n2):
        s1 = to_string(v1).lower()
        s2 = to_string(v2).lower()
        if s1 < s2:
            return -1
        if s1 > s2:
            return 1
        return 0

    if (n1 == float("inf") and n2 == float("inf")) or (n1 == float("-inf") and n2 == float("-inf")):
        return 0

    if n1 < n2:
        return -1
    if n1 > n2:
        return 1
    return 0


# ═════════════════════════════════════════════════════════════════════════
#  List index
# ═════════════════════════════════════════════════════════════════════════


def to_list_index(index: Any, length: int, accept_all: bool = False) -> int | str:
    """Compute a 1-based index into a list, based on a Scratch argument.

    Mirrors ``Cast.toListIndex()`` in scratch-vm.

    Special values
    --------------
    * ``"all"`` → ``LIST_ALL`` (only when *accept_all* is True)
    * ``"last"`` → *length* (1-based), or ``LIST_INVALID`` if empty
    * ``"random"`` / ``"any"`` → random 1..*length*, or ``LIST_INVALID`` if empty
    * Numeric → ``floor(to_number(index))``, or ``LIST_INVALID`` if out of range

    Parameters
    ----------
    index:
        The raw Scratch argument (input value) for the list index.
    length:
        Current length of the list.
    accept_all:
        If True, the string ``"all"`` is accepted and returns ``LIST_ALL``.
        Used by ``deleteOfList``.  Set to False for ``getItemOfList``,
        ``replaceItemOfList``, ``insertAtList``.

    Returns
    -------
    int | str
        A 1-based index (int), or ``LIST_ALL`` (str sentinel), or
        ``LIST_INVALID`` (int 0) if invalid.
    """
    if isinstance(index, str):
        v = index.lower()
        if v == "all":
            return LIST_ALL if accept_all else LIST_INVALID
        if v == "last":
            return length if length > 0 else LIST_INVALID
        if v in ("random", "any"):
            if length > 0:
                return 1 + random.randint(0, length - 1)  # 1-based
            return LIST_INVALID
    # Numeric path — also covers bool, float, int
    idx = int(math.floor(to_number(index)))
    if idx < 1 or idx > length:
        return LIST_INVALID
    return idx


# ═════════════════════════════════════════════════════════════════════════
#  Color helpers
# ═════════════════════════════════════════════════════════════════════════


def decimal_to_rgb(decimal: float) -> dict[str, int]:
    """Convert a Scratch decimal color to an RGB dict.

    Mirrors ``Color.decimalToRgb()`` in scratch-vm/Color.

    Returns ``{"r": ..., "g": ..., "b": ..., "a": ...}``.
    """
    d = int(decimal)
    a = (d >> 24) & 0xFF
    r = (d >> 16) & 0xFF
    g = (d >> 8) & 0xFF
    b = d & 0xFF
    return {"r": r, "g": g, "b": b, "a": a if a > 0 else 255}


def hex_to_rgb(hex_str: str) -> dict[str, int] | None:
    """Convert a hex color string to an RGB dict.

    Mirrors ``Color.hexToRgb()`` in scratch-vm/Color.

    Accepts ``"F00"``, ``"#03F"``, ``"#0033FF"``, etc.
    Returns ``None`` if the string is not valid hex.
    """
    h = hex_str.lstrip("#")
    shorthand = re.match(r"^([a-fA-F\d])([a-fA-F\d])([a-fA-F\d])$", h)
    if shorthand:
        h = "".join(c * 2 for c in shorthand.groups())
    full = re.match(r"^([a-fA-F\d]{2})([a-fA-F\d]{2})([a-fA-F\d]{2})$", h)
    if full:
        return {
            "r": int(full.group(1), 16),
            "g": int(full.group(2), 16),
            "b": int(full.group(3), 16),
        }
    return None


def to_rgb_color_object(value: Any) -> dict[str, int]:
    """Cast any Scratch argument to an RGB color object.

    Mirrors ``Cast.toRgbColorObject()`` in scratch-vm.
    """
    if isinstance(value, str) and value.startswith("#"):
        color = hex_to_rgb(value)
        if color is not None:
            return color
        return {"r": 0, "g": 0, "b": 0, "a": 255}
    return decimal_to_rgb(to_number(value))


def to_rgb_color_list(value: Any) -> list[int]:
    """Cast any Scratch argument to an RGB color list.

    Mirrors ``Cast.toRgbColorList()`` in scratch-vm.
    """
    c = to_rgb_color_object(value)
    return [c["r"], c["g"], c["b"]]
