"""
Core expression types for the Scratch DSL.

Defines the base protocols: Expr, StackExpr (command / C-shaped), Reporter.
"""

from __future__ import annotations

import uuid
from typing import Any

from scratch.vm.types import Block, Field, Input, Mutation


class Expr:
    """Base class for any block expression."""

    def __init__(self) -> None:
        self.block_id: str = ''
        self.opcode: str = ''
        self.inputs: dict[str, Input] = {}
        self.fields: dict[str, Field] = {}
        # Track Reporter objects used as inputs so we can walk the tree.
        # Maps input name → Reporter for inputs that are blocks.
        self._shadow_reporters: dict[str, Reporter] = {}

    def _ensure_id(self) -> str:
        if not self.block_id:
            self.block_id = uuid.uuid4().hex[:8]
        return self.block_id


class StackExpr(Expr):
    """A command / stack block.

    C-shaped blocks (repeat, forever, if_) override ``__call__`` to attach
    a substack body. ``else_()`` attaches the false branch for ``if_else``.
    """

    def __init__(
        self,
        opcode: str = '',
        inputs: dict[str, Input] | None = None,
        fields: dict[str, Field] | None = None,
        shadow_reporters: dict[str, Reporter] | None = None,
        mutation: Mutation | None = None,
    ) -> None:
        super().__init__()
        self.opcode = opcode
        self.inputs = inputs or {}
        self.fields = fields or {}
        self._shadow_reporters = shadow_reporters or {}
        self._mutation = mutation
        self._body: list[StackExpr] | None = None
        self._body2: list[StackExpr] | None = None

    def __call__(self, *body: StackExpr) -> StackExpr:
        """Attach a substack (body) to this C-shaped block.

        The positional args become the SUBSTACK chain.
        Returns self for chaining (e.g. .else_()).
        """
        self._body = list(body)
        return self

    def else_(self, *body: StackExpr) -> StackExpr:
        """Attach the else branch (SUBSTACK2) for if_else."""
        self._body2 = list(body)
        return self

    def as_block(self) -> Block:
        """Build a scratch.vm.types.Block from this expression."""
        self._ensure_id()
        return Block(
            id=self.block_id,
            opcode=self.opcode,
            inputs=dict(self.inputs),
            fields=dict(self.fields),
            mutation=self._mutation,
        )


class Reporter(Expr):
    """A reporter (oval) or boolean (hex) block. Produces a value.

    ``as_input()`` returns the block ID (str) that another block's input
    references. The block is registered in the owner's block tree during
    the build phase.
    """

    def __init__(
        self,
        opcode: str = '',
        inputs: dict[str, Input] | None = None,
        fields: dict[str, Field] | None = None,
        shadow_reporters: dict[str, Reporter] | None = None,
        shadow: bool = False,
    ) -> None:
        super().__init__()
        self.opcode = opcode
        self.inputs = inputs or {}
        self.fields = fields or {}
        self._shadow_reporters = shadow_reporters or {}
        self._shadow = shadow

    def as_input(self) -> str:
        """Return this reporter's block ID for use as an input reference."""
        return self._ensure_id()

    def as_block(self) -> Block:
        """Build a scratch.vm.types.Block from this reporter expression."""
        self._ensure_id()
        return Block(
            id=self.block_id,
            opcode=self.opcode,
            inputs=dict(self.inputs),
            fields=dict(self.fields),
            shadow=self._shadow,
        )


# ── Input resolution helper ──────────────────────────────────────────────


# Primitive type codes used by Scratch compact primitives.
# See ``docs/sb3-serialization.md`` for the full list.
NUMBER = 4  # number value
POSITIVE_NUMBER = 5  # positive number value (e.g. wait duration)
WHOLE_NUMBER = 6  # whole number value (e.g. repeat count)
INTEGER = 7  # integer value
ANGLE = 8  # angle value
TEXT = 10  # text/string value


def _resolve_inputs(
    kwargs: dict[str, Any],
    types: dict[str, int] | None = None,
) -> tuple[dict[str, Input], dict[str, Reporter]]:
    """Convert ``{Scratch_input_name: literal_or_reporter}`` → ``{name: Input}``.

    ``types`` optionally maps input names to Scratch compact-primitive type
    codes (e.g. ``POSITIVE_NUMBER``, ``WHOLE_NUMBER``).  When a literal is
    provided for a typed input, the value is wrapped as a compact primitive
    of that type for correct serialization.

    Returns (inputs, shadow_reporters) where shadow_reporters maps input names
    to Reporter objects for block-referenced inputs.
    """
    types = types or {}
    inputs: dict[str, Input] = {}
    shadows: dict[str, Reporter] = {}
    for name, val in kwargs.items():
        if isinstance(val, Reporter):
            # Inline variable references as OBSOLETE_FLAG with VARIABLE primitive
            # instead of creating a separate data_variable block.
            if val.opcode == 'data_variable':
                var_name = str(val.fields.get('VARIABLE', Field(value='')).value)
                inputs[name] = Input(value=None, variable_name=var_name)
            else:
                inputs[name] = Input(value=val.as_input())
                shadows[name] = val
        else:
            type_code = types.get(name)
            if type_code is not None:
                inputs[name] = Input(value=[type_code, str(val)], shadow=True, is_literal=False)
            else:
                inputs[name] = Input(value=val, is_literal=True)
    return inputs, shadows
