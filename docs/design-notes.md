# Design Notes

## Thread Model

```
RUNNING ──→ WAITING ─→ RUNNING  (resumed when timer expires)
RUNNING ──→ DONE               (generator exhausted / stack empty)
```

| State | Meaning | Transition out |
|---|---|---|
| `RUNNING` | Ready to execute one step | `_step_thread` processes the block handler |
| `WAITING` | Paused for a timer (`wait_yield`) | Set back to `RUNNING` when `clock.now() >= waiting_until` |
| `DONE` | Finished | Removed from the thread list by the sweep at the end of each `step()` |

| Yield value | Meaning |
|---|---|
| `YIELD` | Pause this thread; resume next tick |
| `Wait(secs)` | Park thread until wall-clock time elapses |
| `Report(value)` | Reporter block returns a value to its parent |
| `StopIteration` (generator exit) | Handler finished; advance to next block |

A thread in `RUNNING` that yields `YIELD` stays `RUNNING` — the generator is simply resumed by `next(gen)` on the next call to `step()`. There is no separate `YIELD` state; the per-frame guarantee (each thread is stepped at most once per `step()`) makes it unnecessary.

### Execution per thread

Each thread has a **stack of frames**. A frame holds:

- `block_id` — the block being executed
- `gen` — the handler's active generator (or `None` if not yet started, or `None` for instant blocks)
- `result` / `saved` — used by reporter blocks and control flow

`_step_thread` drives one thread forward by one "instruction":

1. **Instant block** (non-generator handler, returns `None`): advance to the next block immediately via `_advance_to_next`.
2. **Generator block**: call `next(frame.gen)` to resume the handler:
   - `StopIteration` → handler finished → advance to next block.
   - `YIELD` → suspend thread; resume next frame.
   - `Wait(secs)` → suspend thread; resume after `secs` seconds by wall clock.
   - `Report(value)` → reporter block result; pop frame, deliver value to parent.

### Block chaining

Scratch blocks form a linked list via `block.next`. `_advance_to_next` moves the thread to the next block:

- If `block.next` is set, the frame's `block_id` and `gen` are replaced (the thread stays at the same stack depth).
- If `block.next` is `None`, the frame is popped. If the stack becomes empty, the thread is marked `DONE`.

### Control blocks

Control blocks (`repeat`, `forever`, `if`, etc.) don't rely on `_advance_to_next` for their sub-stack. Instead, their handler generators delegate to `execute_substack`, a compound generator that steps through a linked block chain:

```python
yield from rt.execute_substack(tgt, substack.value)
```

`execute_substack` handles both instant and generator blocks internally, yielding any control signals to the outer generator. This means the parent generator (`repeat`, `forever`) can insert `yield YIELD` between iterations without `_advance_to_next` interfering.

### Forever loops

`control_forever` is an infinite generator that:
1. Runs the sub-stack via `yield from execute_substack(...)`
2. Yields `YIELD` to let other threads run
3. Loops

The generator never raises `StopIteration`. The thread stays alive until `green_flag()` forcibly kills it.

### Green flag lifecycle

`green_flag()`:
1. Marks all existing threads as `DONE`
2. Clears the thread list
3. Starts new threads for every `event_whenflagclicked` hat block (starting from the block *after* the hat)

This matches Scratch semantics: pressing the green flag stops all running scripts before starting fresh ones.

### Thread list cleanup

At the end of each `step()`, a sweep removes all `DONE` threads:

```python
self.threads[:] = [t for t in self.threads if not t.is_done()]
```

This is the only place threads are removed (besides `green_flag()` which clears the list explicitly).

## Why generators?

**89 opcode handlers** implemented across Control, Events, Motion, Looks, Operators, Data, Sensing, and Pen.
Each opcode handler is a Python generator function. This gives us:

- **Cooperative concurrency** — handlers voluntarily yield control by yielding `YIELD` or `wait_yield`. No preemption needed.
- **Natural control flow** — loops (`repeat`, `forever`) are actual Python loops inside the generator. No need for a separate instruction pointer or continuation-passing style.
- **Zero-copy input resolution** — reporter blocks yield `Report(value)` which pops back up the stack naturally.
- **Deterministic stepping** — each `step()` call advances each thread by exactly one generator `.next()`. The thread list is stable within a single frame.
