"""Build the Context for this machine: the real adapters, wired once per command."""

from __future__ import annotations

import os
from pathlib import Path

from exakit.adapters.fs.log import FileLog, NullLog
from exakit.adapters.fs.manifest_store import FileManifestStore
from exakit.adapters.fs.paths import Paths
from exakit.adapters.net.http import UrllibDownloader
from exakit.adapters.net.versions_cache import CachedVersionsSource
from exakit.adapters.platform.detect import detect
from exakit.adapters.process.runner import SubprocessRunner
from exakit.app import Context
from exakit.domain.catalog import Catalog
from exakit.ui import make_renderer

DEFAULT_KIT_REPO = "krishna-exasol/update-path"


def kit_root_for(paths: Paths) -> Path:
    if (paths.kit / "exakit").is_dir():
        return paths.kit
    return Path(__file__).resolve().parents[2]


def build(*, json: bool, yes: bool, dry_run: bool, readonly: bool, mutating: bool) -> Context:
    env = dict(os.environ)
    paths = Paths.from_env(env, Path.home())
    root = kit_root_for(paths)
    log = FileLog(paths.logs) if mutating and paths.home.exists() else NullLog()
    warnings: list[str] = []
    catalog = Catalog.load(root, paths.personas_user, warn=warnings.append)
    ui = make_renderer(json=json, env=env, log=log, home=str(Path.home()))
    for warning in warnings:
        ui.warn(warning)
    kit_repo = env.get("EXAKIT_KIT_REPO") or env.get("EXAKIT_REPO") or DEFAULT_KIT_REPO
    downloader = UrllibDownloader(user_agent=f"exakit/{_kit_version(root)}")
    versions = CachedVersionsSource.from_env(env, kit_repo=kit_repo, cache_path=paths.versions_cache,
                                             baked_path=root / "versions.json", downloader=downloader, log=log)
    return Context(
        paths=paths, platform=detect(), env=env, catalog=catalog,
        manifest_store=FileManifestStore(paths.manifest, paths.manifest_lock), versions=versions,
        runner=SubprocessRunner(), net=downloader, ui=ui, log=log,
        json=json, yes=yes, dry_run=dry_run, readonly=readonly, kit_repo=kit_repo,
    )


def _kit_version(root: Path) -> str:
    import json as _json
    try:
        return _json.loads((root / "versions.json").read_text(encoding="utf-8"))["kit"]["version"]
    except (OSError, ValueError, KeyError, TypeError):
        return "unknown"
