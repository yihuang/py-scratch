"""
Operators category blocks — arithmetic, comparison, string, boolean, trigonometry.
"""

from __future__ import annotations

from scratch.vm.types import Field

from .expr import Reporter, _resolve_inputs
def add(a: int | float | Reporter, b: int | float | Reporter) -> Reporter:
    """``operator_add``."""
    ins, shadows = _resolve_inputs({"NUM1": a, "NUM2": b})
    return Reporter(opcode="operator_add", inputs=ins, shadow_reporters=shadows)


def sub(a: int | float | Reporter, b: int | float | Reporter) -> Reporter:
    """``operator_subtract``."""
    ins, shadows = _resolve_inputs({"NUM1": a, "NUM2": b})
    return Reporter(opcode="operator_subtract", inputs=ins, shadow_reporters=shadows)


def mult(a: int | float | Reporter, b: int | float | Reporter) -> Reporter:
    """``operator_multiply``."""
    ins, shadows = _resolve_inputs({"NUM1": a, "NUM2": b})
    return Reporter(opcode="operator_multiply", inputs=ins, shadow_reporters=shadows)


def div(a: int | float | Reporter, b: int | float | Reporter) -> Reporter:
    """``operator_divide``."""
    ins, shadows = _resolve_inputs({"NUM1": a, "NUM2": b})
    return Reporter(opcode="operator_divide", inputs=ins, shadow_reporters=shadows)


def random(from_: int | float | Reporter, to: int | float | Reporter) -> Reporter:
    """``operator_random``."""
    ins, shadows = _resolve_inputs({"FROM": from_, "TO": to})
    return Reporter(opcode="operator_random", inputs=ins, shadow_reporters=shadows)


# ── Comparison ────────────────────────────────────────────────────────────


def gt(a: int | float | str | Reporter, b: int | float | str | Reporter) -> Reporter:
    """``operator_gt`` — boolean reporter."""
    ins, shadows = _resolve_inputs({"OPERAND1": a, "OPERAND2": b})
    return Reporter(opcode="operator_gt", inputs=ins, shadow_reporters=shadows)


def lt(a: int | float | str | Reporter, b: int | float | str | Reporter) -> Reporter:
    """``operator_lt`` — boolean reporter."""
    ins, shadows = _resolve_inputs({"OPERAND1": a, "OPERAND2": b})
    return Reporter(opcode="operator_lt", inputs=ins, shadow_reporters=shadows)


def eq(a: int | float | str | Reporter, b: int | float | str | Reporter) -> Reporter:
    """``operator_equals`` — boolean reporter."""
    ins, shadows = _resolve_inputs({"OPERAND1": a, "OPERAND2": b})
    return Reporter(opcode="operator_equals", inputs=ins, shadow_reporters=shadows)


# ── Boolean ───────────────────────────────────────────────────────────────


def and_(a: Reporter, b: Reporter) -> Reporter:
    """``operator_and`` — boolean reporter."""
    ins, shadows = _resolve_inputs({"OPERAND1": a, "OPERAND2": b})
    return Reporter(opcode="operator_and", inputs=ins, shadow_reporters=shadows)


def or_(a: Reporter, b: Reporter) -> Reporter:
    """``operator_or`` — boolean reporter."""
    ins, shadows = _resolve_inputs({"OPERAND1": a, "OPERAND2": b})
    return Reporter(opcode="operator_or", inputs=ins, shadow_reporters=shadows)


def not_(a: Reporter) -> Reporter:
    """``operator_not`` — boolean reporter."""
    ins, shadows = _resolve_inputs({"OPERAND": a})
    return Reporter(opcode="operator_not", inputs=ins, shadow_reporters=shadows)


# ── String ────────────────────────────────────────────────────────────────


def join(a: str | Reporter, b: str | Reporter) -> Reporter:
    """``operator_join``."""
    ins, shadows = _resolve_inputs({"STRING1": a, "STRING2": b})
    return Reporter(opcode="operator_join", inputs=ins, shadow_reporters=shadows)


