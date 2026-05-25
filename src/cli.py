"""`triage` CLI entrypoint.

Commands:
    triage route "<alert>"          run V1 router only
    triage plan "<alert>"           run V2 planner pipeline
    triage agent "<alert>"          run V3 ReAct agent and stream trace
    triage list-runbooks            list ingested runbooks
    triage info                     show active prompt config + models
"""

from __future__ import annotations

import json
import sys
from typing import Optional

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

load_dotenv()

from .agent import ReactAgent
from .config import load_prompt_config, settings
from .planner import PlannerAgent
from .retrieval import RunbookIndex
from .router import RouterAgent


app = typer.Typer(add_completion=False, no_args_is_help=True)
console = Console()


def _need_openai() -> None:
    if not settings.openai_api_key:
        console.print("[red]OPENAI_API_KEY is not set. Add it to .env.[/red]")
        sys.exit(1)


@app.command()
def route(
    alert: str = typer.Argument(..., help="Alert text to classify"),
    prompt_version: Optional[str] = typer.Option(None, "--prompt", help="Prompt config version, e.g. v1"),
) -> None:
    """V1 router only — single LLM classification call."""
    _need_openai()
    cfg = load_prompt_config(version=prompt_version)
    router = RouterAgent(prompt_config=cfg)
    result = router.route(alert)
    console.print(Panel(f"category: [bold]{result.category.value}[/bold]\nrationale: {result.rationale or '(none)'}",
                        title="V1 router"))


@app.command()
def plan(
    alert: str = typer.Argument(..., help="Alert text"),
    prompt_version: Optional[str] = typer.Option(None, "--prompt"),
) -> None:
    """V2 planner pipeline — router → retrieve → plan."""
    _need_openai()
    cfg = load_prompt_config(version=prompt_version)
    router = RouterAgent(prompt_config=cfg)
    index = RunbookIndex(runbook_dir=settings.runbook_dir)
    planner = PlannerAgent(router=router, index=index, prompt_config=cfg)
    p = planner.plan(alert)

    console.print(Panel(
        f"category: [bold]{p.category.value}[/bold]\nprimary_runbook: {p.primary_runbook or '(none — escalate)'}",
        title="V2 planner",
    ))
    if p.steps:
        table = Table(title="Plan steps")
        table.add_column("#", style="dim")
        table.add_column("step")
        table.add_column("why", style="dim")
        for i, s in enumerate(p.steps, 1):
            table.add_row(str(i), s.step, s.why)
        console.print(table)

    rt = Table(title="Retrieval (top-3 BM25)")
    rt.add_column("runbook_id", style="cyan")
    rt.add_column("score", justify="right")
    rt.add_column("title", style="dim")
    for hit in p.retrieval_hits:
        rt.add_row(hit.runbook.runbook_id, f"{hit.score:.2f}", hit.runbook.title)
    console.print(rt)


@app.command()
def agent(
    alert: str = typer.Argument(..., help="Alert text"),
    prompt_version: Optional[str] = typer.Option(None, "--prompt"),
    max_iterations: Optional[int] = typer.Option(None, "--max-iter"),
) -> None:
    """V3 ReAct agent — observe / reason / act loop with tool calling."""
    _need_openai()
    cfg = load_prompt_config(version=prompt_version)
    index = RunbookIndex(runbook_dir=settings.runbook_dir)
    a = ReactAgent(index=index, prompt_config=cfg, max_iterations=max_iterations)
    r = a.run(alert)
    console.print(ReactAgent.format_trace(r))


@app.command("list-runbooks")
def list_runbooks() -> None:
    index = RunbookIndex(runbook_dir=settings.runbook_dir)
    table = Table(title=f"Runbooks in {settings.runbook_dir}")
    table.add_column("id", style="cyan")
    table.add_column("category", style="dim")
    table.add_column("title")
    for rb in index.runbooks:
        table.add_row(rb.runbook_id, rb.category or "?", rb.title)
    console.print(table)


@app.command()
def info() -> None:
    cfg = load_prompt_config()
    table = Table(title="Active configuration")
    table.add_column("key", style="cyan")
    table.add_column("value")
    table.add_row("prompt version", cfg.version)
    table.add_row("router_model", cfg.router_model())
    table.add_row("planner_model", cfg.planner_model())
    table.add_row("agent_model", cfg.agent_model())
    table.add_row("judge_model", cfg.judge_model())
    table.add_row("max_agent_iterations", str(cfg.agent.max_iterations))
    table.add_row("retrieval.top_k", str(cfg.retrieval.top_k))
    table.add_row("runbook_dir", settings.runbook_dir)
    table.add_row("prompts_dir", settings.prompts_dir)
    console.print(table)


if __name__ == "__main__":
    app()
