"""Upstream version lookups for ``EXAKIT_VERSION_POLICY=latest``: GitHub releases and PyPI.

Silence (None) is the only failure mode: the caller falls back. Nothing here
raises past a network error.
"""

from __future__ import annotations

import json

from exakit.domain.versions import _VERSION_RE

from .http import Downloader


def github_latest_release(repo: str, downloader: Downloader, *, token: str | None = None) -> str | None:
    """The tag of the latest non-draft, non-prerelease release, without a leading ``v``."""
    try:
        text = downloader.text(f"https://api.github.com/repos/{repo}/releases/latest", token=token)
        tag = json.loads(text).get("tag_name")
    except Exception:
        return None
    if not isinstance(tag, str):
        return None
    tag = tag.lstrip("v")
    return tag if _VERSION_RE.match(tag) else None


def pypi_latest_version(package: str, downloader: Downloader) -> str | None:
    """The version PyPI marks as current for a package."""
    try:
        text = downloader.text(f"https://pypi.org/pypi/{package}/json")
        version = json.loads(text)["info"]["version"]
    except Exception:
        return None
    return version if isinstance(version, str) and _VERSION_RE.match(version) else None
