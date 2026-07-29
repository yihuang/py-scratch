"""
Operator opcodes — ``operator_add``, ``operator_random``, ``operator_mathop``, etc.
"""

from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..runtime import Runtime
    from ..target import Target
    from ..types import Block

from ..cast import compare, to_string
from ..constants import MATH_TRIG_PRECISION


def operator_add(rt: Runtime, tgt: Target, block: Block) -> Any:
    a = rt.num(tgt, block, "NUM1")
    b = rt.num(tgt, block, "NUM2")
    return a + b


def operator_subtract(rt: Runtime, tgt: Target, block: Block) -> Any:
    a = rt.num(tgt, block, "NUM1")
    b = rt.num(tgt, block, "NUM2")
    return a - b


def operator_multiply(rt: Runtime, tgt: Target, block: Block) -> Any:
    a = rt.num(tgt, block, "NUM1")
    b = rt.num(tgt, block, "NUM2")
    return a * b


def operator_divide(rt: Runtime, tgt: Target, block: Block) -> Any:
    a = rt.num(tgt, block, "NUM1")
    b = rt.num(tgt, block, "NUM2")
    return a / b if b != 0 else float("inf")


def operator_lt(rt: Runtime, tgt: Target, block: Block) -> Any:
    a = rt.val(tgt, block, "OPERAND1")
    b = rt.val(tgt, block, "OPERAND2")
    return compare(a, b) < 0


def operator_equals(rt: Runtime, tgt: Target, block: Block) -> Any:
    a = rt.val(tgt, block, "OPERAND1")
    b = rt.val(tgt, block, "OPERAND2")
    return compare(a, b) == 0


def operator_gt(rt: Runtime, tgt: Target, block: Block) -> Any:
    a = rt.val(tgt, block, "OPERAND1")
    b = rt.val(tgt, block, "OPERAND2")
    return compare(a, b) > 0


def operator_and(rt: Runtime, tgt: Target, block: Block) -> Any:
    return rt.truthy(tgt, block, "OPERAND1") and rt.truthy(tgt, block, "OPERAND2")


def operator_or(rt: Runtime, tgt: Target, block: Block) -> Any:
    return rt.truthy(tgt, block, "OPERAND1") or rt.truthy(tgt, block, "OPERAND2")


def operator_not(rt: Runtime, tgt: Target, block: Block) -> Any:
    return not rt.truthy(tgt, block, "OPERAND")


def operator_random(rt: Runtime, tgt: Target, block: Block) -> Any:
    lo = rt.num(tgt, block, "FROM")
    hi = rt.num(tgt, block, "TO")
    if lo > hi:
        lo, hi = hi, lo
    lo_int, hi_int = int(lo), int(hi)
    if lo == lo_int and hi == hi_int:
        return random.randint(lo_int, hi_int)
    else:
        return lo + (hi - lo) * random.random()


def operator_join(rt: Runtime, tgt: Target, block: Block) -> Any:
    return to_string(rt.val(tgt, block, "STRING1")) + to_string(rt.val(tgt, block, "STRING2"))


def operator_letter_of(rt: Runtime, tgt: Target, block: Block) -> Any:
    idx = rt.num_int(tgt, block, "LETTER")
    s = to_string(rt.val(tgt, block, "STRING"))
    if 1 <= idx <= len(s):
        return s[idx - 1]
    return ""


def operator_length(rt: Runtime, tgt: Target, block: Block) -> Any:
    return len(to_string(rt.val(tgt, block, "STRING")))


def operator_contains(rt: Runtime, tgt: Target, block: Block) -> Any:
    s1 = to_string(rt.val(tgt, block, "STRING1"))
    s2 = to_string(rt.val(tgt, block, "STRING2"))
    return s2.lower() in s1.lower()


def operator_mod(rt: Runtime, tgt: Target, block: Block) -> Any:
    a = rt.num(tgt, block, "NUM1")
    b = rt.num(tgt, block, "NUM2")
    return a % b if b != 0 else float("nan")


def operator_round(rt: Runtime, tgt: Target, block: Block) -> Any:
    return round(rt.num(tgt, block, "NUM"))


def operator_mathop(rt: Runtime, tgt: Target, block: Block) -> Any:
    operator = rt.field(tgt, block, "OPERATOR")
    n = rt.num(tgt, block, "NUM")
    if not operator:
        return 0
    match operator:
        case "abs":
            r = abs(n)
        case "floor":
            r = math.floor(n)
        case "ceiling":
            r = math.ceil(n)
        case "sqrt":
            r = math.sqrt(n) if n >= 0 else float("nan")
        case "sin":
            r = round(math.sin(math.radians(n)), MATH_TRIG_PRECISION)
        case "cos":
            r = round(math.cos(math.radians(n)), MATH_TRIG_PRECISION)
        case "tan":
            r = math.tan(math.radians(n)) if n % 180 != 90 else float("inf")
        case "asin":
            r = math.degrees(math.asin(max(-1, min(1, n))))
        case "acos":
            r = math.degrees(math.acos(max(-1, min(1, n))))
        case "atan":
            r = math.degrees(math.atan(n))
        case "ln":
            r = math.log(n) if n > 0 else float("-inf")
        case "log":
            r = math.log10(n) if n > 0 else float("-inf")
        case "e ^":
            r = math.exp(n)
        case "10 ^":
            r = math.pow(10, n)
        case _:
            r = 0
    return r
