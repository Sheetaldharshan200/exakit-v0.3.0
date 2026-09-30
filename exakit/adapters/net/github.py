"""GitHub releases: an asset's URL and its published digest, for the download-verify chain.

Order: the release API first; when it cannot be asked (offline, or the 60-per-hour
unauthenticated limit), the answer cached from the last successful call, keyed by
repository and tag, which never changes for a published release.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..fs.atomic import atomic_write_text
from .http import Downloader


@dataclass(frozen=True, slots=True)
class ReleaseAsset:
    name: str
    url: str
    digest: str | None     # sha256 hex when GitHub publishes one


def _cache_file(cache_dir: Path | None, repo: str, tag: str) -> Path | None:
    return cache_dir / f"{repo.replace('/', '__')}-{tag}.json" if cache_dir else None


def _parse(doc: dict) -> list[ReleaseAsset]:
    assets = []
    for asset in doc.get("assets", []) or []:
        digest = asset.get("digest") or ""
        assets.append(ReleaseAsset(
            name=str(asset.get("name", "")), url=str(asset.get("browser_download_url", "")),
            digest=digest.split(":", 1)[1] if digest.startswith("sha256:") else None,
        ))
    return assets


def release_assets(repo: str, tag: str, downloader: Downloader, *, token: str | None = None,
                   cache_dir: Path | None = None) -> list[ReleaseAsset] | None:
    """The assets of a release: from the API, else from the cached answer, else None."""
    cache = _cache_file(cache_dir, repo, tag)
    try:
        text = downloader.text(f"https://api.github.com/repos/{repo}/releases/tags/{tag}", token=token)
        doc = json.loads(text)
        assets = _parse(doc)
    except Exception:
        try:
            return _parse(json.loads(cache.read_text(encoding="utf-8"))) if cache and cache.is_file() else None
        except (OSError, ValueError):
            return None
    if cache:
        try:
            atomic_write_text(cache, json.dumps({"assets": doc.get("assets", []) or []}), mode=0o644)
        except OSError:
            pass
    return assets


def asset_digest(repo: str, tag: str, name: str, downloader: Downloader, *, token: str | None = None,
                 cache_dir: Path | None = None) -> str | None:
    for asset in release_assets(repo, tag, downloader, token=token, cache_dir=cache_dir) or []:
        if asset.name == name:
            return asset.digest
    return None


def download_url(repo: str, tag: str, name: str) -> str:
    return f"https://github.com/{repo}/releases/download/{tag}/{name}"
