"""The console's arrow-key menu: one key applied to the menu state, and the rows redrawn in place."""

from __future__ import annotations

from collections.abc import Sequence
from typing import IO

from .menu_rules import tick
from .widgets import Option, Palette


def menu_key(key: str, options: Sequence[Option], chosen: set[str], cursor: int, single: bool) -> tuple[str, int]:
    """Apply one key to the menu state: (``move``/``enter``/``esc``, the cursor)."""
    if key == "enter":
        return "enter", cursor
    if key in ("esc", "q"):
        return "esc", cursor
    if key in ("up", "k"):
        return "move", (cursor - 1) % len(options)
    if key in ("down", "j"):
        return "move", (cursor + 1) % len(options)
    if key == "a" and not single:
        chosen.update(o.id for o in options if not o.disabled)
    elif key == "n" and not single:
        chosen.clear()
    elif key == "space" or (key.isdigit() and 1 <= int(key) <= len(options)):
        index = cursor if key == "space" else int(key) - 1
        if single:
            return ("enter" if key.isdigit() else "move"), index
        if not options[index].disabled:
            tick(options, chosen, index)
        return "move", index
    return "move", cursor

def draw_menu(out: IO[str], p: Palette, options: Sequence[Option], chosen: set[str], cursor: int, hint: str, single: bool, *, first: bool) -> None:
    """Draw (or redraw in place) the rows of the arrow-key menu and the key hint."""
    if not first:
        out.write(f"\x1b[{len(options) + 1}A")
    for i, option in enumerate(options):
        box = ("(*)" if i == cursor else "( )") if single else ("[x]" if option.id in chosen else "[ ]")
        if option.disabled:
            box = f"{p.dim}[-]"
        pointer = f"{p.accent}{p.arrow}{p.reset}" if i == cursor else " "
        label = f"{p.bold}{option.label}{p.reset}" if i == cursor else option.label
        extra = f"  {p.dim}{option.hint}{p.reset}" if option.hint else ""
        out.write(f"\r\x1b[2K    {pointer} {box} {label}{extra}{p.reset}\n")
    out.write(f"\r\x1b[2K      {p.dim}{hint}{p.reset}\n")
    out.flush()

