# Test plan and acceptance criteria

Status: living document. Every row maps to a requirement in
[requirements.md](requirements.md) and to a check in `tests/persona.sh` or
`tests/persona.ps1` unless marked *manual*. Update the result column in the
same commit as the change.

## 1. How the suites run

```bash
python3 -m unittest discover -s tests/unit -t .        # pure rules and adapters with fakes; no machine state
python3 -m unittest discover -s tests/contract -t .    # the frozen --json shapes and exit codes, against the real CLI in a sandbox
python3 -m unittest discover -s tests/e2e -t .         # installer dry run, launcher answers, update-path layout
EXAKIT_E2E_NETWORK=1 python3 -m unittest tests.e2e.test_bootstrap_network   # the real uv + CPython bootstrap (opt in)
bash tests/<legacy-suite>.sh                            # the legacy suites, unchanged, against setup/legacy-exakit
```

The acceptance rows below name the suite that proves each one. Rows that
belong to `persona apply` (A21 to A24) are Phase B and are marked pending.

## 2. Acceptance criteria (personas)

| Id | Given | When | Then | Req | Check |
|---|---|---|---|---|---|
| A1 | a fresh sandbox | `exakit_persona_ids` | prints `analyst data-engineer data-scientist minimal`, sorted | R15 | persona.sh: registry |
| A2 | every shipped file | validated | schema 1, id equals filename, ASCII, canonical json.tool layout, LF, title at most 40 chars, summary at most 120 | R14, R17 | persona.sh: files |
| A3 | every shipped file | ids cross-checked | every dataset is bundled, every add-on registered, every client accepted by `exakit_parse_mcp_client_selection`, `skills` is `all` | R17 | persona.sh: files |
| A4 | a user file `$EXAKIT_HOME/personas/team-x.json` | `exakit_persona_ids` | includes `team-x`, source `user` | R16 | persona.sh: user dir |
| A5 | a user file named `analyst.json` with a different title | `exakit_persona_field analyst title` | the user title wins | R16 | persona.sh: shadowing |
| A6 | a user file that is not JSON, and one with schema_version 99 | `exakit_persona_ids` | both are skipped with one warning each, the rest still listed, exit 0 | R16 | persona.sh: broken files |
| A7 | `EXAKIT_PERSONA=data-scientist`, no other env | `exakit_persona_apply_env` | exports `EXAKIT_DATASETS=tpch,energy,weather`, `EXAKIT_MCP_CLIENTS=all`, `EXAKIT_PERSONA_ACTIVE=1`; manifest has `persona.id`, `persona.source=install`, `persona.requested_at` | R1, R4 | persona.sh: expansion |
| A8 | `EXAKIT_PERSONA=data-scientist EXAKIT_DATASETS=tpch EXAKIT_MCP_CLIENTS=codex` | `exakit_persona_apply_env` | the explicit values are untouched | R2 | persona.sh: precedence |
| A9 | `EXAKIT_PERSONA=minimal` | `exakit_persona_apply_env` | `EXAKIT_LOAD_SAMPLE=0`, `EXAKIT_MCP_CLIENTS=skip`, `EXAKIT_DATASETS` unset | design 4 | persona.sh: minimal |
| A10 | `EXAKIT_PERSONA=nope` | `exakit_persona_apply_env` | dies before any step, message names the known ids, nothing recorded | R3 | persona.sh: unknown |
| A11 | `data-engineer`, no `code` CLI on PATH, json-tables engine stubbed absent | `exakit_persona_addons_answer` | prints `dbt-exasol,exasol-scheduler`; `EXAKIT_PERSONA_SKIPPED` names exasol-vscode and json-tables with their reasons; no `die` | design 3, D4 | persona.sh: add-on filter |
| A12 | `analyst`, dash-server already installed (stub `dash_server_installed_version`) | `exakit_persona_addons_answer` | prints `none` | design 3 | persona.sh: add-on filter |
| A13 | `EXAKIT_PERSONA_ACTIVE=1`, `EXAKIT_MARKETPLACE_ADDONS` unset | `exakit_marketplace_offer` (menu stubbed) | the menu sees `EXAKIT_MARKETPLACE_ADDONS` equal to the persona answer | design 3 | persona.sh: offer hook |
| A14 | `EXAKIT_PERSONA_ACTIVE` unset, `persona.id` recorded from an earlier run | `exakit_marketplace_offer` | the persona does not answer; existing behaviour | design 3 | persona.sh: offer hook |
| A15 | no manifest | `exakit persona list --json` | exit 4, one JSON object with `installed:false`, `status`, `remedy` | R12 | persona.sh: CLI |
| A16 | a sandbox manifest | `exakit persona list --json` | exit 0, `installed:true`, `status:"none"`, `recorded:null`, 4 personas each with `id`, `title`, `summary`, `source`, `recorded` | R7 | persona.sh: CLI |
| A17 | manifest with `persona.id=analyst` | `exakit persona list` | the analyst row is marked; `--json` `recorded:"analyst"` and `status:"recorded"` | R7 | persona.sh: CLI |
| A18 | `exakit persona show data-scientist --json` | | the file's fields, exit 0; `show nope` exits 2 with the refusal object under `--json` | R10, R12 | persona.sh: CLI |
| A19 | sandbox with tpch loaded, no clients connected, no add-ons, skills current | `exakit persona plan data-scientist --json` | `datasets`: tpch done, energy pending, weather pending; `mcp_clients` from the stubbed discovery; `addons` states; `skills.state:"done"`; `pending` equals the count; `remedy` is the `apply --yes` command | R9 | persona.sh: plan |
| A20 | same, everything already there | `exakit persona plan analyst --json` | `status:"complete"`, `pending:0`, `remedy:null` | R9 | persona.sh: plan |
| A21 | no terminal, no `--yes` | `exakit persona apply analyst` | prints the plan, exits 5, last line names `exakit persona apply analyst --yes`; nothing recorded | R8, D6 | persona.sh: apply |
| A22 | `--yes`, every downstream function stubbed to succeed | `exakit persona apply data-scientist --yes --json` | calls the data loader with `EXAKIT_DATASETS=energy,weather` (pending only), `exakit_mcp_setup` with `EXAKIT_MCP_CLIENTS=all`, the marketplace with the filtered csv, `exakit_install_skills`; records `persona.source=apply`, `persona.applied_at`; `status:"applied"`, exit 0 | R8 | persona.sh: apply |
| A23 | `--yes`, the marketplace stub fails | `exakit persona apply data-scientist --yes --json` | the other sections still run; `status:"partial"`, `failed[]` names the add-on, `remedy` is `exakit marketplace <id>`; exit 1 | R8 | persona.sh: apply |
| A24 | `--yes`, `minimal` | `exakit persona apply minimal --yes` | no loader, no MCP setup, no marketplace call; skills placed; exit 0 | design 4 | persona.sh: apply |
| A25 | `exakit persona apply` (no id), `exakit persona bogus`, `exakit persona list --nope` | | exit 2 each; JSON refusal object when `--json` present | R12 | persona.sh: CLI |
| A26 | manifest with `persona.id` | `exakit status --json` | carries `"persona":"<id>"`; without the block, `"persona":null` | R13 | persona.sh: status |
| A27 | `setup/help/exakit.json` | `exakit help persona`, `exakit catalog`, `exakit help --json` | all know the command; the Personas group exists | R13 | persona.sh: help |
| A28 | docs | grep | `AGENTS.md` env table has `EXAKIT_PERSONA` and names every shipped persona id; `README.md` has `exakit persona`; each `quickstarts/*.md` shows the one-line persona install; `install.sh` and `install.ps1` headers list the variable | R20 | persona.sh: docs |
| A29 | `setup/whats-new.json` | `tests/whats-new.sh` | a `0.3.0` card that passes the line rules; `versions.json` `kit.version` is `0.3.0` | R18 | persona.sh + whats-new.sh |
| A30 | PowerShell files | static | every name in design 6 is defined; `persona.ps1` is ASCII; `setup-windows.ps1` calls `Set-ExakitPersonaEnvironment`; `Request-ExakitMarketplaceOffer` calls `Get-ExakitPersonaAddonsAnswer`; `Invoke-CmdStatus` emits `persona` | C6, design 6 | persona.sh: parity |
| A31 | pwsh present | live pwsh | `Get-ExakitPersonaIds` lists the same four; `Set-ExakitPersonaEnvironment data-scientist` sets the same env values as A7; unknown id throws | design 6 | persona.sh: pwsh block; persona.ps1 |
| A32 | the existing suites | run | `marketplace.sh`, `skills.sh`, `agent-operability.sh`, `agents-rosters.sh`, `whats-new.sh`, `ps-encoding-guard.sh`, `ps-undefined-functions.sh`, `ps-table-twin.sh`, `bash32-guard.sh`, `dry-run-matrix.sh`, `noninteractive-answers.sh`, `versions-manifest.sh`, `help` checks in `agent-audit.sh` still pass | C6 | section 5 |

