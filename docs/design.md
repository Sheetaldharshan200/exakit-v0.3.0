# Low-level design

Status: DRAFT for review. Implements [architecture.md](architecture.md), which
is approved. Requirements: [requirements.md](requirements.md). Work
breakdown: [tasks.md](tasks.md). Proof: [test-and-acceptance.md](test-and-acceptance.md).

Reading guide: section 1 is the shell that remains, 2 to 8 are the Python
package, 9 the frozen contracts, 10 the update path, 11 testing, 12 the
first work package, 13 the coding standard every file follows.

---

## 1. Bootstrap: the shell that remains

Three shell files per OS family, none of them with lifecycle logic.

### 1.1 `install.sh` (macOS, Linux, WSL) and `install.ps1` (Windows)

```
main()
  1. preflight        not root; curl + tar (or PowerShell 5.1+); supported os/arch
  2. fetch kit        tarball of main (or EXAKIT_REF / EXAKIT_LOCAL_KIT) -> $EXAKIT_HOME/kit
                      staged next to the old copy, swapped by rename, backup kept
  3. ensure python    . bootstrap/ensure-python.sh   (section 1.2)
  4. hand over        exec "$EXAKIT_PYTHON" -m exakit install  (stdin reattached to /dev/tty when possible)
```

Environment it honours: `EXAKIT_HOME`, `EXAKIT_REPO`, `EXAKIT_REF`,
`EXAKIT_LOCAL_KIT`, `EXAKIT_DRY_RUN`, `EXAKIT_PREFLIGHT`, `GITHUB_TOKEN`.
Every other `EXAKIT_*` variable passes through untouched to Python.
`EXAKIT_DRY_RUN=1` stops after step 3 with the plan printed by
`python -m exakit install --dry-run`; `EXAKIT_PREFLIGHT=1` runs
`python -m exakit preflight` after step 3.

Exit codes: 1 preflight failure, 2 bad env value, 0 otherwise (the Python
exit code is propagated by `exec`).

### 1.2 `bootstrap/ensure-python.sh` and `ensure-python.ps1`

The only place that knows how a Python gets onto the machine.

```
ensure_python()
  if EXAKIT_PYTHON set and runs `-c "import sys; sys.exit(sys.version_info < (3,11))"` -> done
  read $EXAKIT_HOME/python/interpreter   (path written by a previous run) -> verify -> done
  if EXAKIT_READONLY_QUERY=1            -> exit 3 (never download from a read-only query)
  uv := $EXAKIT_UV_BIN | `uv` on PATH | $EXAKIT_HOME/tools/uv/uv
  if no uv:
      version, sha256 := versions.json  tools.uv.version, tools.uv.sha256.<platform-key>
      download https://github.com/astral-sh/uv/releases/download/<version>/uv-<triple>.(tar.gz|zip)
      verify sha256 (refuse on mismatch unless EXAKIT_ALLOW_UNVERIFIED_UV=1)
      unpack into $EXAKIT_HOME/tools/uv/
  UV_PYTHON_INSTALL_DIR=$EXAKIT_HOME/python  uv python install 3.12   (idempotent, uv verifies its own downloads)
  interpreter := uv python find 3.12
  write $EXAKIT_HOME/python/interpreter
  export EXAKIT_PYTHON=<interpreter>
```

Why a pinned uv release archive and not `curl astral.sh/uv/install.sh | sh`:
the archive has a digest we control in `versions.json`; the installer script
does not. Why never the system Python: the macOS Xcode stub and the Windows
Store stub both exist, are executable, and fail (documented in today's
`common.sh`).

`versions.json` gains one additive block, validated like every component:

```json
"tools": {
  "uv": {
    "version": "0.8.4",
    "sha256": {
      "linux-aarch64": "...", "linux-x86_64": "...",
      "macos-aarch64": "...", "macos-x86_64": "...",
      "windows-x86_64": "..."
    }
  }
}
```

### 1.3 `bootstrap/exakit` (the launcher on PATH) and `bootstrap/exakit.cmd` + `exakit.ps1`

