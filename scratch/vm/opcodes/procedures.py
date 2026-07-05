"""
Procedure (custom block) opcodes — ``procedures_definition``, ``procedures_call``, etc.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..runtime import Runtime
    from ..target import Target
    from ..types import Block

from ._helpers import _field_val


def procedures_definition(rt: Runtime, tgt: Target, block: Block) -> None:
    """Custom block definition — hat. The body runs normally via next block."""


def procedures_call(rt: Runtime, tgt: Target, block: Block) -> Any:
    """Custom block call — looks up the prototype and runs its body."""
    mutation = getattr(block, 'mutation', None) or getattr(block, '_mutation', None)
    if mutation is None:
        return
    proccode = getattr(mutation, 'proccode', None) or (
        mutation.get('proccode') if isinstance(mutation, dict) else None
    )
    if proccode is None:
        return
    for bid, b in tgt.blocks.items():
        if b.opcode in ('procedures_definition', 'procedures_def'):
            # Mutation may be on the definition block (DSL builder) or
            # on the referenced prototype block (sb3 serialization).
            b_mut = getattr(b, 'mutation', None) or getattr(b, '_mutation', None)
            if b_mut is None:
                # Try reading mutation from the prototype block
                proto_inp = b.inputs.get('custom_block')
                if proto_inp is not None:
                    raw = proto_inp.value
                    # Unpack compact primitive [type_code, block_id] if needed
                    if isinstance(raw, (list, tuple)) and len(raw) >= 2:
                        proto_bid: str | None = str(raw[1])
                    else:
                        proto_bid = str(raw) if raw is not None else None
                    if proto_bid is not None and proto_bid in tgt.blocks:
                        proto = tgt.blocks[proto_bid]
                        b_mut = getattr(proto, 'mutation', None) or getattr(
                            proto, '_mutation', None
                        )
            if b_mut:
                b_proc = getattr(b_mut, 'proccode', None) or (
                    b_mut.get('proccode') if isinstance(b_mut, dict) else None
                )
                if b_proc == proccode:
                    frame = rt.current_thread.peek_frame() if rt.current_thread else None
                    if frame is not None:
                        try:
                            arg_ids = json.loads(mutation.argumentids)
                            arg_names = json.loads(b_mut.argumentnames)
                            try:
                                arg_defaults = json.loads(b_mut.argumentdefaults)
                            except (json.JSONDecodeError, AttributeError, TypeError):
                                arg_defaults = []
                            for i, (arg_id, arg_name) in enumerate(zip(arg_ids, arg_names)):
                                if arg_id in block.inputs:
                                    frame.params[arg_name] = rt.val(tgt, block, arg_id)
                                else:
                                    default = arg_defaults[i] if i < len(arg_defaults) else ''
                                    frame.params[arg_name] = default
                        except (json.JSONDecodeError, AttributeError, TypeError, KeyError):
                            pass
                    yield from rt.execute_substack(tgt, b.next)
                    return


def _get_param(rt: Runtime, arg_name: str) -> Any:
    """Search up the thread's entire stack for a procedure parameter.

    Mirrors the official VM's ``getParam``, which walks from the top
    of the stack downwards to find the nearest enclosing procedure
    call that defines *arg_name*.
    """
    thread = rt.current_thread
    if thread is None:
        return None
    for i in range(len(thread.stack) - 1, -1, -1):
        frame = thread.stack[i]
        if arg_name in frame.params:
            return frame.params[arg_name]
    return None


def argument_reporter_string_number(rt: Runtime, tgt: Target, block: Block) -> Any:
    """Return the value of a custom block argument (string or number)."""
    arg_name = _field_val(block.fields.get('VALUE')) if block.fields.get('VALUE') else ''
    if arg_name:
        val = _get_param(rt, arg_name)
        if val is not None:
            return val
    return 0


def argument_reporter_boolean(rt: Runtime, tgt: Target, block: Block) -> Any:
    """Return the value of a custom block argument (boolean)."""
    arg_name = _field_val(block.fields.get('VALUE')) if block.fields.get('VALUE') else ''
    if arg_name:
        val = _get_param(rt, arg_name)
        if val is not None:
            return val
    return 0