## 3. Combination matrix

Personas x answers x platform x mode. Each cell is covered by the check named.

| Dimension | Values | Covered by |
|---|---|---|
| persona | analyst, data-scientist, data-engineer, minimal, user-defined, shadowing, unknown, broken | A1 to A10 |
| explicit env per variable | unset / set for each of DATASETS, LOAD_SAMPLE, MCP_CLIENTS, SKIP_MCP, MARKETPLACE_ADDONS | A7, A8, A13 (SKIP_MCP=1 and LOAD_SAMPLE set are asserted untouched in A8's block) |
| add-on availability | applicable+absent, applicable+installed, applicable+system-present, inapplicable, module missing | A11, A12, A19 |
| datasets state | none loaded, some loaded, all loaded | A19, A20 |
| MCP clients state | none detected, some pending, all connected, persona says skip | A19, A20, A24 |
| terminal | tty (interactive confirm), no tty with --yes, no tty without --yes | A21, A22 (manual: interactive path, section 4) |
| output | human, --json | every CLI row runs both |
| install entry | fresh install with EXAKIT_PERSONA, re-run over existing, apply on existing | A7, A13, A22 |
| platform | bash 3.2 (macOS), bash (Ubuntu), pwsh 7 (macOS/Ubuntu), Windows PowerShell 5.1 (windows-latest) | CI matrix; A30, A31 |
| kit copy age | new copy (module present), old copy without `persona.sh` (loader is a no-op, installer unchanged) | A14 plus the loader guard |

## 4. Manual acceptance (before merge, record the outcome here)

| Id | Steps | Expected | Result |
|---|---|---|---|
| M-1 | On this Mac: `EXAKIT_LOCAL_KIT=$PWD EXAKIT_DRY_RUN=1 EXAKIT_PERSONA=data-scientist sh install.sh` | plan shown, nothing installed, no error | pending |
| M-2 | `EXAKIT_LOCAL_KIT=$PWD EXAKIT_PERSONA=nope sh install.sh` | stops before step 1 naming the four ids | pending |
| M-3 | Full install on a scratch machine or VM with `EXAKIT_PERSONA=analyst` | tpch loaded, detected clients connected, dash-server installed, `exakit info --json` shows the persona block | pending |
| M-4 | On a 0.2.0 install: `exakit update`, then `exakit persona list`, `exakit persona plan data-scientist`, `exakit persona apply data-scientist` interactively | update pulls 0.3.0 and shows the card; commands work; the confirm question appears once | pending |
| M-5 | Windows 11 (PowerShell 5.1): `$env:EXAKIT_PERSONA='data-engineer'; irm .../install.ps1 \| iex` | exasol-vscode skipped with the reason when VS Code is absent, the rest installed | pending |

## 5. Latest local run

Recorded on 2026-09-30 on this Mac (macOS, bash 3.2, pwsh 7, Python 3.12.10).

| Suite | Result |
|---|---|
| tests/unit (132 tests) | pass |
| tests/contract (15 tests) | pass |
| tests/e2e (9 tests) | pass |
| tests/e2e/test_bootstrap_network (real uv 0.12.21 + CPython 3.12.14) | pass, 5 s |
| tests/whats-new.sh | pass |
| tests/skills.sh | pass |
| tests/ps-encoding-guard.sh | pass |
| tests/ps-parse.ps1 | pass |
| tests/ps51-json-contracts.ps1 | pass |
| remaining legacy suites | see the commit message of the run that recorded them |
