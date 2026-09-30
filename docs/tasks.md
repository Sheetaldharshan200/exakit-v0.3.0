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

- [x] B1 `lifecycles/{__init__,base,python_venv,binary,host_extension}.py`; per-add-on modules `exakit/addons/{dash_server,dbt_exasol,json_tables,exasol_scheduler}.py` (exasol-vscode is the generic host extension); `tests/unit/lifecycles/test_addons.py` (D16)
- [x] B2 `app/marketplace.py` (list, scripted and menu answers, install loop, `install_addon_quietly`, `uninstall <addon>`), `app/services.py`; `marketplace` and add-on `uninstall` migrated (the full uninstall stays legacy, D18); `tests/unit/app/test_marketplace.py` + contract shapes. The legacy `.sh`/`.ps1` add-on modules stay until C4 retires the legacy start/stop/autostart (D17)
- [x] B3 `app/skills.py` (place, retire, allowlist, per-add-on) + `tests/unit/app/test_skills.py`
- [x] B4 `app/mcp.py` (setup, status, doctor, remove, read-only user, add-on endpoints) over `adapters/clients` calling `mcp/` in process (D15; the package move is Phase C); `app/runtime_ops.py` self-heal; `tests/unit/app/test_mcp.py`
- [x] B5 `adapters/exapump.py` + `app/{data,data_files,sql,logs}.py` (bundled datasets, files with cut-short recovery, folders with receipts, JSON through json-tables) + CLI wiring; `tests/unit/app/{test_data,test_sql_logs}.py`
- [x] B6 `app/persona.py` apply through `run_plan` (datasets via data, clients via mcp, add-ons via marketplace, skills via skills; records `persona.*`); `tests/unit/app/test_persona_apply.py` + contract; acceptance A21 to A24
- [x] B8 Every function in `exakit/` is under 40 lines and every module under 400 (`data_folder.py` and `mcp_readonly.py` split out of `data_files.py` and `mcp.py`); an ast check in the test run record proves it
- [ ] B7 Retire the legacy suites for these areas once C4 deletes the legacy add-on modules they cover; CI roster runs the Python suites already (`versions.yml`)

## Phase C: install, update, runtime, uninstall

- [x] C1 `adapters/runtime/personal.py` (status decision tree, start/stop/wait/reap/deploy/record) + `adapters/process/services.py` (launchd, systemd user, Windows Startup) + `adapters/fs/notes.py` (failure note, install-lock holder) + fakes. `podman.py` is not needed: the container runtime is legacy-only and reaches Python solely through `migrate docker-nano` (C4)
- [x] C2 `app/install.py` + `app/install_steps.py` (six ticked steps with resume, artifact and version-drift reruns, soft failures reported once, the persona's answers folded into the environment, the closing sequence), `app/deploy.py` (the deployment decision tree: reuse, start, replace with consent, deploy fresh), `app/requirements.py` (the compatibility gate, Podman on Linux, `exakit preflight`), `adapters/platform/machine.py`; `tests/unit/app/{test_install,test_deploy_requirements_migrate}.py` + contract PhaseCCommandsTest (D23, D24)
- [x] C3 `exakit/components/{base,exapump,mcp_server,pyexasol,personal,kit,skill_set}.py` (one lifecycle per kit part: install, validate, update, uninstall) + `adapters/clients/handshake.py` + `app/update.py` (targets, ahead/current/unsupported/min-kit rules, the runtime offer with `--yes`/`EXAKIT_CONFIRM_RUNTIME_UPDATE`, kit self-update stage/swap/backup/marker, skills re-placed, what's-new card); `tests/unit/components/test_components.py`, `tests/unit/app/test_update.py` (D22). Left for C2: the exapump glibc container shim (Linux with glibc < 2.38) still comes from the legacy installer
- [x] C4a `app/status.py`, `app/info.py` (the tri-state queries, every AGENTS.md key, `datasets_source`), `app/runtime.py` (`start` with orphan reaping, `stop`, `autostart`); `tests/unit/app/test_status_info_runtime.py` + contract StateQueryPhaseCTest (D21)
- [x] C4b `app/repair.py` (consent, exit 5 when declined, the installer re-run in process with a forced fresh deployment) and `app/legacy_db.py` + `app/legacy_crossing.py` + `app/migrate.py` (the docker-nano crossing: asked once during the install, `exakit migrate docker-nano` afterwards) over `adapters/process/containers.py`
- [x] C5 `app/uninstall.py` (the safe-target rule, the legacy removal order, the menu with the typed UNINSTALL gate, `--yes`, `--dry-run`, snapshots kept); `tests/unit/app/test_uninstall_repair.py`
- [ ] C6 `install.sh` / `install.ps1` already hand over to `python -m exakit install`; delete `setup/setup-*.{sh,ps1}` and the `cli/legacy.py` install path once a real install has been run on macOS, Linux and Windows through the Python path (manual acceptance M-3, M-5). `exakit guide` and the kit2 scripts are the last legacy passthroughs

## Phase D: delete the legacy tree

- [ ] D1 `setup/` deleted; `tests/legacy/` empty; `MIGRATED_COMMANDS` removed (everything is Python)
- [ ] D2 `CLAUDE.md`, `MARKETPLACE.md`, `AGENTS.md` describe only the Python kit
- [ ] D3 Optional: `ui/tui/` on Textual in the kit venv, `exakit ui` command (decision A3)