```sh
#!/bin/sh
# exakit - launcher. Finds the kit's Python and runs the kit. Nothing else.
EXAKIT_HOME="${EXAKIT_HOME:-$HOME/.exasol-starter-kit}"
KIT="$EXAKIT_HOME/kit"
[ -d "$KIT/exakit" ] || { echo "exakit: no kit at $KIT (run the installer)" >&2; exit 4; }
case " $* " in *" --json "*|*" -j "*) EXAKIT_REFUSAL_JSON=1; export EXAKIT_REFUSAL_JSON ;; esac
. "$KIT/bootstrap/ensure-python.sh"      # defines ensure_python; honours EXAKIT_READONLY_QUERY
ensure_python || exit $?
PYTHONPATH="$KIT${PYTHONPATH:+:$PYTHONPATH}" exec "$EXAKIT_PYTHON" -m exakit "$@"
```

Windows: `exakit.cmd` is today's shim (`powershell -NoProfile -ExecutionPolicy Bypass -File "%USERPROFILE%\...\kit\bootstrap\exakit.ps1" %*`) and `exakit.ps1` is the launcher above in PowerShell. Both launchers are under 40 lines and have no branches other than "is Python here".

Read-only commands (`status info version help catalog whats-new skills marketplace --list persona list|show|plan`) set `EXAKIT_READONLY_QUERY=1` inside Python before touching adapters; the launcher only refuses to *download* a Python for them when none exists, answering the documented `{"installed": true, "status": "unknown", "remedy": "exakit update"}` shape with exit 3.

---

## 2. Package `exakit/`: module map and public API

Python 3.11+, standard library only, `from __future__ import annotations`,
dataclasses, `typing.Protocol` for every adapter. Style is the existing
`mcp/` package's. No module over 400 lines; no function over 40.

```
exakit/
  __init__.py            __version__ read from kit versions.json at import
  __main__.py            sys.exit(cli.main())
  cli/
    __init__.py          main(argv) -> int; build_parser(); dispatch(); MIGRATED_COMMANDS
    _common.py           add_json_flag(), add_yes_flag(), render_or_json(result, ctx)
    status.py info.py version.py help.py catalog.py whats_new.py
    persona.py marketplace.py skills.py mcp.py data.py sql.py logs.py
    install.py update.py runtime.py (start/stop/repair/autostart/migrate) uninstall.py
    legacy.py            passthrough to setup/legacy-exakit(.ps1) for not-yet-migrated commands
  ui/
    __init__.py          Renderer Protocol; make_renderer(mode) -> Renderer
    plain.py             no colour, one line per event (no tty, NO_COLOR, EXAKIT_NO_FANCY)
    ansi.py              banner, palette, glyphs, spinner, progress, live table, panel, menus (port of ui.sh)
    silent.py            used under --json: everything goes to the log, nothing to stdout
    widgets.py           shared: wrap(), visible_len(), Table/Panel dataclasses
  app/
    __init__.py          Context dataclass; UseCase Protocol (plan/apply)
    status.py info.py version.py help.py
    persona.py marketplace.py skills.py mcp.py data.py
    install.py update.py runtime.py uninstall.py
    notice.py            the once-a-day pending-update notice
    machine.py           MachineState probe: what is on THIS machine (datasets, clients, add-ons, skills)
  domain/
    errors.py            ExakitError hierarchy with exit codes (the only place codes are defined)
    result.py            Result, Refusal
    plan.py              Step, StepState, Plan
    manifest.py          Manifest (pure dict ops + schema + migrations)
    versions.py          VersionsDoc, VersionPolicy, resolve(), compare()
    catalog.py           Component, Addon, Persona dataclasses + validate_*() + Catalog
    persona.py           answers_for(persona, env) -> Answers; plan_for(persona, machine) -> Plan
    platform.py          Platform(os, arch, wsl) + platform_key()
    ids.py               canonical client ids, dataset ids helpers, is_token()
  adapters/
    fs/       paths.py (Paths), atomic.py (atomic_write), lock.py (FileLock), manifest_store.py, log.py
    process/  runner.py (Runner Protocol + SubprocessRunner), services.py (Services Protocol + launchd/systemd/taskscheduler)
    platform/ base.py (PlatformAdapter Protocol), macos.py, linux.py, wsl.py, windows.py, detect.py
    net/      http.py (Downloader), digest.py (sha256), github.py, pypi.py, versions_cache.py
    runtime/  personal.py (PersonalRuntime Protocol + impl over the `exasol` launcher), podman.py
    clients/  (today's mcp/adapters, moved: base.py, registry.py, one file per client)
    exapump.py           the exapump CLI wrapper (profiles, sql, upload)
  lifecycles/
    __init__.py          Lifecycle Protocol; for_addon(addon) -> Lifecycle
    python_venv.py       uv venv + uv pip install <package>==<version>; console script launcher
    binary.py            release asset -> verify digest -> place under $EXAKIT_HOME/tools/<id>/ -> launcher in bin dir
    host_extension.py    e.g. VS Code: `code --install-extension` from a verified .vsix
```

