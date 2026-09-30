"""Marketplace: optional add-ons. Filled in by Phase B2."""

from __future__ import annotations

from . import Context


def install_addon_quietly(ctx: Context, addon_id: str) -> bool:
    """Install an add-on with its screen output in the log only. Replaced by the full marketplace in B2."""
    return False
