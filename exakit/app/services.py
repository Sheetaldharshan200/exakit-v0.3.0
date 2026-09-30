"""Services: the database plus every installed add-on that runs as one; start, stop, autostart."""

from __future__ import annotations

from dataclasses import dataclass

from exakit.adapters.process.services import ServiceSpec, for_platform

from . import Context
from .machine import addon_installed_version
from .runtime_ops import ensure_running, runtime


@dataclass(frozen=True, slots=True)
class Service:
    id: str
    hooks: object | None      # ServiceHooks for an add-on; None for the database


def services_adapter(ctx: Context):
    if ctx.services is None:
        home = ctx.env.get("HOME") or str(ctx.paths.home.parent)
        from pathlib import Path
        ctx.services = for_platform(ctx.platform, home=Path(home), logs_dir=ctx.paths.logs, runner=ctx.runner,
                                    env=dict(ctx.env), log=ctx.log)
    return ctx.services


def service_ids(ctx: Context) -> list[Service]:
    """``database`` when a runtime is recorded, then each installed add-on with service hooks."""
    from exakit.lifecycles import for_addon
    manifest = ctx.manifest_or_none()
    out: list[Service] = []
    if manifest and manifest.runtime_type():
        out.append(Service("database", None))
    for addon in ctx.catalog.addons():
        if manifest and addon_installed_version(ctx, addon, manifest)[1]:
            hooks = for_addon(ctx, addon).service()
            if hooks is not None:
                out.append(Service(addon.id, hooks))
    return out


def status_of(ctx: Context, service: Service) -> str:
    if service.hooks is None:
        manifest = ctx.manifest_or_none()
        if manifest and manifest.runtime_type() == "personal":
            return runtime(ctx).status().state
        return "unknown"
    return service.hooks.status()


def start(ctx: Context, service: Service) -> None:
    if service.hooks is None:
        ensure_running(ctx, deploy=True)
    else:
        service.hooks.start()


def stop(ctx: Context, service: Service) -> None:
    if service.hooks is None:
        manifest = ctx.manifest_or_none()
        if manifest and manifest.runtime_type() == "personal":
            runtime(ctx).stop(ctx.ui.info)
    else:
        service.hooks.stop()


def autostart_spec(ctx: Context, service: Service) -> ServiceSpec | None:
    if service.hooks is None:
        manifest = ctx.manifest_or_none()
        if manifest and manifest.runtime_type() == "personal":
            return ServiceSpec("database", (runtime(ctx).cli(), "start"), kind="handoff")
        return None
    return service.hooks.autostart()


def register_autostart(ctx: Context, service: Service) -> bool:
    spec = autostart_spec(ctx, service)
    if spec is None:
        return True
    outcome = services_adapter(ctx).register(spec)
    for note in outcome.notes:
        (ctx.ui.warn if not outcome.ok else ctx.ui.info)(note)
    return outcome.ok


def unregister_autostart(ctx: Context, service_id: str) -> None:
    if services_adapter(ctx).unregister(service_id):
        ctx.ui.ok(f"{service_id}: no longer starts at login")


def autostart_registered(ctx: Context, service_id: str) -> bool:
    return services_adapter(ctx).registered(service_id)


def autostart_enable(ctx: Context) -> bool:
    any_ok = False
    for service in service_ids(ctx):
        if register_autostart(ctx, service):
            any_ok = True
    ctx.manifest_store.update(lambda m: m.set("autostart.enabled", any_ok))
    if any_ok:
        ctx.ui.ok("Automatic start after a restart is on.")
    return any_ok


def autostart_disable(ctx: Context) -> None:
    for service in service_ids(ctx):
        unregister_autostart(ctx, service.id)
    ctx.manifest_store.update(lambda m: m.set("autostart.enabled", False))
    ctx.ui.ok("Automatic start after a restart is off.")


def autostart_wanted(ctx: Context) -> bool:
    manifest = ctx.manifest_or_none()
    return bool(manifest and manifest.get("autostart.enabled") is True)
