"""
Scratch DSL — Pythonic block builder for .sb3 projects.

Build Scratch 3 projects programmatically using a composable expression API::

    from scratch.dsl import Project, motion, control, looks, events, data, operators, sensing

    project = Project("My Game")
    sprite = project.sprite("Cat")

    sprite.when_flag_clicked(
        control.forever()(
            motion.move(5),
            motion.if_on_edge_bounce(),
            control.wait(0.01),
        ),
    )

    sprite.var("score", 0)
    sprite.when_flag_clicked(
        data.set_variable("score", operators.add(data.variable("score"), 1)),
    )

    project.save("game.sb3")
"""

from .project import Project, ProjectTarget
from . import control
from . import data
from . import events
from . import looks
from . import motion
from . import operators
from . import pen
from . import sensing
from .expr import Reporter, StackExpr
from .builder import Script

__all__ = [
    'Project',
    'ProjectTarget',
    'Reporter',
    'Script',
    'StackExpr',
    'control',
    'data',
    'events',
    'looks',
    'motion',
    'operators',
    'pen',
    'sensing',
]
