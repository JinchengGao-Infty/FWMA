"""FWMA CLI — AI Parliament-driven literature review."""

# ruff: noqa: I001
# pyright: reportMissingImports=false

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
from rich.table import Table

ALL_STEPS = ("crawl", "screen", "download", "review", "report")

app = typer.Typer(
    name="fwma",
    help="AI Parliament-driven systematic literature review.",
    rich_markup_mode="rich",
    no_args_is_help=True,
)


@app.callback()
def main_callback(
    verbose: int = typer.Option(0, "--verbose", "-v", count=True, help="Verbosity level (-v info, -vv debug)"),
) -> None:
    """FWMA — AI Parliament-driven systematic literature review."""
    import logging

    level = logging.WARNING
    if verbose == 1:
        level = logging.INFO
    elif verbose >= 2:
        level = logging.DEBUG
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")


tools_app = typer.Typer(name="tools", help="Standalone tools (pdf-vision, citation-check).")
app.add_typer(tools_app)

console = Console()
ALL_STEPS = ("crawl", "screen", "download", "review", "report")


def _load_config() -> Any:
    """Load global config with backward-compatible fallback."""
    import fwma.core.config as config_module

    loader = getattr(config_module, "load_config", None)
    if callable(loader):
        return loader()
    return config_module.FWMAConfig.load()


def _load_research_config(config_path: Path) -> dict[str, Any]:
    import fwma.core.config as config_module

    loader = getattr(config_module, "load_research_config", None)
    if callable(loader):
        loaded = loader(config_path)
        if isinstance(loaded, dict):
            return loaded
        raise TypeError("load_research_config must return a dict")

    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef]

    with open(config_path, "rb") as handle:
        data = tomllib.load(handle)

    requirement = data.get("requirement") or data.get("research", {}).get("requirement")
    sources = data.get("sources") or data.get("research", {}).get("sources") or []
    if not requirement or not sources:
        raise ValueError("Config must contain 'requirement' and 'sources'.")
    return {
        "requirement": requirement,
        "sources": sources,
        "name": data.get("name", config_path.stem),
        "run_id": data.get("run_id"),
    }


def _print_dict(title: str, payload: dict[str, Any]) -> None:
    console.print(Panel(json.dumps(payload, ensure_ascii=False, indent=2), title=title, border_style="cyan"))


def _show_run_status(service: Any, run_id: str) -> None:
    status = service.run_status(run_id)
    table = Table(title=f"Run Status: {run_id}")
    table.add_column("Field", style="bold")
    table.add_column("Value")
    for key in ("status", "created_at", "updated_at", "current_step"):
        if key in status and status[key] is not None:
            table.add_row(key, str(status[key]))
    console.print(table)


def _extract_run_id(run_dir: Path) -> str:
    # Accept either a raw run_id or a path ending with run_id.
    return run_dir.name if run_dir.name else str(run_dir)


def _wait_for_job(service: Any, job_id: str, description: str) -> dict[str, Any]:
    """Poll async job status with rich progress UI."""
    final_status: dict[str, Any] = {}
    with Progress(SpinnerColumn(), TextColumn("{task.description}"), BarColumn(), console=console) as progress:
        task = progress.add_task(description, total=None)
        while True:
            final_status = service.get_job_status(job_id)
            progress_info = final_status.get("progress") or {}
            if progress_info.get("total"):
                progress.update(
                    task,
                    total=progress_info["total"],
                    completed=progress_info.get("current", 0),
                    description=f"{description}: {progress_info.get('message', '')}",
                )
            if final_status.get("status") in {"succeeded", "completed", "failed", "cancelled"}:
                break
            time.sleep(2)

    if final_status.get("status") in {"failed", "cancelled"}:
        console.print(f"[bold red]Job failed:[/bold red] {final_status.get('error', 'Unknown error')}")
        raise typer.Exit(1)
    console.print("  [green]Done[/green]")
    return final_status


@app.command()
def suggest(
    requirement: str = typer.Argument(..., help="Research requirement in natural language"),
    model: str = typer.Option(None, help="LLM model for suggestion generation"),
):
    """AI-powered search strategy suggestion."""
    _load_config()
    from fwma.core.service import FWMAService

    service = FWMAService()
    with console.status("Generating search strategy..."):
        if model:
            try:
                result = service.suggest_sources(requirement, model=model)
            except TypeError:
                result = service.suggest_sources(requirement)
        else:
            result = service.suggest_sources(requirement)
    _print_dict("Suggested Sources", result if isinstance(result, dict) else {"result": result})


