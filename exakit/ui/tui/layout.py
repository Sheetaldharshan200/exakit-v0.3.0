"""Where a list sits beside its detail: as wide as its rows, never more than its share, stacked on top when the terminal is narrow."""

from __future__ import annotations

from exakit.ui.widgets import Option

LIST_MIN, LIST_MAX = 20, 48


def fitted_width(rows: list[Option], most: int = LIST_MAX) -> int:
    """The columns a list needs: pointer and gutter, the widest name, the widest status after two spaces, its border."""
    names = max((len(r.label) for r in rows if not r.heading), default=0)
    hints = max((len(r.hint) for r in rows if r.hint and not r.heading), default=0)
    return max(LIST_MIN, min(most, 3 + names + (2 + hints if hints else 0) + 3))


NARROW = 72          # a view narrower than this stacks the detail under the list instead of beside it


def place_list(view, choices, fitted: int, share: float = 0.5) -> None:
    """Beside the detail: as wide as its rows, at most ``share`` of the view (longer rows end in an ellipsis).
    In a narrow view the list goes on top at full width and the detail below it."""
    width = view.size.width
    narrow = bool(width) and width < NARROW
    view.set_class(narrow, "-narrow")
    choices.styles.width = "100%" if narrow else (max(LIST_MIN, min(fitted, int(width * share))) if width else fitted)
