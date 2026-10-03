"""The one rule for ticking a row in a tick list, shared by the console menu and the screens."""

from __future__ import annotations

from collections.abc import Sequence

from .widgets import Option


def tick(options: Sequence[Option], chosen: set[str], index: int) -> None:
    """Tick or untick a row.

    An exclusive row (a "Skip") clears the others and is cleared by any other. An "everything" row ticks every row
    that can be ticked; unticking it, or any other row, unticks it.
    """
    option = options[index]
    if option.disabled or option.heading:
        return
    tickable = [o for o in options if not o.disabled and not o.heading]     # a heading is drawn, never ticked
    if option.id in chosen:
        chosen.discard(option.id)
        chosen.difference_update({o.id for o in options if o.everything})
        if option.everything:
            chosen.clear()
        return
    if option.everything:
        chosen.clear()
        chosen.update(o.id for o in tickable if not o.exclusive)
        return
    if option.exclusive:
        chosen.clear()
    else:
        chosen.difference_update({o.id for o in options if o.exclusive})
    chosen.add(option.id)
    if all(o.id in chosen for o in tickable if not o.exclusive and not o.everything):
        chosen.update(o.id for o in options if o.everything)
