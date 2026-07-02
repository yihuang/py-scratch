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


## DSL Design

The `scratch.dsl` package is a Pythonic block builder that mirrors Scratch block
structure through composable expression objects.  A full reference is at
`docs/dsl-reference.md`.

### Expression tree

Each Scratch block is represented by a single `StackExpr` (command, hat, C-shaped)
or `Reporter` (oval, boolean).  Category modules (`scratch.dsl.motion`,
`scratch.dsl.control`, etc.) provide factory functions that construct these
expression objects with typed parameters::

```python
motion.move(10)                    # StackExpr for motion_movesteps
operators.add(x_position(), 5)     # Reporter for operator_add
```

C-shaped blocks use ``__call__`` to attach their body, and ``.else_()`` for
the false branch of ``if_else``::

```python
control.repeat(10)(motion.move(5))          # repeat body
control.if_else(cond)(say("a")).else_(move(-10))  # if-else
```

### Builder

``chain()`` links a list of ``StackExpr`` into a flat ``target.blocks`` dict.
``Script.build()`` does the same for a hat + body pair.  Both register reporter
blocks referenced from inputs and resolve variable field IDs.

### Project

``Project`` wraps the full lifecycle: it manages targets (stage + sprites),
turns DSL expressions into a ``Runtime`` via ``build_runtime()``, and serializes
to an ``.sb3`` file via ``save()``.  Placeholder costumes with valid PNG data
are auto-generated for targets that lack them, ensuring the .sb3 is importable
by the Scratch editor.

### Schema compliance

The DSL enforces the Scratch SB3 schema constraints documented in
``docs/vm-reference.md`` under *SB3 Validation Constraints*:
literal values use compact primitives, reporter parents are linked, and variable
field IDs are resolved on all blocks including reporters.