### 2.1 Public signatures (the ones other modules call)

```python
# domain/errors.py
class ExakitError(Exception):
    code: int = 1                      # Failed
    def __init__(self, message: str, *, remedy: str | None = None, hint: str | None = None): ...
class BadInput(ExakitError):      code = 2
class NotRunning(ExakitError):    code = 3
class NotInstalled(ExakitError):  code = 4
class NotConfirmed(ExakitError):  code = 5
EXIT_OK = 0

# domain/result.py
@dataclass(slots=True)
class Result:
    installed: bool
    status: str
    remedy: str | None = None
    remedy_hint: str | None = None
    data: dict[str, Any] = field(default_factory=dict)   # command-specific keys, merged flat into JSON
    exit_code: int = 0
    def to_json(self) -> str: ...                        # one line, keys: installed, status, remedy, [remedy_hint], **data

# domain/plan.py
class StepState(str, Enum): DONE = "done"; PENDING = "pending"; SKIPPED = "skipped"; FAILED = "failed"
@dataclass(slots=True)
class Step:
    section: str          # datasets | mcp_clients | addons | skills | components | files | services ...
    id: str
    state: StepState
    reason: str = ""      # why skipped/failed
    run: Callable[[], None] | None = None   # set by app for pending steps; None in plan-only mode
    remedy: str | None = None               # the one command that retries this step
@dataclass(slots=True)
class Plan:
    title: str
    steps: list[Step]
    def pending(self, section: str | None = None) -> list[Step]: ...
    def by_section(self) -> dict[str, list[Step]]: ...
    @property
    def complete(self) -> bool: ...

# domain/manifest.py
SCHEMA_VERSION = 2
class Manifest:
    def __init__(self, doc: dict[str, Any]): ...
    @classmethod
    def new(cls, *, platform: Platform, kit_version: str, kit_source: str) -> "Manifest": ...
    def get(self, path: str, default: Any = None) -> Any: ...      # "components.mcp_server.version"
    def set(self, path: str, value: Any) -> None: ...
    def delete(self, path: str) -> None: ...
    def migrate(self) -> list[str]: ...                            # 1 -> 2: adds schema_version, persona:{}, kit.python; returns notes
    @property
    def doc(self) -> dict[str, Any]: ...

# domain/versions.py
class VersionPolicy(str, Enum): MANIFEST = "manifest"; LATEST = "latest"; PINNED = "pinned"
@dataclass(frozen=True)
class VersionsDoc:
    raw: dict[str, Any]
    @classmethod
    def parse(cls, text: str) -> "VersionsDoc": ...               # raises BadInput on schema/charset violations
    def kit_version(self) -> str: ...
    def component(self, id: str) -> dict[str, Any] | None: ...
    def sha256(self, id: str, platform_key: str) -> str | None: ...
    def tool(self, id: str) -> dict[str, Any] | None: ...
def resolve(component_id: str, *, policy: VersionPolicy, env_pin: str | None,
            doc: VersionsDoc | None, fallback: str, latest: Callable[[], str | None]) -> tuple[str, str]:
    """-> (version, source) where source in {env, manifest, latest, fallback}"""
def compare(a: str, b: str) -> int: ...                             # PEP-440-ish loose compare, never raises

# domain/catalog.py
@dataclass(frozen=True) class Component: id; title; kind; package|repo; severity; min_kit_version; ...
@dataclass(frozen=True) class Addon:     id; title; kind; source; platforms; requires; provides; service; skill; help; ...
@dataclass(frozen=True) class Persona:   id; title; summary; datasets; mcp_clients; addons; skills; source
def validate_component(doc) -> list[str]; validate_addon(doc) -> list[str]; validate_persona(doc, *, known_datasets, known_addons, known_clients) -> list[str]
class Catalog:
    def __init__(self, components: dict[str, Component], addons: dict[str, Addon], personas: dict[str, Persona]): ...
    @classmethod
    def load(cls, kit_root: Path, user_root: Path | None, *, warn: Callable[[str], None]) -> "Catalog": ...
    def component(self, id) -> Component; def addon(self, id) -> Addon; def persona(self, id) -> Persona   # raise BadInput with known ids
    def persona_ids(self) -> list[str]; def addon_ids(self) -> list[str]

# domain/persona.py
@dataclass(frozen=True)
class Answers:
    datasets: list[str] | None          # None = "no sample data" (EXAKIT_LOAD_SAMPLE=0)
    mcp_clients: str                    # "all" | "skip" | csv of ids
    addons: list[str]                   # already filtered by the caller against MachineState
def answers_for(persona: Persona, env: Mapping[str, str], *, all_datasets: list[str]) -> Answers: ...   # explicit env wins per variable
def plan_for(persona: Persona, machine: "MachineState") -> Plan: ...   # pure: done/pending/skipped+reason

# app/__init__.py
@dataclass
class Context:
    paths: Paths; platform: Platform; env: Mapping[str, str]
    catalog: Catalog; manifest: ManifestStore; versions: VersionsSource
    runner: Runner; net: Downloader; runtime: PersonalRuntime; services: Services; clients: ClientRegistry
    ui: Renderer; log: Log
    json: bool; yes: bool; dry_run: bool; readonly: bool
class UseCase(Protocol):
    def plan(self, ctx: Context, **args) -> Plan: ...
    def apply(self, ctx: Context, plan: Plan) -> Result: ...
def run_plan(ctx: Context, plan: Plan, *, confirm_question: str) -> Result:
    """The one apply loop: show plan -> confirm (or --yes / NotConfirmed) -> run steps in order,
    each in try/except, mark FAILED with reason+remedy, continue -> verify -> Result(applied|partial)."""

# app/machine.py
@dataclass(frozen=True)
class MachineState:
    loaded_datasets: set[str]; all_datasets: list[str]
    client_states: dict[str, str]        # id -> connected | pending | missing
    addon_states: dict[str, tuple[str, str]]  # id -> (installed|available|system|unavailable|missing-module, reason)
    skills_current: bool
def probe(ctx: Context, *, need: set[str]) -> MachineState: ...   # only probes the sections asked for

# lifecycles/__init__.py
class Lifecycle(Protocol):
    def applicable(self, ctx: Context, addon: Addon) -> tuple[bool, str]: ...
    def system_present(self, ctx, addon) -> bool: ...
    def installed_version(self, ctx, addon) -> str | None: ...
    def install(self, ctx, addon, version: str) -> None: ...
    def validate(self, ctx, addon) -> None: ...
    def update(self, ctx, addon, version: str) -> None: ...
    def uninstall(self, ctx, addon, *, dry_run: bool) -> list[str]: ...   # paths it would/did remove
    def service(self, ctx, addon) -> ServiceHooks | None: ...             # status/start/stop/urls/log_path, or None
def for_addon(addon: Addon, kit_root: Path) -> Lifecycle:
    """kind -> built-in lifecycle; catalog/addons/<id>/lifecycle.py (class Lifecycle) overrides when present."""
```

