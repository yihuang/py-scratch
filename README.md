# Scratch VM — Python

A Python reimplementation of the [Scratch 3.0](https://scratch.mit.edu) virtual machine. Loads `.sb3` files and runs them.

```bash
uv run scratch-vm /path/to/project.sb3
```

No args → built-in demo (4 sprites: bouncing ball, orbiting triangle, pen drawer, square). Press **ESC** to quit.

## DSL — programmatic block builder

The `scratch.dsl` package lets you build Scratch projects from Python code
using a composable expression API.  Blocks are constructed with factory
functions that mirror their Scratch counterparts, and the result is a valid
`.sb3` file importable by the Scratch editor.

```python
from scratch.dsl import Project, motion, control

project = Project("Bouncing Ball")
sprite = project.sprite("Ball")
sprite.when_flag_clicked(
    control.forever()(
        motion.move(5),
        motion.if_on_edge_bounce(),
        control.wait(0.01),
    ),
)
project.save("ball.sb3")
```

See `docs/dsl-reference.md` for the full API, and `examples/` for runnable scripts.

## License

MIT
