# Tasks

Status legend: `[ ]` not started, `[~]` in progress, `[x]` done, `[-]` dropped (say why).
Update this file in the same commit as the work. Design sections are in
[design.md](design.md); phases in [architecture.md](architecture.md) section 7.

## Phase A: bootstrap, launcher, read-only commands, persona list/plan

### Domain
- [x] A1 `exakit/domain/{errors,result,plan,platform,ids}.py` + unit tests (design 2.1)
- [x] A2 `exakit/domain/manifest.py` schema 2 + migrate, `adapters/fs/{paths,atomic,lock,manifest_store,log}.py` + tests (design 3.4)
- [x] A3 `exakit/domain/versions.py` + `adapters/net/{http,digest,versions_cache,github,pypi}.py` + tests mirroring the four promises of `tests/versions-manifest.sh`
- [x] A4 `exakit/domain/catalog.py` + validators; `catalog/components/*.json`; `catalog/addons/*/addon.json` (metadata only); `catalog/personas/*.json` (moved from setup/personas); tests validate every shipped file (design 3.1 to 3.3)
- [x] A5 `exakit/domain/persona.py` answers_for + plan_for + tests (the 32-row acceptance matrix rows A1 to A12, A19, A20)

### UI and app
- [x] A6 `exakit/ui/{__init__,plain,silent,widgets}.py`
- [x] A7 `exakit/ui/console.py` with the legacy palettes: banner, panel, rule, spinner, numbered select, checkbox by numbers, confirm/prompt. The live progress table and the arrow-key checkbox arrive with the flows that need them (B2, B5)
- [x] A8 `exakit/app/{__init__,machine,notice}.py` with Context and run_plan (design 4.1)
- [x] A9 `exakit/app/{version,help,whats_new}.py` + `cli/` modules + contract tests against the real CLI. `status` and `info` stay on the legacy CLI until the runtime adapter (C1): their answers need the database probe (design 11, D8)
- [x] A10 `exakit/app/persona.py` list/show/plan + `cli/persona.py` + goldens (acceptance A15 to A20, A25, A26)
- [x] A11 `cli/__init__.py` main/dispatch/MIGRATED_COMMANDS + `cli/legacy.py` passthrough + contract test that every command is in exactly one world

### Bootstrap and update path
- [x] A12 `bootstrap/ensure-python.sh` + `.ps1`; `versions.json` `tools.uv` block with digests; unit test for the digest table
- [x] A13 `bootstrap/exakit`, `exakit.cmd`, `exakit.ps1` launchers; `setup/exakit` becomes the launcher and the legacy CLI moves to `setup/legacy-exakit` (same for `.ps1`) (design 10)
- [x] A14 `install.sh` / `install.ps1` steps 3 and 4; `EXAKIT_DRY_RUN` and `EXAKIT_PREFLIGHT` routed to Python
- [x] A15 `versions.json` kit 0.3.0; `setup/whats-new.json` 0.3.0 card

### Tests and CI
- [x] A16 `tests/unit`, `tests/contract`, `tests/e2e` runners. The legacy suites stay at `tests/*.sh` and `*.ps1` (their `ROOT` is `dirname/..`; moving them would touch 40 files for nothing) and now run against `setup/legacy-exakit*` (design 11, D9)
- [x] A17 `versions.yml` and `windows-ps51.yml` run the three Python suites and the legacy suites
- [ ] A18 Full local run on this Mac (bash 3.2, pwsh 7, python 3.12) recorded in test-and-acceptance.md section 5

### Docs
- [x] A19 `AGENTS.md` (EXAKIT_PERSONA, `exakit persona`), `README.md`, quickstarts, `CHANGELOG.md`, `CLAUDE.md` recipes (persona, add-on, component), `MARKETPLACE.md` pointer
- [x] A20 `docs/adr/0001-0006.md` for decisions A1 to A6
- [x] A21 Work lives in `Sheetaldharshan200/exakit-v0.3.0` (private) on `main`; no AI attribution

## Phase B: marketplace, skills, mcp, data, persona apply, logs, sql

- [ ] B1 `lifecycles/{python_venv,binary,host_extension}.py` + fakes + tests
- [ ] B2 `app/marketplace.py` + `cli/marketplace.py`; port each add-on to its `addon.json` (+ hooks.py where needed: exasol-scheduler DB user, json-tables cargo shim); legacy module pairs deleted one by one after `tests/legacy/marketplace.sh` equivalents pass in `tests/unit`
- [ ] B3 `app/skills.py` (place, retire, allowlist) + tests from `tests/legacy/skills.sh`
- [ ] B4 `app/mcp.py`: move `mcp/` into `exakit/adapters/clients` + `app/mcp.py`; `mcp-setup`, `mcp-status`, `mcp-doctor`, `mcp-remove`; `mcp/tests` moved to `tests/unit/clients`
- [ ] B5 `adapters/exapump.py` + `app/data.py` (bundled datasets, files, folders, resume) + `cli/data.py`, `cli/sql.py`, `cli/logs.py`
- [ ] B6 `app/persona.py` apply + acceptance A21 to A24
- [ ] B7 Retire the legacy suites for these areas; CI roster updated

## Phase C: install, update, runtime, uninstall

- [ ] C1 `adapters/runtime/personal.py` + `podman.py` + `adapters/process/services.py` (launchd, systemd, Task Scheduler) + fakes
- [ ] C2 `app/install.py` (steps, resume, soft failures, legacy crossing, closing sequence, persona answers) + e2e dry-run matrix
- [ ] C3 `app/update.py` (self-update stage/swap/backup, per component, heavy runtime gate, notice)
- [ ] C4 `app/runtime.py` (start, stop, repair-runtime, autostart, migrate docker-nano)
- [ ] C5 `app/uninstall.py` (menu, typed confirmation, snapshots kept, add-on removal)
- [ ] C6 `install.sh` / `install.ps1` hand over to `python -m exakit install` for the whole run; `setup/setup-*.{sh,ps1}` deleted

## Phase D: delete the legacy tree

- [ ] D1 `setup/` deleted; `tests/legacy/` empty; `MIGRATED_COMMANDS` removed (everything is Python)
- [ ] D2 `CLAUDE.md`, `MARKETPLACE.md`, `AGENTS.md` describe only the Python kit
- [ ] D3 Optional: `ui/tui/` on Textual in the kit venv, `exakit ui` command (decision A3)