---

## 3. Data schemas

All JSON is canonical (`json.tool`, indent 2, one key per line, LF, ASCII).
Each schema has a `schema_version`. Validators return a list of problems;
an empty list is valid. Shipped files that fail validation fail CI.

### 3.1 `catalog/components/<id>.json`

```json
{
  "schema_version": 1,
  "id": "exapump",
  "title": "exapump",
  "kind": "binary",                          // binary | python-tool | runtime | skills | helper
  "source": {"type": "github_release", "repo": "exasol-labs/exapump", "asset": "exapump-{os}-{arch}{ext}"},
  "install_order": 30,
  "step_id": "exapump",                      // the steps_completed key (unchanged)
  "fallback_version": "0.13.0",              // today's *_FALLBACK constants move here
  "requires": ["runtime"],
  "help": "exapump"                          // help/<id>.json
}
```

The five core components today (personal, exapump, mcp, pyexasol, skills)
plus `exakit` (the helper) become six files. `versions.json` keeps
carrying the advertised version, severity, note, min_kit_version and
digests; the catalog carries what does not change per release.

### 3.2 `catalog/addons/<id>/addon.json`

```json
{
  "schema_version": 1,
  "id": "dash-server",
  "title": "dash-server (AI dashboard host)",
  "kind": "python-venv",                     // python-venv | binary | host-extension | custom
  "source": {"type": "github_tag", "repo": "exasol-labs/dash-server"},
  "platforms": ["macos-aarch64", "macos-x86_64", "linux-aarch64", "linux-x86_64", "windows-x86_64"],
  "requires": ["runtime", "mcp"],            // component/add-on ids that must be present
  "provides": ["dashboarding"],              // capabilities (persona schema 2 will select on these)
  "service": {"port": 8050, "autostart": true, "url": "http://127.0.0.1:{port}"},
  "launcher": "dash-server",                 // name placed in the bin dir
  "skill": "skill/",                         // optional, SKILL.md inside, addon: <id>
  "help": "dash-server",                     // help/<id>.json (repo + tagline live there today; they stay)
  "fallback_version": "0.1.1"
}
```

