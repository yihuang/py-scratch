"""
Procedures (My Blocks) category.
"""

from __future__ import annotations

import json

from scratch.vm.types import Field, Input, Mutation

from .expr import Reporter, StackExpr


def define(proc_name: str, *param_names: str) -> StackExpr:
    """``procedures_definition`` — define a custom block (My Block).

    Usage::

        procedures.define("my_block %n", "param1")(
            motion.move(10),
        )

    *proc_name* is the proccode (e.g. ``"my_block %n"``).
    Extra positional args are parameter names, one per ``%`` placeholder.
    """
    arg_count = proc_name.count("%")
    # Pad param_names if fewer provided than placeholders
    padded_names = list(param_names) + [""] * (arg_count - len(param_names))
    # Use sequential indices as arg IDs so they are consistent between
    # definitions and calls regardless of parameter naming.
    arg_ids = [str(i) for i in range(arg_count)]

    mutation = Mutation(
        proccode=proc_name,
        argumentids=json.dumps(arg_ids),
        argumentnames=json.dumps(padded_names),
        argumentdefaults=json.dumps([0] * arg_count),
        warp="false",
    )

    return StackExpr(
        opcode="procedures_definition",
        mutation=mutation,
    )


def arg(param_name: str, *, shadow: bool = False) -> Reporter:
    """``argument_reporter_string_number`` — reference a procedure argument.

    Usage within a custom block body::

        def my_block(procedures: procedures):  # in scope
            ...
            data.set_variable("score", procedures.arg("param_name")),
            ...

    Args:
        param_name: The parameter name as declared in ``define()``.
        shadow: Whether the reporter is a shadow block.  ``False`` matches
            the official Scratch format for argument reporters in procedure
            bodies.
    """
    return Reporter(
        opcode="argument_reporter_string_number",
        fields={"VALUE": Field(value=param_name)},
        shadow=shadow,
    )


def call(proc_name: str, *args: object) -> StackExpr:
    """``procedures_call`` — call a custom block.

    Usage::

        procedures.call("my_block %n", 42)

    *proc_name* is the proccode (e.g. ``"my_block %n"``).
    Additional positional arguments are passed as block inputs, one per
    ``%`` placeholder in the proccode.
    """
    arg_count = proc_name.count("%")
    # Use parameter-index-based arg IDs matching ``define()``.
    # Without param names, the call can't know the definition's IDs,
    # so we rely on positional matching via ``argumentnames/argumentdefaults``.
    # The IDs are positional indices ("0", "1", ...) — consistent if the
    # same procedure is always called with the same count of placeholders.
    arg_ids = [str(i) for i in range(arg_count)]

    inputs: dict[str, Input] = {}
    reported_shadows: dict[str, object] = {}
    for i, (arg_id, arg_val) in enumerate(zip(arg_ids, args)):
        if hasattr(arg_val, "_ensure_id"):  # Reporter
            reporter = arg_val
            rid = reporter._ensure_id()
            inputs[arg_id] = Input(value=rid)
            reported_shadows[arg_id] = reporter
        else:
            # Procedure call inputs use SHADOW_FLAG (1) with TEXT/compact
            # primitives.  Numbers are stored as strings, e.g. [10, "50"].
            val_str = str(arg_val)
            inputs[arg_id] = Input(value=[10, val_str], shadow=True, is_literal=False)

    mutation = Mutation(
        proccode=proc_name,
        argumentids=json.dumps(arg_ids),
        argumentnames=json.dumps([""] * arg_count),
        argumentdefaults=json.dumps([0] * arg_count),
    )

    return StackExpr(
        opcode="procedures_call",
        inputs=inputs,
        mutation=mutation,
        shadow_reporters=reported_shadows,  # type: ignore[arg-type]
    )
