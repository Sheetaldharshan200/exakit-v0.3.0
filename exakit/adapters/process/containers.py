"""A container engine (docker or podman) as the legacy crossing needs it: find, inspect, start, stop, port."""

from __future__ import annotations

from dataclasses import dataclass

from .runner import Runner

PROBE_TIMEOUT = 20


@dataclass(frozen=True, slots=True)
class Engine:
    name: str      # docker | podman
    path: str


def find_engine(runner: Runner, container: str, *, prefer: str | None = None) -> Engine | None:
    """The engine that knows the container: the recorded one when it is on PATH, else whichever answers for it."""
    if prefer:
        path = runner.which(prefer)
        return Engine(prefer, path) if path else None
    for name in ("docker", "podman"):
        path = runner.which(name)
        if path and runner.run([path, "container", "inspect", container], timeout=PROBE_TIMEOUT).ok:
            return Engine(name, path)
    return None


def engine_answers(runner: Runner, engine: Engine) -> bool:
    done = runner.run([engine.path, "version", "--format", "{{.Server.Version}}"], timeout=PROBE_TIMEOUT)
    return done.ok and bool(done.out.strip())


def container_state(runner: Runner, engine: Engine | None, container: str) -> str:
    """running | stopped | absent | unknown."""
    if not container:
        return "absent"
    if engine is None:
        return "unknown"
    done = runner.run([engine.path, "container", "inspect", "-f", "{{.State.Running}}", container], timeout=PROBE_TIMEOUT)
    if done.ok:
        text = done.out.lower()
        return "running" if "true" in text else "stopped" if "false" in text else "unknown"
    if runner.run([engine.path, "container", "inspect", container], timeout=PROBE_TIMEOUT).ok:
        return "unknown"
    return "unknown" if not engine_answers(runner, engine) else "absent"


def start_container(runner: Runner, engine: Engine, container: str) -> bool:
    return runner.run([engine.path, "start", container], timeout=120).ok


def stop_container(runner: Runner, engine: Engine, container: str) -> bool:
    return runner.run([engine.path, "stop", container], timeout=120).ok


def published_port(runner: Runner, engine: Engine, container: str, inner: str = "8563/tcp") -> int | None:
    done = runner.run([engine.path, "port", container, inner], timeout=PROBE_TIMEOUT)
    for line in done.out.splitlines() if done.ok else []:
        if line.startswith("["):
            continue
        port = line.rsplit(":", 1)[-1].strip()
        if port.isdigit():
            return int(port)
    return None