`kind: custom` means `lifecycle.py` next to it exports `class Lifecycle`
implementing the Protocol. The generic lifecycles cover everything the five
add-ons do today except: exasol-scheduler's DB user bootstrap (custom hook
`post_install`), json-tables' Windows cargo shim (a second `binary` asset
under `source.extra`). Both are expressed as optional hooks, not full
modules: `hooks.py` may define `post_install(ctx, addon)`, `pre_uninstall`,
`validate`.

### 3.3 `catalog/personas/<id>.json` (schema 1, unchanged from the approved draft)

```json
{
  "schema_version": 1,
  "id": "data-scientist",
  "title": "Data Scientist",
  "summary": "Every sample dataset, every AI client on this machine, dashboards and JSON ingestion.",
  "datasets": "all",                         // "all" | "none" | [ids]
  "mcp_clients": "all",                      // "all" | "skip" | [client ids]
  "addons": ["dash-server", "json-tables"],  // "all" | "none" | [ids]
  "skills": "all"                            // reserved
}
```

User personas: `$EXAKIT_HOME/personas/<id>.json`, same schema, shadow by id.

### 3.4 `manifest.json` schema 2 (additive)

```
schema_version: 2                      NEW (absent = 1; migrate() adds it and the two blocks below)
kit.python: <interpreter path>         NEW
persona: {id, source: install|apply, requested_at, applied_at, skipped}   NEW, absent when none
everything else                        exactly today's keys (section 2 map in the codebase audit)
```

Migration 1 to 2 runs on first write by the Python kit, never on a read-only
query, and is logged as one line.

### 3.5 `versions.json`

Schema stays 1. Additive: `tools.uv` (section 1.2) and, per component,
nothing new. The `expected` component set in `versions.yml` stays.

---

## 4. Use cases

Every mutating use case is `plan -> confirm -> apply -> verify -> record`.
`run_plan()` in `app/__init__.py` is the only apply loop in the codebase.

| Use case | plan() builds | apply() steps (each a `Step.run`) | verify | records |
|---|---|---|---|---|
| install | components in `install_order`, filtered by `steps_completed`; then data, clients, skills, marketplace offer as sections; persona answers folded in | one step per component via its lifecycle; data via `data.load`; clients via `mcp.setup`; skills via `skills.place`; add-ons via `marketplace.install` | each lifecycle `validate()`; `runtime.status()` | `steps_completed`, `install.current_step`, soft failures, `persona.*` |
| update | `exakit`, `runtime`, core components, `skills`, installed add-ons; `version_available > current` and not ahead; heavy (runtime) gated by `--yes`/env/confirm | self-update (stage main tarball, swap, reinstall launcher, re-place skills); per-component `update()` | `validate()` | `kit.version`, `kit.source`, `components.<id>.version` |
| marketplace | selected add-ons: state from `MachineState.addon_states`; refuse unknown; skip unavailable with reason (explicit `exakit marketplace <id>` of an unavailable one is still `BadInput`, as today) | `install -> validate -> place skill -> autostart -> start` | service status | `components.<id>.*` |
| persona | `domain.persona.plan_for()` | datasets via data, clients via mcp, add-ons via marketplace, skills via skills | re-probe | `persona.*` |
| mcp | client selection (env or menu) x adapter detection | read-only user, per-client render + write with snapshot | validator | `components.mcp_server.*` |
| data | datasets/files pending | exapump loads with progress table | marker tables | `data.*` |
| skills | diff of shipped vs placed | copy, retire, allowlist | re-list | `components.skills.*` |
| runtime | start/stop/repair/autostart/migrate | `PersonalRuntime` calls, Services | `status()` | `runtime.*`, `autostart.enabled` |
| uninstall | selection (menu/env) -> files, services, configs, database | typed confirmation for everything; snapshots kept | re-probe | manifest removed or trimmed |

