"""Selection to clipboard, shared by the install screens and the dashboard: copied the moment the mouse is released, and again on Ctrl-C."""

from __future__ import annotations

from collections.abc import Callable

from textual import events

HINT = ("Ctrl-Q quits. Drag to select text: it is copied the moment you release the mouse (Cmd-V or Ctrl-V pastes). "
        "Ctrl-C copies the selection again.")


class CopyKeys:
    """Mixed into an App before ``textual.app.App``. ``copier`` is the host's clipboard tool (pbcopy, clip, wl-copy, xclip, xsel), handed in by the cli; OSC 52 goes out as well for terminals that honour it (over SSH)."""

    copier: Callable[[str], bool] | None = None
    _last_copied = ""

    def copy_to_clipboard(self, text: str) -> None:
        """The host tool and the escape sequence both; whichever the terminal honours wins."""
        if self.copier is not None:
            self.copier(text)
        super().copy_to_clipboard(text)                         # type: ignore[misc]

    def on_text_selected(self, event: events.TextSelected) -> None:
        """The mouse was released over a selection: copy it, so a Cmd-C the terminal keeps for itself finds the text already there."""
        selected = self.screen.get_selected_text()                # type: ignore[attr-defined]
        if selected and selected != self._last_copied:
            self._last_copied = selected
            self.copy_to_clipboard(selected)
            self.notify("Copied - Cmd-V / Ctrl-V pastes", timeout=2)    # type: ignore[attr-defined]

    def action_copy_or_hint(self) -> None:
        """Ctrl-C copies the selected text; without a selection it says how to quit and how to select."""
        selected = self.screen.get_selected_text()                # type: ignore[attr-defined]
        if selected:
            self._last_copied = selected
            self.copy_to_clipboard(selected)
            self.notify("Copied", timeout=2)                      # type: ignore[attr-defined]
            return
        self.notify(HINT, timeout=5)                              # type: ignore[attr-defined]
