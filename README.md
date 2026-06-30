# Scratch VM — Python

Two things in one crate:

- **VM** — reimplementation of the [Scratch 3.0](https://scratch.mit.edu) virtual machine in Python. Loads `.sb3` files and runs them with a Pygame renderer.
- **DSL** (TODO) — a Pythonic DSL that generates `.sb3` project files from code.

```bash
uv run scratch-vm /path/to/project.sb3
```

No args → built-in demo (4 sprites: bouncing ball, orbiting triangle, pen drawer, square).

Press **ESC** to quit.

## Core Scheduler: Generator-Based Cooperative Multitasking

Every opcode handler is a Python **generator**. The runtime advances threads by stepping one generator at a time, round-robin, 60 fps. No preemption, no OS threads, no async/await — plain `yield` is the control signal.

```
handler → generator → yields → next thread → repeat
```

| Yield value | Meaning |
|---|---|
| `YIELD` (sentinel) | Pause this thread; resume next tick |
| `wait_yield(secs)` | Park thread until wall-clock time elapses |
| `report(value)` | Reporter block returns a value to its parent |
| `return` (generator exit) | Thread completed |

A thread is a stack of **Frames**, each wrapping one block's generator. The sequencer (`runtime._step_thread`) calls `next()` on the topmost frame. Control blocks like `repeat`/`forever` push child frames via `execute_substack()`, so nested loops become a linked walk through frame frames — no recursion, no stack overflow.

Cooperative by design: no handler runs longer than one tick. A `wait` block literally suspends the generator, and `wait until` spins the condition check across ticks.

**89 opcode handlers** implemented across Control, Events, Motion, Looks, Operators, Data, Sensing, and Pen.

## DSL (TODO)

The second half of the project — a Python DSL for building Scratch projects without dragging blocks in a browser.

Think:

```python
project = Project(
    Sprite("Cat", costumes=["cat-a.svg", "cat-b.svg"],
        when_flag_clicked(
            forever(
                next_costume(),
                wait(0.2),
            )
        ),
        when_key_pressed("space",
            say("Meow!", 2),
        ),
    ),
)
project.save("cat-project.sb3")
```

Not built yet. Contributions welcome.

## License

MIT
