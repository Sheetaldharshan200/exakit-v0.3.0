"""Where everything lives, computed once from the environment.

Nothing else in the kit builds a path under the kit home by hand.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Paths:
    home: Path            # EXAKIT_HOME, default ~/.exasol-starter-kit
    bin_dir: Path         # EXAKIT_BIN_DIR, default ~/.local/bin (the launcher and add-on launchers)

    @classmethod
    def from_env(cls, env: Mapping[str, str], user_home: Path) -> Paths:
        home = Path(env.get("EXAKIT_HOME") or user_home / ".exasol-starter-kit")
        bin_dir = Path(env.get("EXAKIT_BIN_DIR") or user_home / ".local" / "bin")
        return cls(home=home.expanduser(), bin_dir=bin_dir.expanduser())

    @property
    def kit(self) -> Path:
        return self.home / "kit"

    @property
    def manifest(self) -> Path:
        return self.home / "manifest.json"

    @property
    def manifest_lock(self) -> Path:
        return self.home / "manifest.json.lock"

    @property
    def logs(self) -> Path:
        return self.home / "logs"

    @property
    def credentials(self) -> Path:
        return self.home / "credentials"

    @property
    def cache(self) -> Path:
        return self.home / "cache"

    @property
    def versions_cache(self) -> Path:
        return self.cache / "versions.json"

    @property
    def about_cache(self) -> Path:
        return self.cache / "about"

    @property
    def releases_cache(self) -> Path:
        return self.cache / "releases"

    @property
    def tools(self) -> Path:
        return self.home / "tools"

    @property
    def python(self) -> Path:
        return self.home / "python"

    @property
    def python_interpreter_record(self) -> Path:
        return self.python / "interpreter"

    @property
    def personas_user(self) -> Path:
        return self.home / "personas"

    @property
    def workflows(self) -> Path:
        return self.home / "workflows"

    @property
    def failure_note(self) -> Path:
        return self.home / ".last-failure"

    @property
    def update_in_progress(self) -> Path:
        return self.home / ".update-in-progress"

    @property
    def install_lock(self) -> Path:
        return self.home / ".install.lock"