Read-only use cases (`status`, `info`, `version`, `help`, `catalog`,
`whats-new`, `persona list/show/plan`, `marketplace --list`, `skills`,
`logs`, `mcp-status`, `mcp-doctor` without repair) build a `Result` directly
and never write (except the versions cache refresh, which today's code also
allows).

### 4.1 `run_plan()` in full

```python
def run_plan(ctx, plan, *, confirm_question) -> Result:
    if plan.complete:
        return Result(True, "complete", data=plan_json(plan))
    if not ctx.yes:
        ctx.ui.plan(plan)
        if ctx.json or not ctx.ui.interactive:
            raise NotConfirmed("nothing changed", remedy=f"{plan.remedy_command} --yes", data=plan_json(plan))
        if not ctx.ui.confirm(confirm_question, default=True):
            raise NotConfirmed("nothing changed", remedy=f"{plan.remedy_command} --yes")
    failed: list[Step] = []
    for step in plan.pending():
        ctx.ui.step_begin(step)
        try:
            step.run(); step.state = StepState.DONE
        except ExakitError as err:
            step.state, step.reason, step.remedy = StepState.FAILED, str(err), err.remedy or step.remedy
            failed.append(step)
        ctx.ui.step_end(step)
    status = "applied" if not failed else "partial"
    remedy = failed[0].remedy if failed else None
    return Result(True, status, remedy=remedy, data=plan_json(plan), exit_code=0 if not failed else 1)
```

Under `--json`, `ctx.ui` is the `silent` renderer, so stdout carries the
one `Result` line and everything else is in the log.

---

## 5. CLI

### 5.1 Parser

```
exakit [--json|-j] [--yes|-y] [--dry-run] <command> [args]
```

Global flags are accepted before or after the command (argparse
`parents=` on every subparser), matching today's `exakit status --json`.
Each `cli/<command>.py` exposes `register(subparsers) -> None` and
`run(args, ctx) -> Result`. `cli/__init__.py`:

```python
MIGRATED_COMMANDS: frozenset[str]   # grows per phase; anything else -> cli.legacy.run()
def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    ctx = build_context(args)                       # adapters for this OS, renderer for this tty/--json
    try:
        result = COMMANDS[args.command].run(args, ctx)
        emit(result, ctx)                           # JSON line or rendered
        notice.maybe_show(ctx, args.command)        # the pending-update notice, never under --json
        return result.exit_code
    except ExakitError as err:
        emit_refusal(err, ctx)                      # {"ok": false, "error", "remedy", "rejected"} under --json; card otherwise
        return err.code
    except KeyboardInterrupt:
        return 130
```

Unknown command: `BadInput` with remedy `exakit catalog --json` (exit 2). A
bare component id (`exakit mcp`) renders that help page, as today.

### 5.2 Legacy passthrough (phases A to C only)

`cli/legacy.py` runs `bash setup/legacy-exakit <argv>` (or
`powershell -File setup/legacy-exakit.ps1`) with stdin/stdout/stderr
inherited and returns its exit code. The migrated set is the single source
of truth; `tests/contract` asserts every command is in exactly one of the two
worlds.

---

## 6. UI renderer contract

```python
class Renderer(Protocol):
    interactive: bool
    def banner(self, title: str) -> None
    def heading(self, text) / info / ok / warn / error(self, text) -> None
    def panel(self, title: str, lines: list[str]) -> None
    def rule(self) -> None
    def plan(self, plan: Plan) -> None                     # the persona/marketplace/update panel
    def step_begin(self, step: Step) / step_end(self, step: Step) -> None   # spinner or table row
    def table(self, table: Table) -> LiveTable             # begin/update/end, one live table at a time
    def select(self, title: str, options: list[Option], default: int) -> int | None
    def checkboxes(self, title: str, options: list[Option], defaults: set[int]) -> set[int]
    def confirm(self, question: str, default: bool) -> bool
    def prompt(self, question: str, default: str) -> str
```

`ansi.py` is a port of `ui.sh` (same glyphs, palette, box drawing, live
table behaviour, terminal-width capping) so screens look identical.
`plain.py` prints one line per call. `silent.py` writes to the log. Menus in
non-interactive mode return their defaults, exactly as today.

---

## 7. Adapter protocols (each in its own file, each with a fake in `tests/unit/fakes/`)

