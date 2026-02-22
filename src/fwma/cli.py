"""FWMA CLI — AI Parliament-driven literature review."""

from __future__ import annotations

import typer
from rich.console import Console

app = typer.Typer(
    name="fwma",
    help="AI Parliament-driven systematic literature review.",
    rich_markup_mode="rich",
    no_args_is_help=True,
)
tools_app = typer.Typer(name="tools", help="Standalone tools (pdf-vision, citation-check).")
app.add_typer(tools_app)

console = Console()


@app.command()
def suggest(
    requirement: str = typer.Argument(..., help="Research requirement in natural language"),
    model: str = typer.Option(None, help="LLM model for suggestion generation"),
):
    """AI-powered search strategy suggestion."""
    console.print(f"[bold]Generating search strategy for:[/bold] {requirement}")
    raise NotImplementedError("suggest not yet implemented")


@app.command()
def run(
    config: str = typer.Argument(..., help="Path to research config TOML file"),
    steps: str = typer.Option(None, help="Comma-separated steps to run (crawl,screen,download,review,report)"),
    resume: bool = typer.Option(True, help="Resume from last checkpoint"),
    verbose: int = typer.Option(0, "--verbose", "-v", count=True, help="Verbosity level"),
):
    """Run full research pipeline from config file."""
    console.print(f"[bold]Running pipeline from:[/bold] {config}")
    raise NotImplementedError("run not yet implemented")


@app.command()
def crawl(
    config: str = typer.Argument(..., help="Path to research config TOML"),
    resume: bool = typer.Option(True, help="Resume from last checkpoint"),
):
    """Crawl papers from configured sources."""
    console.print(f"[bold]Crawling papers from:[/bold] {config}")
    raise NotImplementedError("crawl not yet implemented")


@app.command()
def screen(
    run_dir: str = typer.Option(".", help="Run directory path"),
    threshold: str = typer.Option("high_medium", help="Screening threshold (high_only, high_medium, all_selected)"),
):
    """Screen papers for relevance using AI."""
    console.print(f"[bold]Screening papers in:[/bold] {run_dir}")
    raise NotImplementedError("screen not yet implemented")


@app.command()
def download(
    run_dir: str = typer.Option(".", help="Run directory path"),
    concurrency: int = typer.Option(8, help="Concurrent downloads"),
    resume: bool = typer.Option(True, help="Skip already downloaded"),
):
    """Download PDFs for screened papers."""
    console.print(f"[bold]Downloading PDFs to:[/bold] {run_dir}")
    raise NotImplementedError("download not yet implemented")


@app.command()
def review(
    run_dir: str = typer.Option(".", help="Run directory path"),
    rounds: int = typer.Option(5, help="Max debate rounds"),
    resume: bool = typer.Option(True, help="Skip already reviewed"),
):
    """Review papers with AI Parliament debate."""
    console.print(f"[bold]Reviewing papers in:[/bold] {run_dir}")
    raise NotImplementedError("review not yet implemented")


@app.command()
def report(
    run_dir: str = typer.Option(".", help="Run directory path"),
    format: str = typer.Option("markdown", help="Output format (markdown, json, both)"),
):
    """Generate research summary report."""
    console.print(f"[bold]Generating report for:[/bold] {run_dir}")
    raise NotImplementedError("report not yet implemented")


@app.command()
def writing_review(
    pdf_path: str = typer.Argument(..., help="Path to manuscript PDF"),
    venue: str = typer.Option(None, help="Target venue (e.g., 'NeurIPS 2025')"),
    notes: str = typer.Option(None, help="Additional notes for reviewers"),
    rounds: int = typer.Option(3, help="Max debate rounds"),
):
    """Review manuscript writing quality with AI Parliament."""
    console.print(f"[bold]Reviewing writing:[/bold] {pdf_path}")
    raise NotImplementedError("writing_review not yet implemented")


@app.command()
def mcp():
    """Start FWMA MCP server."""
    try:
        from fwma.mcp.server import main as mcp_main

        mcp_main()
    except ImportError:
        console.print("[red]MCP support not installed. Run: pip install fwma\\[mcp][/red]")
        raise typer.Exit(1)


# --- Standalone tools ---


@tools_app.command("pdf-vision")
def pdf_vision(
    pdf_path: str = typer.Argument(..., help="Path to PDF file"),
    model: str = typer.Option("gemini/gemini-2.5-flash", help="Vision model"),
):
    """Extract tables, figures, and formulas from PDF using vision model."""
    console.print(f"[bold]Extracting visuals from:[/bold] {pdf_path}")
    raise NotImplementedError("pdf-vision not yet implemented")


@tools_app.command("citation-check")
def citation_check(
    tex_path: str = typer.Argument(..., help="Path to .tex manuscript"),
    bib_path: str = typer.Option(None, "--bib", help="Path to .bib file"),
):
    """Check citation reasonability in LaTeX manuscript."""
    console.print(f"[bold]Checking citations in:[/bold] {tex_path}")
    raise NotImplementedError("citation-check not yet implemented")
