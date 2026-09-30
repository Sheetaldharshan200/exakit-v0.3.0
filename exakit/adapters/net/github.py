"""GitHub releases: an asset's URL and its published digest, for the download-verify chain."""

from __future__ import annotations

import json
from dataclasses import dataclass

from .http import Downloader


@dataclass(frozen=True, slots=True)
class ReleaseAsset:
    name: str
    url: str
    digest: str | None     # sha256 hex when GitHub publishes one


def release_assets(repo: str, tag: str, downloader: Downloader, *, token: str | None = None) -> list[ReleaseAsset] | None:
    """The assets of a release, or None when GitHub could not be asked."""
    try:
        text = downloader.text(f"https://api.github.com/repos/{repo}/releases/tags/{tag}", token=token)
        doc = json.loads(text)
    except Exception:
        return None
    assets = []
    for asset in doc.get("assets", []) or []:
        digest = asset.get("digest") or ""
        assets.append(ReleaseAsset(
            name=str(asset.get("name", "")), url=str(asset.get("browser_download_url", "")),
            digest=digest.split(":", 1)[1] if digest.startswith("sha256:") else None,
        ))
    return assets


def asset_digest(repo: str, tag: str, name: str, downloader: Downloader, *, token: str | None = None) -> str | None:
    for asset in release_assets(repo, tag, downloader, token=token) or []:
        if asset.name == name:
            return asset.digest
    return None


def download_url(repo: str, tag: str, name: str) -> str:
    return f"https://github.com/{repo}/releases/download/{tag}/{name}"
