# Claude Code notes for this repo

**Installing the kit?** Follow [AGENTS.md](AGENTS.md) — it is the full agent
runbook (install command, env-var answers, verification, uninstall).

Claude-Code-specific tips:

- The macOS first install deploys a database — **usually in under 2 minutes**.
  Run the install command **in the background** and poll `exakit status`
  until it reports running — do not treat a long-running or timed-out
  foreground call as a failure. Re-running the installer is safe; it resumes.
- Answer install choices with env vars using **names, not menu numbers**
  (e.g. `EXAKIT_MCP_CLIENTS=claude,codex`, `EXAKIT_DATASETS=tpch`), or name a
  persona: `EXAKIT_PERSONA=data-scientist`.
- Never print or log database passwords; they live in files under
  `~/.exasol-starter-kit/credentials/` and scripts read them from there.

## Working on the code in this repo

The kit is **one Python implementation** (`exakit/`), bootstrapped by a tiny
shell layer (`bootstrap/`, `install.sh`, `install.ps1`). Read
[docs/architecture.md](docs/architecture.md) (the approved shape),
[docs/design.md](docs/design.md) (module map, schemas, contracts, coding
standard) and [docs/tasks.md](docs/tasks.md) (what is done and what is next)
before changing anything. Update those three documents in the same commit
as the change they describe.

- **Layers point down only.** `cli -> ui / app -> domain`, `app -> adapters`
  (behind Protocols) `-> the machine`. `domain/` does no IO and imports
  nothing from the other layers. No `subprocess`, `open`, `urllib` or
  `os.environ` writes outside `adapters/`.
- **Exit codes live in one file**, `exakit/domain/errors.py`, as exception
  classes (2 bad input, 3 not running, 4 not installed, 5 not confirmed,
  1 failed). Raise them; only `app.run_plan` and `cli.main` catch them.
- **Every command answers with one `Result`** (installed, status, remedy,
  then its own keys). Under `--json` that object is the only thing on stdout.
  A remedy is a runnable command or `None`, never a sentence.
- **Plan, then apply.** A mutating command builds a `Plan`, shows it,
  confirms (or `--yes`, or exits 5 without a terminal), and runs it through
  `app.run_plan` — the one apply loop in the kit.
- **Standard library only** in `exakit/`, Python 3.11+, type hints,
  dataclasses, `Protocol` for adapters, a module at most 400 lines, a
  function at most 40.
- **Adding a persona?** One file, `catalog/personas/<id>.json` (schema in
  docs/design.md 3.3). `tests/unit/domain/test_catalog.py` validates every
  shipped file; name the id in AGENTS.md. Nothing in code names a persona.
- **Adding an add-on?** One file, `catalog/addons/<id>/addon.json` (schema
  3.2), its `setup/help/<id>.json` and its `skills/<id>/SKILL.md` with an
  `addon:` key, plus the `components.<id>` block in `versions.json`. Code
  (`hooks.py`) only for behaviour a generic lifecycle cannot express. Never
  a `.sh` + `.ps1` module pair.
- **Adding a component?** One file, `catalog/components/<id>.json`, plus its
  `versions.json` entry.
- **Adding an AI skill?** Unchanged: `skills/<name>/SKILL.md` with `name` and
  `description` frontmatter (ending in a `Triggers —` list), a row in
  `skills/README.md`, and a bump of `components.skills.version`.
- **Tests:** `python3 -m unittest discover -s tests/unit -t .` (no machine
  state), `-s tests/contract` (the frozen `--json` shapes and exit codes
  against the real CLI in a sandbox), `-s tests/e2e` (installer dry run,
  launcher). One behaviour per test; fakes from `tests/unit/fakes.py`, never
  the network.
- **The legacy tree (`setup/`) is frozen.** It still runs the commands Python
  has not taken over (`exakit/cli/main.py` lists the migrated set) and is
  deleted phase by phase. Fix a bug there only when the same fix is not yet
  scheduled in Python; never add a feature there. Its own suites stay at
  `tests/*.sh` and `tests/*.ps1` until the code they cover is gone. Shell
  there stays bash 3.2 and PowerShell 5.1 compatible; `bootstrap/*.ps1`
  stays ASCII-only.
- Do not add AI attribution to commits, PRs, code, or docs.
