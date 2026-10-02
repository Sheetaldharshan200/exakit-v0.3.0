"""Who manages a piece the kit found or installed: the kit itself, an adoption of what was already there, or nobody but the user."""

from __future__ import annotations

from .manifest import Manifest

KIT = "kit"                 # the kit installed it; the kit starts, stops, updates and removes it
ADOPTED = "adopted"         # it was there before the kit and the user said to use it; the kit operates it but never deletes it unasked
EXTERNAL = "external"       # it was there before the kit and the user kept it apart; the kit never touches it
PIECES = ("launcher", "database")

WORDS = {KIT: "installed by the kit", ADOPTED: "yours before the kit, adopted into it", EXTERNAL: "managed outside the kit"}


def word(value: object) -> str:
    """A raw tag (from a record read as a dict) in words."""
    return WORDS.get(str(value or KIT), WORDS[KIT])


def tag(manifest: Manifest, piece: str) -> str:
    """The piece's tag; a record without one was written by a kit that installed everything itself."""
    value = str(manifest.get(f"ownership.{piece}") or KIT)
    return value if value in WORDS else KIT


def describe(manifest: Manifest, piece: str) -> str:
    """The tag in words, for a status line or a card."""
    return WORDS[tag(manifest, piece)]


def controlled(manifest: Manifest, piece: str) -> bool:
    """True when the kit may start, stop and update the piece."""
    return tag(manifest, piece) != EXTERNAL


def set_tag(manifest: Manifest, piece: str, value: str) -> None:
    """Record the tag."""
    manifest.set(f"ownership.{piece}", value)


def adopt_unless_tagged(manifest: Manifest, piece: str) -> None:
    """A piece found on the machine is adopted - unless the record already says whose it is (the kit's own, re-found after a failed step)."""
    if not manifest.get(f"ownership.{piece}"):
        set_tag(manifest, piece, ADOPTED)
