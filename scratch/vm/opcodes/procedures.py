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

from . import _field_val


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
            b_mut = getattr(b, 'mutation', None) or getattr(b, '_mutation', None)
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
                                    frame.saved[arg_name] = rt.val(tgt, block, arg_id)
                                else:
                                    default = arg_defaults[i] if i < len(arg_defaults) else ''
                                    frame.saved[arg_name] = default
                        except (json.JSONDecodeError, AttributeError, TypeError, KeyError):
                            pass
                    yield from rt.execute_substack(tgt, b.next)
                    return


def argument_reporter_string_number(rt: Runtime, tgt: Target, block: Block) -> Any:
    """Return the value of a custom block argument (string or number)."""
    arg_name = _field_val(block.fields.get('VALUE')) if block.fields.get('VALUE') else ''
    if arg_name:
        frame = rt.current_thread.peek_frame() if rt.current_thread else None
        if frame is not None and arg_name in frame.saved:
            return frame.saved[arg_name]
    return 0


def argument_reporter_boolean(rt: Runtime, tgt: Target, block: Block) -> Any:
    """Return the value of a custom block argument (boolean)."""
    arg_name = _field_val(block.fields.get('VALUE')) if block.fields.get('VALUE') else ''
    if arg_name:
        frame = rt.current_thread.peek_frame() if rt.current_thread else None
        if frame is not None and arg_name in frame.saved:
            return frame.saved[arg_name]
    return 0