@app.command()
def run(
    config: Path = typer.Argument(..., help="Path to research config TOML file"),
    steps: str = typer.Option(None, help="Comma-separated steps to run (crawl,screen,download,review,report)"),
    resume: bool = typer.Option(True, help="Resume from last checkpoint"),
):
    """Run full research pipeline from config file."""
    del resume
    _load_config()
    from fwma.core.service import FWMAService

    if not config.exists():
        console.print(f"[red]Config file not found:[/red] {config}")
        raise typer.Exit(1)

    research = _load_research_config(config)
    service = FWMAService()
    run_info = service.create_run(
        requirement=research["requirement"],
        sources=research["sources"],
        name=research.get("name", config.stem),
        run_id=research.get("run_id"),
    )
    run_id = run_info.get("run_id")
    if not run_id:
        console.print("[red]create_run did not return run_id.[/red]")
        raise typer.Exit(1)

    console.print(f"Created run: [bold]{run_id}[/bold]")
    requested_steps = [item.strip() for item in steps.split(",")] if steps else list(ALL_STEPS)
    invalid = [step for step in requested_steps if step not in ALL_STEPS]
    if invalid:
        console.print(f"[red]Invalid steps:[/red] {', '.join(invalid)}")
        raise typer.Exit(1)

    for step in requested_steps:
        if step == "crawl":
            console.print("\n[bold blue]Step 1: Crawling papers...[/bold blue]")
            result = service.crawl(run_id)
            console.print(f"  Found {result.get('papers_count', 'N/A')} papers")
        elif step == "screen":
            console.print("\n[bold blue]Step 2: Screening papers...[/bold blue]")
            result = service.screen(run_id, threshold="high_medium")
            console.print(f"  Screened: {result.get('screened_count', 'N/A')} papers passed")
        elif step == "download":
            console.print("\n[bold blue]Step 3: Downloading PDFs...[/bold blue]")
            job_id = service.download_async(run_id, concurrency=8)
            _wait_for_job(service, job_id, "Downloading")
        elif step == "review":
            console.print("\n[bold blue]Step 4: AI Parliament Review...[/bold blue]")
            job_id = service.review_async(run_id, max_rounds=5)
            _wait_for_job(service, job_id, "Reviewing")
        elif step == "report":
            console.print("\n[bold blue]Step 5: Generating Report...[/bold blue]")
            job_id = service.report_async(run_id, format="markdown")
            _wait_for_job(service, job_id, "Generating report")

    console.print(f"\n[bold green]Pipeline complete![/bold green] Run ID: {run_id}")
    _show_run_status(service, run_id)


@app.command()
def crawl(
    config: Path = typer.Argument(..., help="Path to research config TOML"),
    resume: bool = typer.Option(True, help="Resume from last checkpoint"),
):
    """Crawl papers from configured sources."""
    del resume
    _load_config()
    from fwma.core.service import FWMAService

    research = _load_research_config(config)
    service = FWMAService()
    run_info = service.create_run(
        research["requirement"], research["sources"], research.get("name", config.stem), research.get("run_id")
    )
    run_id = run_info["run_id"]
    result = service.crawl(run_id)
    _print_dict("Crawl Result", result)


@app.command()
def screen(
    run_dir: Path = typer.Option(Path("."), help="Run directory path"),
    threshold: str = typer.Option("high_medium", help="Screening threshold (high_only, high_medium, all_selected)"),
):
    """Screen papers for relevance using AI."""
    _load_config()
    from fwma.core.service import FWMAService

    service = FWMAService()
    run_id = _extract_run_id(run_dir)
    result = service.screen(run_id, threshold=threshold)
    _print_dict("Screen Result", result)


@app.command()
def download(
    run_dir: Path = typer.Option(Path("."), help="Run directory path"),
    concurrency: int = typer.Option(8, help="Concurrent downloads"),
    resume: bool = typer.Option(True, help="Skip already downloaded"),
):
    """Download PDFs for screened papers."""
    del resume
    _load_config()
    from fwma.core.service import FWMAService

    service = FWMAService()
    run_id = _extract_run_id(run_dir)
    job_id = service.download_async(run_id, concurrency=concurrency)
    _wait_for_job(service, job_id, "Downloading PDFs")
    _show_run_status(service, run_id)


@app.command()
def review(
    run_dir: Path = typer.Option(Path("."), help="Run directory path"),
    rounds: int = typer.Option(5, help="Max debate rounds"),
    resume: bool = typer.Option(True, help="Skip already reviewed"),
):
    """Review papers with AI Parliament debate."""
    del resume
    _load_config()
    from fwma.core.service import FWMAService

    service = FWMAService()
    run_id = _extract_run_id(run_dir)
    job_id = service.review_async(run_id, max_rounds=rounds)
    _wait_for_job(service, job_id, "AI Parliament review")
    _show_run_status(service, run_id)


