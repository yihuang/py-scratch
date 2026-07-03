"""
Procedures (My Blocks) category.
"""

from __future__ import annotations

import json
import uuid

from scratch.vm.types import Input, Mutation

from .expr import StackExpr


def call(proc_name: str, *args: object) -> StackExpr:
    """``procedures_call`` — call a custom block.

    Usage::

        procedures.call("my_block %n", 42)

    *proc_name* is the proccode (e.g. ``"my_block %n"``).
    Additional positional arguments are passed as block inputs, one per
    ``%`` placeholder in the proccode.
    """
    arg_count = proc_name.count('%')
    arg_ids = [uuid.uuid4().hex[:8] for _ in range(arg_count)]

    inputs: dict[str, Input] = {}
    reported_shadows: dict[str, object] = {}
    for i, (arg_id, arg_val) in enumerate(zip(arg_ids, args)):
        if hasattr(arg_val, '_ensure_id'):  # Reporter
            reporter = arg_val
            rid = reporter._ensure_id()
            inputs[arg_id] = Input(value=rid)
            reported_shadows[arg_id] = reporter
        else:
            inputs[arg_id] = Input(value=arg_val)

    mutation = Mutation(
        proccode=proc_name,
        argumentids=json.dumps(arg_ids),
        argumentnames=json.dumps([''] * arg_count),
        argumentdefaults=json.dumps([0] * arg_count),
    )

    return StackExpr(
        opcode='procedures_call',
        inputs=inputs,
        mutation=mutation,
        shadow_reporters=reported_shadows,  # type: ignore[arg-type]
    )
