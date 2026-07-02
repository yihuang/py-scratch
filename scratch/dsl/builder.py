"""
Builder — converts the DSL expression tree into a flat ``target.blocks`` dict.

Key functions
-------------
* ``chain(exprs, parent_id, var_map)`` — link a list of ``StackExpr`` into a
  sequential block chain, returning ``(blocks_dict, entry_id, exit_id)``.
* ``Script.build(target)`` — fully populate a target's blocks from a hat +
  body pair.
"""

from __future__ import annotations

from scratch.vm.target import Target
from scratch.vm.types import Block, Field, Input
from .expr import Reporter, StackExpr


def _register_reporters(
    blocks: dict[str, Block],
    root: StackExpr | Reporter,
    visited: set[str],
) -> None:
    """Recursively register reporter blocks referenced in ``root._shadow_reporters``."""
    for reporter in root._shadow_reporters.values():
        rid = reporter._ensure_id()
        if rid not in visited:
            visited.add(rid)
            blocks[rid] = reporter.as_block()
            _register_reporters(blocks, reporter, visited)


def _chain_impl(
    exprs: list[StackExpr],
    parent_id: str | None,
    var_map: dict[str, str] | None,
    reporter_visited: set[str],
) -> tuple[dict[str, Block], str | None, str | None]:
    """Internal recursive chain implementation with shared visited tracking."""
    if not exprs:
        return {}, None, None

    blocks: dict[str, Block] = {}
    chain_ids: list[str] = []

    for expr in exprs:
        bid = expr._ensure_id()
        chain_ids.append(bid)

        block = expr.as_block()
        blocks[bid] = block

        # Resolve variable fields if var_map is provided
        if var_map:
            for field_name in list(block.fields.keys()):
                field = block.fields[field_name]
                if isinstance(field, Field) and field.name == 'VARIABLE':
                    mapped = var_map.get(str(field.value))
                    if mapped:
                        field.id = mapped

        # Register reporter blocks from shadow reporters (shared visited)
        _register_reporters(blocks, expr, reporter_visited)

        # Handle SUBSTACK (body)
        if expr._body:
            sub_blocks, sub_entry, _ = _chain_impl(
                expr._body,
                parent_id=bid,
                var_map=var_map,
                reporter_visited=reporter_visited,
            )
            blocks.update(sub_blocks)
            if sub_entry:
                block.inputs['SUBSTACK'] = Input(name='SUBSTACK', value=sub_entry)

        # Handle SUBSTACK2 (else branch)
        if expr._body2:
            sub2_blocks, sub2_entry, _ = _chain_impl(
                expr._body2,
                parent_id=bid,
                var_map=var_map,
                reporter_visited=reporter_visited,
            )
            blocks.update(sub2_blocks)
            if sub2_entry:
                block.inputs['SUBSTACK2'] = Input(name='SUBSTACK2', value=sub2_entry)

    # Link sequential chain (next pointers)
    for i in range(len(chain_ids) - 1):
        curr_id = chain_ids[i]
        next_id = chain_ids[i + 1]
        blocks[curr_id].next = next_id
        blocks[next_id].parent = curr_id

    # Apply parent_id to the first block in the chain
    if parent_id and chain_ids:
        blocks[chain_ids[0]].parent = parent_id

    # Post-process: set parent on reporter blocks referenced by inputs
    _resolve_input_parents(blocks)

    # Post-process: resolve variable fields on all blocks (incl. reporters)
    if var_map:
        _resolve_variable_fields(blocks, var_map)

    entry_id = chain_ids[0] if chain_ids else None
    exit_id = chain_ids[-1] if chain_ids else None

    return blocks, entry_id, exit_id


def _resolve_input_parents(blocks: dict[str, Block]) -> None:
    """Set parent on blocks referenced by other blocks' inputs.

    When block A has inputs={'X': [2, 'blockB_id']}, block B's parent
    should be A.  Required for valid Scratch JSON.
    """
    for bid, block in blocks.items():
        for inp in block.inputs.values():
            val = inp.value
            if isinstance(val, str) and val in blocks:
                child = blocks[val]
                if child.parent is None:
                    child.parent = bid


def _resolve_variable_fields(
    blocks: dict[str, Block], var_map: dict[str, str]
) -> None:
    """Resolve VARIABLE field id for all blocks, including reporters."""
    for block in blocks.values():
        for field in block.fields.values():
            if isinstance(field, Field) and field.name == 'VARIABLE':
                mapped = var_map.get(str(field.value))
                if mapped and field.id is None:
                    field.id = mapped
def chain(
    exprs: list[StackExpr],
    parent_id: str | None = None,
    var_map: dict[str, str] | None = None,
) -> tuple[dict[str, Block], str | None, str | None]:
    """Link a list of StackExpr into a sequential chain.

    Parameters
    ----------
    exprs : list[StackExpr]
        Commands to chain in order.
    parent_id : str, optional
        Block ID of the parent (e.g. the hat block that this chain follows).
    var_map : dict[str, str], optional
        Mapping of variable names → UUIDs for field resolution.

    Returns
    -------
    (blocks_dict, entry_id, exit_id)
        * entry_id — first block's ID (for hat.next or SUBSTACK reference)
        * exit_id — last block's ID (for linking the next chain element)
        * blocks_dict — all blocks in the chain, recursively including
          substacks and referenced reporters.
    """
    return _chain_impl(exprs, parent_id, var_map, set())


# ── Script ────────────────────────────────────────────────────────────────


class Script:
    """A hat block + body pair ready to build onto a Target."""

    def __init__(
        self,
        hat: StackExpr,
        body: list[StackExpr] | None = None,
        var_map: dict[str, str] | None = None,
    ) -> None:
        self.hat = hat
        self.body = body or []
        self.var_map = var_map or {}

    def build(self, target: Target) -> None:
        """Populate ``target.blocks`` with the full block tree."""
        visited: set[str] = set()

        hat_block = self.hat.as_block()
        hat_id = self.hat._ensure_id()

        hat_block.top_level = True
        hat_block.parent = None

        # Register reporter blocks from the hat itself
        _register_reporters(target.blocks, self.hat, visited)

        # Chain the body
        body_blocks, entry_id, _ = _chain_impl(
            self.body,
            parent_id=hat_id,
            var_map=self.var_map,
            reporter_visited=visited,
        )

        hat_block.next = entry_id

        # Assign editor coordinates — stagger vertical positions
        hat_block.x = 0.0
        hat_block.y = 0.0

        # Update target blocks
        target.blocks[hat_id] = hat_block
        target.blocks.update(body_blocks)

        # Post-process: fix reporter parents across all blocks
        _resolve_input_parents(target.blocks)

        # Post-process: resolve variable fields on all blocks (incl. reporters)
        if self.var_map:
            _resolve_variable_fields(target.blocks, self.var_map)

        # Invalidate hat cache so runtime picks up new hats
        target.invalidate_hat_cache()
