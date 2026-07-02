"""
Data (Variables & Lists) category blocks.
"""

from __future__ import annotations

from scratch.vm.types import Field

from .expr import Reporter, StackExpr, _resolve_inputs
def set_variable(variable: str, value: int | float | str | Reporter = 0) -> StackExpr:
    """``data_setvariableto``.

    *variable* is the variable name (dropdown field).
    *value* is the input (literal or reporter).
    """

    ins, shadows = _resolve_inputs({"VALUE": value})
    return StackExpr(
        opcode="data_setvariableto",
        inputs=ins,
        fields={"VARIABLE": Field(name="VARIABLE", value=variable)},
        shadow_reporters=shadows,
    )


def change_variable(variable: str, change: int | float | Reporter = 1) -> StackExpr:
    """``data_changevariableby``."""

    ins, shadows = _resolve_inputs({"VALUE": change})
    return StackExpr(
        opcode="data_changevariableby",
        inputs=ins,
        fields={"VARIABLE": Field(name="VARIABLE", value=variable)},
        shadow_reporters=shadows,
    )


def show_variable(variable: str) -> StackExpr:
    """``data_showvariable``."""

    return StackExpr(
        opcode="data_showvariable",
        fields={"VARIABLE": Field(name="VARIABLE", value=variable)},
    )


def hide_variable(variable: str) -> StackExpr:
    """``data_hidevariable``."""

    return StackExpr(
        opcode="data_hidevariable",
        fields={"VARIABLE": Field(name="VARIABLE", value=variable)},
    )


# ── Variable reporters ────────────────────────────────────────────────────


def variable(variable: str) -> Reporter:
    """``data_variable`` — reporter that reads a variable's value."""

    return Reporter(
        opcode="data_variable",
        fields={"VARIABLE": Field(name="VARIABLE", value=variable)},
    )


# ── List commands ─────────────────────────────────────────────────────────


def add_to_list(list_: str, item: int | float | str | Reporter) -> StackExpr:
    """``data_addtolist``."""

    ins, shadows = _resolve_inputs({"ITEM": item})
    return StackExpr(
        opcode="data_addtolist",
        inputs=ins,
        fields={"LIST": Field(name="LIST", value=list_, variable_type="list")},
        shadow_reporters=shadows,
    )


def delete_of_list(list_: str, index: int | float | Reporter = 1) -> StackExpr:
    """``data_deleteoflist`` — delete *index* (1-based, "last", "all")."""

    ins, shadows = _resolve_inputs({"INDEX": index})
    return StackExpr(
        opcode="data_deleteoflist",
        inputs=ins,
        fields={"LIST": Field(name="LIST", value=list_, variable_type="list")},
        shadow_reporters=shadows,
    )


def insert_at_list(list_: str, item: int | float | str | Reporter, index: int | float | Reporter = 1) -> StackExpr:
    """``data_insertatlist``."""

    ins, shadows = _resolve_inputs({"ITEM": item, "INDEX": index})
    return StackExpr(
        opcode="data_insertatlist",
        inputs=ins,
        fields={"LIST": Field(name="LIST", value=list_, variable_type="list")},
        shadow_reporters=shadows,
    )


def replace_item_of_list(list_: str, index: int | float | Reporter, item: int | float | str | Reporter) -> StackExpr:
    """``data_replaceitemoflist``."""

    ins, shadows = _resolve_inputs({"INDEX": index, "ITEM": item})
    return StackExpr(
        opcode="data_replaceitemoflist",
        inputs=ins,
        fields={"LIST": Field(name="LIST", value=list_, variable_type="list")},
        shadow_reporters=shadows,
    )


# ── List reporters ────────────────────────────────────────────────────────


def item_of_list(list_: str, index: int | float | Reporter = 1) -> Reporter:
    """``data_itemoflist`` — reporter."""

    ins, shadows = _resolve_inputs({"INDEX": index})
    return Reporter(
        opcode="data_itemoflist",
        inputs=ins,
        fields={"LIST": Field(name="LIST", value=list_, variable_type="list")},
        shadow_reporters=shadows,
    )


def length_of_list(list_: str) -> Reporter:
    """``data_lengthoflist`` — reporter."""

    return Reporter(
        opcode="data_lengthoflist",
        fields={"LIST": Field(name="LIST", value=list_, variable_type="list")},
    )


def list_contains_item(list_: str, item: int | float | str | Reporter) -> Reporter:
    """``data_listcontainsitem`` — boolean reporter."""

    ins, shadows = _resolve_inputs({"ITEM": item})
    return Reporter(
        opcode="data_listcontainsitem",
        inputs=ins,
        fields={"LIST": Field(name="LIST", value=list_, variable_type="list")},
        shadow_reporters=shadows,
    )
