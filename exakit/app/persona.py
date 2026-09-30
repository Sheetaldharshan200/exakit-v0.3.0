"""``exakit persona``: list, show, plan (Phase A); apply arrives with the lifecycles (Phase B)."""

from __future__ import annotations

from typing import Any

from exakit.domain.catalog import Persona
from exakit.domain.persona import answers_for, plan_for
from exakit.domain.plan import Plan
from exakit.domain.result import Result

from . import Context
from .machine import all_datasets, probe


def recorded(ctx: Context) -> str | None:
    manifest = ctx.manifest_or_none()
    return manifest.persona_id() if manifest else None


def list_personas(ctx: Context) -> Result:
    current = recorded(ctx)
    personas = ctx.catalog.personas()
    data: dict[str, Any] = {
        "recorded": current,
        "personas": [{"id": p.id, "title": p.title, "summary": p.summary, "source": p.source, "recorded": p.id == current}
                     for p in personas],
    }
    if not ctx.json:
        _render_list(ctx, personas, current)
    return Result(True, "recorded" if current else "none", data=data)


def _render_list(ctx: Context, personas: list[Persona], current: str | None) -> None:
    if not personas:
        ctx.ui.warn("This kit copy ships no personas.")
        return
    for p in personas:
        mark = "* " if p.id == current else "  "
        yours = " (yours)" if p.source == "user" else ""
        ctx.ui.text(f"  {mark}{p.id:<16} {p.title}")
        ctx.ui.text(f"    {'':<16} {p.summary}{yours}")
    ctx.ui.text("")
    if current:
        ctx.ui.info(f"Recorded on this machine: {current}. See what is left: exakit persona plan {current}")
    else:
        ctx.ui.info("See what one would add: exakit persona plan <id>   Apply it: exakit persona apply <id>")


def show(ctx: Context, persona_id: str) -> Result:
    persona = ctx.catalog.persona(persona_id)
    doc = persona.to_dict()
    if not ctx.json:
        def cell(value: Any) -> str:
            return value if isinstance(value, str) else ", ".join(value)
        origin = "your file: " if persona.source == "user" else "shipped with the kit: "
        ctx.ui.panel(f"Persona: {persona.title} ({persona.id})", [
            persona.summary, "",
            f"Sample data:  {cell(doc['datasets'])}", f"AI clients:   {cell(doc['mcp_clients'])}",
            f"Add-ons:      {cell(doc['addons'])}", f"AI skills:    {doc['skills']}", "",
            f"{origin}{persona.path}",
        ])
    return Result(True, "ok", data={**doc, "source": persona.source}, raw=True)


def build_plan(ctx: Context, persona: Persona) -> Plan:
    manifest = ctx.manifest_or_none()
    machine = probe(ctx, manifest)
    answers = answers_for(persona, ctx.env, all_datasets=list(machine.all_datasets))
    return plan_for(persona, machine, answers)


def plan(ctx: Context, persona_id: str) -> Result:
    persona = ctx.catalog.persona(persona_id)
    the_plan = build_plan(ctx, persona)
    pending = len(the_plan.pending())
    data = {"persona": {"id": persona.id, "title": persona.title, "source": persona.source}, **the_plan.to_dict()}
    if not ctx.json:
        ctx.ui.plan(the_plan)
        if pending:
            ctx.ui.info(f"Apply it with: exakit persona apply {persona.id}")
        else:
            ctx.ui.ok("Everything this persona asks for is already on this machine.")
    return Result(True, "complete" if pending == 0 else "pending",
                  remedy=None if pending == 0 else f"exakit persona apply {persona.id} --yes", data=data)


def install_env(ctx: Context, persona_id: str) -> dict[str, str]:
    """The environment that makes the (legacy) installer follow this persona; explicit answers win."""
    persona = ctx.catalog.persona(persona_id)
    answers = answers_for(persona, ctx.env, all_datasets=all_datasets(ctx))
    env = answers.env()
    if "addons" not in answers.explicit and not isinstance(answers.addons, str):
        manifest = ctx.manifest_or_none()
        machine = probe(ctx, manifest, need={"addons"})
        runnable = [a for a in answers.addons if machine.addon_states.get(a, ("", ""))[0] in ("available", "installed")]
        env["EXAKIT_MARKETPLACE_ADDONS"] = ",".join(runnable) or "none"
    env["EXAKIT_PERSONA_ACTIVE"] = "1"
    return env
