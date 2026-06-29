# Scratch VM — Python

A reimplementation of the [Scratch 3.0](https://scratch.mit.edu) virtual machine in Python.  
Runs Scratch projects using a cooperative generator-based scheduler and a Pygame renderer.

```
python3 -m scratch_vm
```

Press **Space** to start (green flag), **ESC** to quit.

## Architecture

```
src/scratch_vm/
├── __init__.py        Public API
├── __main__.py        Module entry point
├── demo.py            Demo project with 4 sprites
├── types.py           Block, Input, Field, Costume, Sound
├── target.py          Target (stage/sprite), Variable, ListVar
├── thread.py          Thread, Frame, yield protocol
├── runtime.py         Runtime scheduler & sequencer
├── opcodes.py         80+ opcode handlers
└── renderer.py        Pygame rendering
```

| Module | Role |
|---|---|
| `types.py` | Data model — blocks form linked lists via `next`/`parent`; inputs reference child blocks or literals |
| `target.py` | Stage and sprite state — position, direction, costumes, variables, pen |
| `thread.py` | Thread with stack frames — each frame holds a block's generator |
| `runtime.py` | Scheduler — round-robin across threads; sequencer steps generators; `green_flag()`, `broadcast()` |
| `opcodes.py` | Block implementations — each handler is a generator that yields to pause |
| `renderer.py` | Pygame display — stage/sprite drawing, rotation, pen layer, keyboard input |

## Execution Model

Each opcode handler is a **Python generator**.  
- Yielding `YIELD` → pause this thread; resume next frame
- Yielding `wait_yield(secs)` → park until wall-clock time elapses
- Yielding `report(value)` → reporter block returning a value
- Non-generator handlers (instant blocks) execute synchronously

The sequencer (`runtime._step_thread`) steps one generator per call. Control blocks like `repeat`/`forever` use `execute_substack()` to chain through sub-blocks, yielding control between iterations. Threads run cooperatively in round-robin order.

## Opcodes

Implemented categories (80+ handlers):

- **Control** — wait, repeat, forever, if/else, wait until, repeat until, stop
- **Events** — when flag clicked, when broadcast received, broadcast, broadcast and wait
- **Motion** — move steps, go to xy, set/change x/y, turn, point, glide, bounce, x/y/direction reporters
- **Looks** — switch costume, next costume, show/hide, go to front/back, set/change size, costume number/name
- **Operators** — arithmetic, comparison, logic, random, join, letter of, length, contains, mod, round, math ops (sin, cos, sqrt, log, exp, …)
- **Data** — set/change variable, variable reporter, add/delete/insert/replace/list ops, list length/contains reporters
- **Sensing** — touching (bounding-box), key pressed, timer, reset timer
- **Pen** — pen up/down, set color, change/set size, clear, stamp

## Demo

The demo creates 4 sprites:

| Sprite | Behaviour |
|---|---|
| Ball | Bounces around the stage |
| Square | Static (placeholder for mouse-follow) |
| Triangle | Walks in a circle (turn + move) |
| PenWriter | Draws with a pen while bouncing |

## Running

```bash
uv run python3 -m scratch_vm
```

Or directly:

```bash
python3 src/scratch_vm/demo.py
```

## License

MIT