def letter_of(letter: int | float | Reporter, string: str | Reporter) -> Reporter:
    """``operator_letter_of``."""
    ins, shadows = _resolve_inputs({"LETTER": letter, "STRING": string})
    return Reporter(opcode="operator_letter_of", inputs=ins, shadow_reporters=shadows)


def length(string: str | Reporter) -> Reporter:
    """``operator_length``."""
    ins, shadows = _resolve_inputs({"STRING": string})
    return Reporter(opcode="operator_length", inputs=ins, shadow_reporters=shadows)


def contains(string: str | Reporter, substring: str | Reporter) -> Reporter:
    """``operator_contains`` — boolean reporter."""
    ins, shadows = _resolve_inputs({"STRING1": string, "STRING2": substring})
    return Reporter(opcode="operator_contains", inputs=ins, shadow_reporters=shadows)


# ── Math ──────────────────────────────────────────────────────────────────


def mod(a: int | float | Reporter, b: int | float | Reporter) -> Reporter:
    """``operator_mod``."""
    ins, shadows = _resolve_inputs({"NUM1": a, "NUM2": b})
    return Reporter(opcode="operator_mod", inputs=ins, shadow_reporters=shadows)


def round_(n: int | float | Reporter) -> Reporter:
    """``operator_round``."""
    ins, shadows = _resolve_inputs({"NUM": n})
    return Reporter(opcode="operator_round", inputs=ins, shadow_reporters=shadows)


def sqrt(n: int | float | Reporter) -> Reporter:
    """``operator_mathop`` with ``sqrt``."""

    ins, shadows = _resolve_inputs({"NUM": n})
    return Reporter(
        opcode="operator_mathop",
        inputs=ins,
        fields={"OPERATOR": Field(name="OPERATOR", value="sqrt")},
        shadow_reporters=shadows,
    )


def abs_(n: int | float | Reporter) -> Reporter:
    """``operator_mathop`` with ``abs``."""

    ins, shadows = _resolve_inputs({"NUM": n})
    return Reporter(
        opcode="operator_mathop",
        inputs=ins,
        fields={"OPERATOR": Field(name="OPERATOR", value="abs")},
        shadow_reporters=shadows,
    )


def floor_(n: int | float | Reporter) -> Reporter:
    """``operator_mathop`` with ``floor``."""

    ins, shadows = _resolve_inputs({"NUM": n})
    return Reporter(
        opcode="operator_mathop",
        inputs=ins,
        fields={"OPERATOR": Field(name="OPERATOR", value="floor")},
        shadow_reporters=shadows,
    )


def ceil_(n: int | float | Reporter) -> Reporter:
    """``operator_mathop`` with ``ceil``."""

    ins, shadows = _resolve_inputs({"NUM": n})
    return Reporter(
        opcode="operator_mathop",
        inputs=ins,
        fields={"OPERATOR": Field(name="OPERATOR", value="ceil")},
        shadow_reporters=shadows,
    )


# ── Trigonometry ──────────────────────────────────────────────────────────


def _mathop(name: str, n: int | float | Reporter) -> Reporter:

    ins, shadows = _resolve_inputs({"NUM": n})
    return Reporter(
        opcode="operator_mathop",
        inputs=ins,
        fields={"OPERATOR": Field(name="OPERATOR", value=name)},
        shadow_reporters=shadows,
    )


def sin(n: int | float | Reporter) -> Reporter:
    """``operator_mathop`` with ``sin``."""
    return _mathop("sin", n)


def cos(n: int | float | Reporter) -> Reporter:
    """``operator_mathop`` with ``cos``."""
    return _mathop("cos", n)


def tan(n: int | float | Reporter) -> Reporter:
    """``operator_mathop`` with ``tan``."""
    return _mathop("tan", n)


def asin(n: int | float | Reporter) -> Reporter:
    """``operator_mathop`` with ``asin``."""
    return _mathop("asin", n)


def acos(n: int | float | Reporter) -> Reporter:
    """``operator_mathop`` with ``acos``."""
    return _mathop("acos", n)


def atan(n: int | float | Reporter) -> Reporter:
    """``operator_mathop`` with ``atan``."""
    return _mathop("atan", n)
