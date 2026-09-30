"""Use cases. Every command is one of these: build a Result, or build a Plan and run it.

``Context`` is everything a use case may touch, built once per command by
the CLI from the adapters for this machine. ``run_plan`` is the ONE apply
loop in the kit: show the plan, confirm (or ``--yes``, or refuse with exit
5), run each pending step in its own try, and answer with one Result.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from exakit.adapters.fs.log import Log, NullLog
from exakit.adapters.fs.manifest_store import ManifestStore
from exakit.adapters.fs.paths import Paths
from exakit.adapters.net.http import Downloader
from exakit.adapters.net.versions_cache import VersionsSource
from exakit.adapters.process.runner import Runner
from exakit.domain.catalog import Catalog
from exakit.domain.errors import ExakitError, NotConfirmed
from exakit.domain.manifest import Manifest
from exakit.domain.plan import Plan, StepState
from exakit.domain.platform import Platform
from exakit.domain.result import Result
from exakit.domain.versions import VersionPolicy
from exakit.ui import Renderer

INSTALL_URL = "https://www.exasol.com/install/starter-kit.sh"


@dataclass
class Context:
    paths: Paths
    platform: Platform
    env: Mapping[str, str]
    catalog: Catalog
    manifest_store: ManifestStore
    versions: VersionsSource
    runner: Runner
    net: Downloader
    ui: Renderer
    log: Log = field(default_factory=NullLog)
    json: bool = False
    yes: bool = False
    dry_run: bool = False
    readonly: bool = False
    kit_repo: str = "krishna-exasol/update-path"

    @property
    def policy(self) -> VersionPolicy:
        return VersionPolicy.from_env(self.env.get("EXAKIT_VERSION_POLICY"))

    def install_command(self) -> str:
        """The one command that (re)runs the installer, runnable as written."""
        return f"curl -fsSL {self.env.get('EXAKIT_INSTALL_URL') or INSTALL_URL} | sh"

    def manifest(self) -> Manifest:
        """The install record. Raises NotInstalled when there is none."""
        return self.manifest_store.load()

    def manifest_or_none(self) -> Manifest | None:
        return self.manifest_store.load() if self.manifest_store.exists() else None


class UseCase(Protocol):
    def plan(self, ctx: Context, **args: Any) -> Plan: ...
    def apply(self, ctx: Context, plan: Plan) -> Result: ...


def plan_data(plan: Plan) -> dict[str, Any]:
    return plan.to_dict()


def run_plan(ctx: Context, plan: Plan, *, confirm_question: str, extra: dict[str, Any] | None = None) -> Result:
    """Apply a plan. Returns a Result with status applied | partial | complete; raises NotConfirmed."""
    extra = extra or {}
    if plan.complete:
        return Result(True, "complete", data={**extra, **plan_data(plan)})
    remedy = f"{plan.remedy_command} --yes" if plan.remedy_command else None
    if not ctx.yes:
        ctx.ui.plan(plan)
        if ctx.json or not ctx.ui.interactive:
            raise NotConfirmed("Nothing changed: confirm the plan to apply it.", remedy=remedy,
                               data={**extra, **plan_data(plan)})
        if not ctx.ui.confirm(confirm_question, default=True):
            raise NotConfirmed("Nothing changed.", remedy=remedy, data={**extra, **plan_data(plan)})
    for step in plan.pending():
        ctx.ui.step_begin(step)
        try:
            if step.run is not None:
                step.run()
            step.state = StepState.DONE
        except ExakitError as err:
            step.state = StepState.FAILED
            step.reason = err.message
            step.remedy = err.remedy or step.remedy
            ctx.log.line("ERROR", f"{step.section} {step.id}: {err.message}")
        ctx.ui.step_end(step)
    failed = plan.failed()
    if not failed:
        return Result(True, "applied", data={**extra, **plan_data(plan)})
    return Result(True, "partial", remedy=failed[0].remedy, remedy_hint=failed[0].reason,
                  data={**extra, **plan_data(plan)}, exit_code=1)