@app.command()
def report(
    run_dir: Path = typer.Option(Path("."), help="Run directory path"),
    format: str = typer.Option("markdown", help="Output format (markdown, json, both)"),
):
    """Generate research summary report."""
    _load_config()
    from fwma.core.service import FWMAService

    service = FWMAService()
    run_id = _extract_run_id(run_dir)
    job_id = service.report_async(run_id, format=format)
    _wait_for_job(service, job_id, "Generating report")
    _show_run_status(service, run_id)


@app.command(name="runs")
def list_runs(
    runs_root: Path = typer.Option(None, "--runs-root", help="Runs root directory"),
) -> None:
    """List all research runs."""
    _load_config()
    from fwma.core.service import FWMAService

    service = FWMAService(runs_root=runs_root)
    runs = service.run_manager.list_runs()
    if not runs:
        console.print("[dim]No runs found.[/dim]")
        return

    table = Table(title="Research Runs")
    table.add_column("Run ID", style="bold cyan")
    table.add_column("Name")
    table.add_column("Created")
    table.add_column("Crawl", justify="center")
    table.add_column("Screen", justify="center")
    table.add_column("Download", justify="center")
    table.add_column("Review", justify="center")
    table.add_column("Report", justify="center")

    for r in runs:
        steps = r.get("steps", {})
        table.add_row(
            r.get("run_id", "?"),
            r.get("name", ""),
            r.get("created_at", "")[:19],
            "[green]✓[/green]" if steps.get("crawl") else "[dim]·[/dim]",
            "[green]✓[/green]" if steps.get("screen") else "[dim]·[/dim]",
            "[green]✓[/green]" if steps.get("download") else "[dim]·[/dim]",
            "[green]✓[/green]" if steps.get("review") else "[dim]·[/dim]",
            "[green]✓[/green]" if steps.get("report") else "[dim]·[/dim]",
        )
    console.print(table)


@app.command(name="status")
def run_status(
    run_id: str = typer.Argument(..., help="Run ID"),
    runs_root: Path = typer.Option(None, "--runs-root", help="Runs root directory"),
) -> None:
    """Show detailed status of a research run."""
    _load_config()
    from fwma.core.service import FWMAService

    service = FWMAService(runs_root=runs_root)
    try:
        status = service.run_status(run_id)
    except ValueError:
        console.print(f"[red]Run not found:[/red] {run_id}")
        raise typer.Exit(1)

    # Basic info
    info_table = Table(title=f"Run: {run_id}", show_header=False)
    info_table.add_column("Field", style="bold")
    info_table.add_column("Value")
    info_table.add_row("Name", status.get("name", ""))
    info_table.add_row("Requirement", status.get("requirement", ""))
    info_table.add_row("Created", status.get("created_at", ""))
    console.print(info_table)

    # Steps
    steps = status.get("steps", {})
    steps_table = Table(title="Pipeline Steps")
    steps_table.add_column("Step", style="bold")
    steps_table.add_column("Status", justify="center")
    for step_name in ALL_STEPS:
        done = steps.get(step_name, False)
        steps_table.add_row(step_name, "[green]✓ Done[/green]" if done else "[dim]Pending[/dim]")
    console.print(steps_table)

    # Active jobs
    active_jobs = status.get("active_jobs", [])
    if active_jobs:
        jobs_table = Table(title="Jobs")
        jobs_table.add_column("Job ID", style="cyan")
        jobs_table.add_column("Step")
        jobs_table.add_column("Status")
        jobs_table.add_column("Progress")
        for job in active_jobs:
            progress = job.get("progress")
            progress_str = ""
            if progress and progress.get("total"):
                progress_str = f"{progress.get('current', 0)}/{progress['total']}"
            jobs_table.add_row(job.get("job_id", ""), job.get("step", ""), job.get("status", ""), progress_str)
        console.print(jobs_table)

    # Sources
    sources = status.get("sources", [])
    if sources:
        src_table = Table(title="Data Sources")
        src_table.add_column("Type", style="bold")
        src_table.add_column("Query")
        for src in sources:
            src_table.add_row(src.get("type", ""), src.get("query", ""))
        console.print(src_table)


