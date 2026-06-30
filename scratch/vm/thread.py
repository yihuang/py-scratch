"""
Thread — one execution of a Scratch script.

Each thread is a lightweight coroutine-based execution context. Instead of
storing raw generators, the thread maintains a stack of **Frames** where each
frame represents a block currently being executed. The sequencer advances the
thread by stepping the topmost frame.
"""

from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .types import Block

if TYPE_CHECKING:
    from .target import Target


# ── Yield protocol constants ────────────────────────────────────────────

# A block handler is a generator that yields one of these values:
#   YieldPass() — yield control; reschedule next tick.
#   Wait(secs)  — pause thread for secs.
#   Report(val) — reporter block returning a value to its parent.


class YieldPass:
    """Yield control; reschedule next tick."""


YIELD = YieldPass()

@dataclass(frozen=True)
class Wait:
    """Pause thread for ``seconds``."""
    seconds: float


@dataclass(frozen=True)
class Report:
    """Reporter block returning a ``value`` to the parent frame."""
    value: Any


# ── Status ──────────────────────────────────────────────────────────────


class ThreadStatus:
    RUNNING = 'running'
    WAITING = 'waiting'
    DONE = 'done'


# ── Frame ───────────────────────────────────────────────────────────────

# A Frame holds:
#   block_id  — the block currently being executed
#   gen       — the generator for this block's handler (or None)
#   status    — 'active' | 'paused'
#   result    — the reporter result (if this is a reporter evaluation)


@dataclass
class Frame:
    block_id: str
    gen: Generator[Any] | None = None
    status: str = 'active'  # 'active' | 'paused'
    result: Any = None
    # For control blocks (repeat etc.): sub-stack position
    substack_pc: int = 0
    # Loop count, iteration state, etc.
    loop_count: int = 0
    saved: dict[str, Any] = field(default_factory=dict)


# ── Thread ──────────────────────────────────────────────────────────────


@dataclass
class Thread:
    """One thread of execution.

    The thread holds a stack of frames. Each frame is a block being stepped.
    The ``target`` is the sprite or stage this thread runs on.
    """

    target: Target
    top_block: str  # block ID of the first block
    status: str = ThreadStatus.RUNNING
    stack: list[Frame] = field(default_factory=list)
    at_top: bool = True  # True after a fresh start

    def push_frame(self, block_id: str) -> Frame:
        """Push a new frame onto the stack and return it."""
        f = Frame(block_id=block_id)
        self.stack.append(f)
        return f

    def peek_frame(self) -> Frame | None:
        """Return the top frame, or None."""
        if self.stack:
            return self.stack[-1]
        return None

    def pop_frame(self) -> Frame | None:
        """Pop the top frame."""
        if self.stack:
            return self.stack.pop()
        return None

    @property
    def current_block(self) -> Block | None:
        """The block at the top frame, or None."""
        f = self.peek_frame()
        if f is None:
            return None
        return self.target.blocks.get(f.block_id)

    def is_runnable(self) -> bool:
        return self.status == ThreadStatus.RUNNING

    def is_done(self) -> bool:
        return self.status == ThreadStatus.DONE

    def start(self) -> None:
        """Initialise the thread stack with the top block."""
        self.stack.clear()
        self.push_frame(self.top_block)
        self.status = ThreadStatus.RUNNING

    def __repr__(self) -> str:
        return f'Thread(target={self.target.name}, top={self.top_block}, status={self.status})'
