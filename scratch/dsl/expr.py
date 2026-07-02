"""
Core expression types for the Scratch DSL.

Defines the base protocols: Expr, StackExpr (command / C-shaped), Reporter.
"""

from __future__ import annotations

import uuid
from typing import Any

from scratch.vm.types import Block, Field, Input


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
    ) -> None:
        super().__init__()
        self.opcode = opcode
        self.inputs = inputs or {}
        self.fields = fields or {}
        self._shadow_reporters = shadow_reporters or {}
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
    ) -> None:
        super().__init__()
        self.opcode = opcode
        self.inputs = inputs or {}
        self.fields = fields or {}
        self._shadow_reporters = shadow_reporters or {}

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
            shadow=True,
        )


# ── Input resolution helper ──────────────────────────────────────────────


def _resolve_inputs(kwargs: dict[str, Any]) -> tuple[dict[str, Input], dict[str, Reporter]]:
    """Convert ``{Scratch_input_name: literal_or_reporter}`` → ``{name: Input}``.

    Returns (inputs, shadow_reporters) where shadow_reporters maps input names
    to Reporter objects for block-referenced inputs.
    """
    inputs: dict[str, Input] = {}
    shadows: dict[str, Reporter] = {}
    for name, val in kwargs.items():
        if isinstance(val, Reporter):
            inputs[name] = Input(name=name, value=val.as_input())
            shadows[name] = val
        else:
            inputs[name] = Input(name=name, value=val)
    return inputs, shadows
