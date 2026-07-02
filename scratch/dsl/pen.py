"""
Pen extension category blocks.
"""

from __future__ import annotations

from scratch.vm.types import Field

from .expr import Reporter, StackExpr, _resolve_inputs
def pen_down() -> StackExpr:
    """``pen_penDown``."""
    return StackExpr(opcode="pen_penDown")


def pen_up() -> StackExpr:
    """``pen_penUp``."""
    return StackExpr(opcode="pen_penUp")


def pen_clear() -> StackExpr:
    """``pen_penClear``."""
    return StackExpr(opcode="pen_penClear")


def stamp() -> StackExpr:
    """``pen_stamp``."""
    return StackExpr(opcode="pen_stamp")


def change_pen_color_by(change: int | float | Reporter = 10) -> StackExpr:
    """``pen_changePenColorParamBy`` — changes the pen color parameter."""

    ins, shadows = _resolve_inputs({"COLOR_PARAM": change})
    return StackExpr(
        opcode="pen_changePenColorParamBy",
        inputs=ins,
        fields={"colorParam": Field(name="colorParam", value="color")},
        shadow_reporters=shadows,
    )


def set_pen_color_to(color: int | float | Reporter = 0) -> StackExpr:
    """``pen_setPenColorParamTo`` — sets the pen color parameter."""

    ins, shadows = _resolve_inputs({"COLOR_PARAM": color})
    return StackExpr(
        opcode="pen_setPenColorParamTo",
        inputs=ins,
        fields={"colorParam": Field(name="colorParam", value="color")},
        shadow_reporters=shadows,
    )


def change_pen_shade_by(change: int | float | Reporter = 10) -> StackExpr:
    """``pen_changePenColorParamBy`` — changes the pen shade."""

    ins, shadows = _resolve_inputs({"COLOR_PARAM": change})
    return StackExpr(
        opcode="pen_changePenColorParamBy",
        inputs=ins,
        fields={"colorParam": Field(name="colorParam", value="shade")},
        shadow_reporters=shadows,
    )


def set_pen_shade_to(shade: int | float | Reporter = 50) -> StackExpr:
    """``pen_setPenColorParamTo`` — sets the pen shade."""

    ins, shadows = _resolve_inputs({"COLOR_PARAM": shade})
    return StackExpr(
        opcode="pen_setPenColorParamTo",
        inputs=ins,
        fields={"colorParam": Field(name="colorParam", value="shade")},
        shadow_reporters=shadows,
    )


def change_pen_size_by(change: int | float | Reporter = 1) -> StackExpr:
    """``pen_changePenSizeBy``."""
    ins, shadows = _resolve_inputs({"SIZE": change})
    return StackExpr(opcode="pen_changePenSizeBy", inputs=ins, shadow_reporters=shadows)


def set_pen_size_to(size: int | float | Reporter = 1) -> StackExpr:
    """``pen_setPenSizeTo``."""
    ins, shadows = _resolve_inputs({"SIZE": size})
    return StackExpr(opcode="pen_setPenSizeTo", inputs=ins, shadow_reporters=shadows)


def pen_color(color: str = "#000000") -> StackExpr:
    """``pen_setPenColorToColor`` — sets pen to a specific color.

    *color* is a hex string like "#ff0000".
    """

    return StackExpr(
        opcode="pen_setPenColorToColor",
        fields={"COLOR": Field(name="COLOR", value=color)},
    )


def pen_size(size: int | float | Reporter = 1) -> StackExpr:
    """``pen_setPenSizeTo`` — alias for ``set_pen_size_to``."""
    return set_pen_size_to(size)


def pen_saturation(saturation: int | float | Reporter = 100) -> StackExpr:
    """``pen_setPenColorParamTo`` — sets the pen saturation."""

    ins, shadows = _resolve_inputs({"COLOR_PARAM": saturation})
    return StackExpr(
        opcode="pen_setPenColorParamTo",
        inputs=ins,
        fields={"colorParam": Field(name="colorParam", value="saturation")},
        shadow_reporters=shadows,
    )


def pen_brightness(brightness: int | float | Reporter = 100) -> StackExpr:
    """``pen_setPenColorParamTo`` — sets the pen brightness."""

    ins, shadows = _resolve_inputs({"COLOR_PARAM": brightness})
    return StackExpr(
        opcode="pen_setPenColorParamTo",
        inputs=ins,
        fields={"colorParam": Field(name="colorParam", value="brightness")},
        shadow_reporters=shadows,
    )


def pen_hue(hue: int | float | Reporter = 0) -> StackExpr:
    """``pen_setPenColorParamTo`` — sets the pen hue."""

    ins, shadows = _resolve_inputs({"COLOR_PARAM": hue})
    return StackExpr(
        opcode="pen_setPenColorParamTo",
        inputs=ins,
        fields={"colorParam": Field(name="colorParam", value="hue")},
        shadow_reporters=shadows,
    )