@app.command(name="show")
def show_artifact(
    run_id: str = typer.Argument(..., help="Run ID"),
    path: str = typer.Argument(
        None,
        help="Artifact path relative to run dir (e.g. crawl/papers_metadata.json). Omit to list available files.",
    ),
    runs_root: Path = typer.Option(None, "--runs-root", help="Runs root directory"),
) -> None:
    """Show intermediate results of a research run."""
    _load_config()
    from fwma.core.service import FWMAService

    service = FWMAService(runs_root=runs_root)

    # If no path given, list available artifacts
    if not path:
        run_dir = service.run_manager.runs_root / run_id
        if not run_dir.exists():
            console.print(f"[red]Run not found:[/red] {run_id}")
            raise typer.Exit(1)

        table = Table(title=f"Artifacts in {run_id}")
        table.add_column("Path", style="cyan")
        table.add_column("Size")

        for f in sorted(run_dir.rglob("*")):
            if f.is_file() and f.name != "run_config.json":
                rel = f.relative_to(run_dir)
                size = f.stat().st_size
                if size < 1024:
                    size_str = f"{size} B"
                elif size < 1024 * 1024:
                    size_str = f"{size / 1024:.1f} KB"
                else:
                    size_str = f"{size / (1024 * 1024):.1f} MB"
                table.add_row(str(rel), size_str)

        console.print(table)
        return

    try:
        content = service.read_artifact(run_id, path)
    except (ValueError, FileNotFoundError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    # Try to pretty-print JSON, otherwise print raw
    if path.endswith(".json"):
        try:
            data = json.loads(content)
            _print_dict(path, data if isinstance(data, dict) else {"data": data})
            return
        except json.JSONDecodeError:
            pass
    console.print(content)


@app.command()
def writing_review(
    pdf_path: Path = typer.Argument(..., help="Path to manuscript PDF"),
    venue: str = typer.Option(None, help="Target venue (e.g., 'NeurIPS 2025')"),
    notes: str = typer.Option(None, help="Additional notes for reviewers"),
    rounds: int = typer.Option(3, help="Max debate rounds"),
):
    """Review manuscript writing quality with AI Parliament."""
    _load_config()
    from fwma.core.service import FWMAService

    if not pdf_path.exists():
        console.print(f"[red]File not found:[/red] {pdf_path}")
        raise typer.Exit(1)

    if venue or notes:
        table = Table(title="Writing Review Context")
        table.add_column("Key", style="bold")
        table.add_column("Value")
        if venue:
            table.add_row("venue", venue)
        if notes:
            table.add_row("notes", notes)
        console.print(table)

    service = FWMAService()
    job_id = service.writing_review_async(manuscript=str(pdf_path), max_rounds=rounds, target_venue=venue)
    status = _wait_for_job(service, job_id, "Writing review")
    _print_dict("Writing Review", status)


@app.command(name="mcp")
def start_mcp() -> None:
    """Start FWMA MCP server."""
    try:
        from fwma.mcp.server import mcp

        console.print("[bold]Starting FWMA MCP server...[/bold]")
        mcp.run()
    except ImportError:
        console.print("[red]MCP support not installed. Run: pip install -e '.[mcp]' from the project root[/red]")
        raise typer.Exit(1)


@tools_app.command(name="pdf-vision")
def pdf_vision(
    pdf_path: Path = typer.Argument(..., help="Path to PDF file"),
    model: str = typer.Option("gemini/gemini-2.5-flash", help="Vision model"),
):
    """Extract tables, figures, and formulas from PDF using vision model."""
    _load_config()
    from fwma.core.service import FWMAService

    if not pdf_path.exists():
        console.print(f"[red]File not found:[/red] {pdf_path}")
        raise typer.Exit(1)

    service = FWMAService()
    pdf_vision_fn: Any = getattr(service, "pdf_vision")
    try:
        result = pdf_vision_fn(str(pdf_path), model=model)
    except TypeError:
        result = pdf_vision_fn(str(pdf_path))
    _print_dict("PDF Vision", result)


@tools_app.command(name="citation-check")
def citation_check(
    tex_path: Path = typer.Argument(..., help="Path to .tex manuscript"),
    bib_path: Path = typer.Option(None, "--bib", help="Path to .bib file"),
):
    """Check citation reasonability in LaTeX manuscript."""
    _load_config()
    from fwma.core.service import FWMAService

    if not tex_path.exists():
        console.print(f"[red]File not found:[/red] {tex_path}")
        raise typer.Exit(1)

    manuscript = tex_path.read_text(encoding="utf-8")
    bib_text = bib_path.read_text(encoding="utf-8") if bib_path and bib_path.exists() else ""
    bib_index: dict[str, Any] = {"raw_bib": bib_text} if bib_text else {}

    service = FWMAService()
    result = service.citation_check(bib_index=bib_index, manuscript=manuscript)
    _print_dict("Citation Check", result if isinstance(result, dict) else {"result": result})
