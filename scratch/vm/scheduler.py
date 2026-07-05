"""
Scheduler — a reusable, generator-based cooperative multitasking scheduler.

The scheduler manages **thread** objects (subclasses of :class:`SchedulerThread`)
and a **Clock**.  It knows nothing about Scratch blocks, opcodes, or targets.

Usage::

    from scheduler import Scheduler, SchedulerThread

    class MyThread(SchedulerThread):
        ...

    sched = Scheduler()
    t = MyThread(target=...)
    t.start()
    sched.resume(t)

    def step_one(thread: SchedulerThread) -> None:
        ...  # advance thread by one instruction

    while sched.count() > 0:
        sched.step(step_one)
"""

from __future__ import annotations

import heapq
import math
import time
from typing import Any


# ── ThreadStatus ─────────────────────────────────────────────────────────


class ThreadStatus:
    """Possible states for a thread managed by the scheduler."""

    RUNNING = 'running'
    WAITING = 'waiting'
    DONE = 'done'


# ── SchedulerThread (base class) ─────────────────────────────────────────


class SchedulerThread:
    """Minimal thread interface required by the :class:`Scheduler`.

    Subclasses must provide:

    * ``status`` — one of ``ThreadStatus.*`` (default ``RUNNING``).
    * ``target`` — an arbitrary object used for filtering.
    * ``is_done()`` — returns ``True`` when the thread has finished.
    """

    status: str = ThreadStatus.RUNNING

    def is_done(self) -> bool:
        return self.status == ThreadStatus.DONE


# ── Clock ────────────────────────────────────────────────────────────────


class Clock:
    """Virtual 60 fps clock.  Each ``tick()`` call advances by one frame."""

    FPS = 60

    def __init__(self) -> None:
        self._tick: int = 0

    def now(self) -> float:
        """Virtual time in seconds since start."""
        return self._tick / self.FPS

    def tick(self) -> None:
        """Advance one frame."""
        self._tick += 1

    def frames_for(self, seconds: float) -> int:
        """Number of ticks needed to cover *seconds*."""
        return max(1, math.ceil(seconds * self.FPS))

    def reset(self) -> None:
        self._tick = 0


# ── Scheduler ────────────────────────────────────────────────────────────


class Scheduler:
    """A cooperative multitasking scheduler.

    Manages a pool of :class:`SchedulerThread` objects, advancing each one
    by one instruction per call to :meth:`step`.

    The scheduler delegates the actual instruction execution to a
    user-provided ``step_one`` callback, making it agnostic about what
    a "step" means.

    Parameters
    ----------
    real_time:
        If True (default), waiting threads use ``time.monotonic()`` for
        wake-up times.  If False, the virtual :class:`Clock` is used.
    time_module:
        Module to use for time queries (dependency injection for tests).
        Defaults to the stdlib ``time`` module.
    """

    def __init__(self, *, real_time: bool = True, time_module: Any = None) -> None:
        self._runnable_queue: list[SchedulerThread] = []
        self._wait_queue: list[tuple[float, int, SchedulerThread]] = []
        self._wait_seq = 0
        self.clock = Clock()
        self._real_time = real_time
        self._time = time_module or time

    # ── Query ────────────────────────────────────────────────────────

    @property
    def threads(self) -> list[SchedulerThread]:
        """All alive threads: runnable + waiting (read-only view)."""
        waiting = [t for _, _, t in self._wait_queue]
        return self._runnable_queue + waiting

    def count(self) -> int:
        """Total number of alive threads."""
        return len(self._runnable_queue) + len(self._wait_queue)

    # ── Lifecycle ────────────────────────────────────────────────────

    def resume(self, thread: SchedulerThread) -> None:
        """Add *thread* to the runnable queue."""
        thread.status = ThreadStatus.RUNNING
        self._runnable_queue.append(thread)

    def schedule_wake(self, thread: SchedulerThread, delay: float) -> None:
        """Put *thread* to sleep for *delay* seconds.

        The thread will be woken up after *delay* seconds (real or
        virtual, depending on ``real_time``).
        """
        thread.status = ThreadStatus.WAITING
        if self._real_time and delay > 0:
            wake_at = self._time.monotonic() + delay
        else:
            wake_at = self.clock._tick + self.clock.frames_for(delay)
        seq = self._wait_seq
        self._wait_seq += 1
        heapq.heappush(self._wait_queue, (wake_at, seq, thread))

    def stop_all(self) -> None:
        """Mark every alive thread as done."""
        for t in self.threads:
            t.status = ThreadStatus.DONE

    def remove_threads_for(self, target: Any) -> None:
        """Remove all threads belonging to *target*."""
        self._runnable_queue[:] = [
            t for t in self._runnable_queue if getattr(t, 'target', None) is not target
        ]
        self._wait_queue[:] = [
            e for e in self._wait_queue if getattr(e[2], 'target', None) is not target
        ]

    def clear(self) -> None:
        """Remove all threads."""
        self._runnable_queue.clear()
        self._wait_queue.clear()

    # ── Execution ────────────────────────────────────────────────────

    # ── Template method ─────────────────────────────────────────────

    def _step_thread(self, thread: SchedulerThread) -> None:
        """Advance *thread* by one instruction.

        Override in subclasses to define instruction execution.
        The default implementation does nothing, so threads run
        forever without making progress — subclasses must provide
        a real implementation.

        Implementations must update ``thread.status`` to one of:
        ``ThreadStatus.RUNNING`` (still has work) or
        ``ThreadStatus.WAITING`` (paused) or
        ``ThreadStatus.DONE`` (finished).
        """
        # Default: subclasses must override.

    def step(self) -> None:
        """Run one tick of the scheduler.

        1. Wake any waiting threads whose timer has expired.
        2. Advance each runnable thread by one instruction via
           :meth:`_step_thread`.
        3. Tick the virtual clock.
        """
        now = self._time.monotonic() if self._real_time else self.clock._tick

        # 1. Wake threads whose wait has expired
        while self._wait_queue and self._wait_queue[0][0] <= now:
            _, _, thread = heapq.heappop(self._wait_queue)
            if thread.status == ThreadStatus.WAITING:
                thread.status = ThreadStatus.RUNNING
                self._runnable_queue.append(thread)

        # 2. Step each runnable thread once
        still_runnable: list[SchedulerThread] = []
        for thread in self._runnable_queue:
            if thread.is_done():
                continue
            self._step_thread(thread)
            if thread.status == ThreadStatus.RUNNING:
                still_runnable.append(thread)
        self._runnable_queue[:] = still_runnable

        # 3. Advance the clock
        self.clock.tick()