| Protocol | Methods | Implementations |
|---|---|---|
| `Paths` | `home, kit, manifest, logs, credentials, cache, tools, python, bin_dir, personas_user, workflows` | one, computed from `EXAKIT_HOME`, `EXAKIT_BIN_DIR` |
| `ManifestStore` | `load() -> Manifest`, `save(m)`, `exists()`, `locked()` context | file store with `FileLock` + atomic replace |
| `Runner` | `run(cmd, *, env, cwd, timeout, capture, stdin) -> Completed(code, out, err)`, `which(name)` | `SubprocessRunner` |
| `Services` | `install(ServiceSpec)`, `remove(name)`, `status(name) -> running|stopped|absent`, `start`, `stop` | `launchd.py`, `systemd.py` (user units), `taskscheduler.py` |
| `PlatformAdapter` | `detect() -> Platform`, `bin_dir()`, `add_to_profile(path) -> str|None`, `unsigned_binary_hint(path)`, `container_engine()` | macos, linux, wsl, windows |
| `Downloader` | `fetch(url, dest, *, sha256=None, token=None) -> Path`, `text(url, *, ttl_cache=None) -> str` | urllib-based, retries, refuses http:// |
| `VersionsSource` | `current() -> VersionsDoc`, `refresh(force=False)`, `source_label()` | fetch -> cache -> kit copy -> none (today's chain) |
| `PersonalRuntime` | `launcher_version()`, `install_launcher(version)`, `deploy(opts)`, `start()`, `stop()`, `status() -> RuntimeStatus`, `credentials() -> Credentials`, `destroy()` | over the `exasol` launcher CLI |
| `ClientRegistry` | today's `AdapterRegistry` | moved as is |
| `Exapump` | `ensure_profile()`, `sql(text, *, write, json)`, `upload(...)`, `bucketfs(...)` | wrapper over the binary |
| `Log` | `line(level, msg)`, `path` | one file per run under `logs/` |

---

## 8. Lifecycles (generic add-on behaviour)

```
python_venv     uv venv $HOME_KIT/<id>-venv --python 3.12 ; uv pip install <spec>==<version>
                launcher: bin_dir/<launcher> -> venv/bin/<console_script>
binary          asset URL from source + version + platform_key ; download ; sha256 from versions.json
                (else fallback digest in addon.json, else GitHub asset digest) ; place tools/<id>/ ; launcher
host_extension  verified .vsix (or equivalent) ; `code --install-extension` ; applicable = host CLI found
```

Each records `components.<id_>.{version, path|venv, launcher, validated}`
and, when `service` is set, registers autostart through `Services` when
`autostart.enabled`.

---

## 9. Frozen contracts (golden in `tests/contract/golden/`)

Unchanged from today: every `--json` shape of `status info version
mcp-status mcp-doctor sql skills marketplace --list logs catalog help`,
the refusal object, exit codes, and every `EXAKIT_*` variable in
`AGENTS.md`. Additions, all additive:

- `status --json`: `"persona": "<id>" | null`, `"schema_version": 2`.
- `info --json`: the manifest dump gains the `persona` and `kit.python` keys.
- `exakit persona list|show|plan|apply --json`: the shapes in the approved
  persona design (list: `recorded`, `personas[]`; plan/apply: `persona`,
  `datasets[]`, `mcp_clients[]`, `addons[]`, `skills`, `pending`, `failed[]`),
  each with `installed`, `status`, `remedy`.
- `EXAKIT_PERSONA=<id>` on the install.

---

## 10. Update path from 0.2.0

1. `versions.json` `kit.version` = `0.3.0`; `whats-new.json` 0.3.0 card.
2. The 0.2.0 kit's `exakit_update_self` stages the new tarball, swaps `kit/`,
   and installs `setup/exakit` to `~/.local/bin/exakit`. In the new tree,
   `setup/exakit` **is the launcher** (a copy of `bootstrap/exakit`), and the
   legacy CLI lives at `setup/legacy-exakit`. Same on Windows:
   `setup/exakit.ps1` is the launcher, `setup/legacy-exakit.ps1` the old CLI.
   So the very update that brings the tree also installs the launcher, with
   no change to the 0.2.0 code.
3. First `exakit` run after the update: the launcher finds no managed Python,
   runs `ensure-python`, then `python -m exakit`. `Manifest.migrate()` runs on
   the first write.
4. Read-only commands that day answer from Python once it exists; before that,
   from the documented "unknown" shape.

---

## 11. Testing

| Suite | What | How it runs |
|---|---|---|
| `tests/unit/` | domain and app with fakes; every lifecycle against a fake runner; persona answers/plan; manifest migration; versions resolve/compare; catalog validation of every shipped file | `python -m unittest discover -s tests/unit -t .` |
| `tests/contract/` | golden `--json` per command and state (not installed, no database, running, update pending, persona recorded); refusal object; exit codes; `MIGRATED_COMMANDS` covers each command once | same runner; goldens captured from the legacy CLI in a sandbox with paths/timestamps normalised |
| `tests/e2e/` | `install.sh` / `install.ps1` dry run per OS; launcher with no Python; update 0.2.0 -> new against a fixture manifest; `EXAKIT_PERSONA` unattended install (dry run) | GitHub matrix macos/ubuntu/windows |
| `tests/legacy/` | today's `tests/*.sh` and `*.ps1`, moved unchanged | run in CI until the code they cover is deleted (phase D) |

CI: `versions.yml` gains the three Python suites; the legacy suite list is
moved, not edited. `windows-ps51.yml` gains `tests/e2e` Windows dry runs.

---

## 12. Phase A work package (the first implementation slice)

Files, in build order. Each item is a PR-sized commit with its tests.

1. `exakit/domain/{errors,result,plan,platform,ids}.py` + unit tests.
2. `exakit/domain/manifest.py` (schema 2, migrate) + `adapters/fs/*` + tests.
3. `exakit/domain/versions.py` + `adapters/net/{http,digest,versions_cache}.py` + tests (parity with `tests/versions-manifest.sh` promises 1 to 4).
4. `exakit/domain/catalog.py` + `catalog/components/*.json`, `catalog/addons/*/addon.json` (metadata only, no lifecycle yet), `catalog/personas/*.json` + validation tests.
5. `exakit/ui/{plain,silent,widgets}.py`; `ansi.py` port of ui.sh (banner, panel, table, menus).
6. `exakit/app/{status,info,version,help,machine,notice}.py`, `exakit/app/persona.py` (list/show/plan) + `cli/` for those + `cli/legacy.py` + contract goldens.
7. `bootstrap/ensure-python.{sh,ps1}`, `bootstrap/exakit{,.cmd,.ps1}`; `setup/exakit` -> launcher, `setup/legacy-exakit`; `install.sh`/`install.ps1` steps 3 and 4; `versions.json` `tools.uv`.
8. `tests/e2e` dry runs; move `tests/*.sh` to `tests/legacy/`; CI wiring.
9. Docs: `AGENTS.md`, `README.md`, quickstarts, `CHANGELOG.md`, `whats-new.json`, `CLAUDE.md` (new "adding a persona / add-on" recipes), `MARKETPLACE.md` pointer to the catalog.

Phase B follows the same shape for marketplace, skills, mcp, data,
persona apply; Phase C for install, update, runtime, uninstall; Phase D
deletes `setup/`.

---

## 13. Coding standard (checked in review; enforced by `tests/unit/test_style.py` where mechanical)

- Python 3.11+, stdlib only in `exakit/`. `from __future__ import annotations`, full type hints, `@dataclass(slots=True)` for data, `Protocol` for boundaries, `Enum` for closed sets.
- One concept per module; a module is at most 400 lines; a function at most 40 lines and one level of responsibility. If a function needs a comment to separate phases, split it.
- No `subprocess`, `open`, `urllib`, `os.environ` writes outside `adapters/`. `domain/` imports nothing from `app/`, `adapters/`, `ui/`, `cli/`.
- Every user-visible string is a plain sentence, ASCII, and names the one command that fixes the problem. Remedies are runnable commands or `None`, never prose.
- Errors are raised, not returned; only `run_plan()` and `cli.main()` catch them.
- Every public function has a one-paragraph docstring saying what it guarantees, not how it works. Comments explain a decision, not a line.
- Tests: one behaviour per test, named `test_<condition>_<expectation>`; fakes over mocks; no network, no real machine state, no sleeps.
- Naming: ids are kebab-case in data and CLI (`dash-server`), snake_case in manifest keys (`dash_server`), `PascalCase` classes, `snake_case` functions. The mapping lives in `domain/ids.py` and nowhere else.
- Nothing platform-specific outside `adapters/platform/`, `adapters/process/services.py`, `bootstrap/`.
