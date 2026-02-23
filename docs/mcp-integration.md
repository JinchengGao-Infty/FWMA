# MCP Integration Guide

## What is MCP?

[Model Context Protocol (MCP)](https://modelcontextprotocol.io/) is an open standard that lets AI assistants (Claude, Cursor, Windsurf, etc.) call external tools. FWMA's MCP server exposes the entire literature review pipeline as tools that AI agents can invoke autonomously.

## Installation

```bash
pip install -e '.[mcp]'
```

## Configuration

### Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "fwma": {
      "command": "fwma-mcp",
      "env": {
        "GEMINI_API_KEY": "your-key-here"
      }
    }
  }
}
```

### Using pip from source
```bash
git clone https://github.com/JinchengGao-Infty/FWMA.git
cd FWMA
pip install -e '.[mcp]'
```
Then configure your MCP client to use `fwma-mcp` as the command.

### Manual start

```bash
fwma mcp
# or
fwma-mcp
```

## Tool Reference

### Pipeline Tools

| Tool | Sync/Async | Parameters | Description |
|------|-----------|------------|-------------|
| `suggest_sources` | sync | `requirement`, `model?` | Generate search strategy from natural language |
| `run_create` | sync | `requirement`, `sources`, `name?`, `run_id?` | Create a new research run |
| `crawl` | sync | `run_id`, `timeout_s?` | Crawl papers from configured sources |
| `screen` | sync | `run_id`, `threshold?` | AI relevance screening |
| `download` | async | `run_id`, `concurrency?` | Download PDFs (progress reporting) |
| `review` | async | `run_id`, `max_rounds?` | AI Parliament debate review (progress reporting) |
| `report` | async | `run_id`, `format?` | Generate research report |

### Standalone Tools

| Tool | Sync/Async | Parameters | Description |
|------|-----------|------------|-------------|
| `writing_review` | async | `manuscript`, `max_rounds?`, `target_venue?` | Review manuscript writing quality |
| `parliament_debate` | sync | `topic`, `context?`, `max_rounds?` | General-purpose multi-agent debate |
| `pdf_vision` | sync | `pdf_path` | Extract tables/figures/formulas from PDF |
| `citation_check` | sync | `bib_index`, `manuscript?` | Check citation reasonability |

### Management Tools

| Tool | Parameters | Description |
|------|------------|-------------|
| `run_status` | `run_id` | Get run status and available artifacts |
| `job_status` | `job_id` | Get status/progress for one async job |
| `artifact_read` | `run_id`, `path` | Read a text artifact from a run |

## Example: AI Agent Conversation

Here's how an AI agent would use FWMA tools to conduct a literature review:

```
User: "Help me survey recent papers on transformer architectures in seismology"

Agent: [calls suggest_sources]
  → requirement: "transformer architectures applied to seismology, earthquake detection, seismic wave analysis"
  → Returns: sources config with OpenAlex + arXiv queries

Agent: [calls run_create]
  → requirement: "...", sources: [suggested sources]
  → Returns: run_id = "transformer-seismo-20250222"

Agent: [calls crawl]
  → run_id: "transformer-seismo-20250222"
  → Returns: {papers_found: 187, sources: {openalex: 120, arxiv: 67}}

Agent: [calls screen]
  → run_id: "transformer-seismo-20250222", threshold: "high_medium"
  → Returns: {screened: 187, high: 23, medium: 41, low: 123, selected: 64}

Agent: [calls download]
  → run_id: "transformer-seismo-20250222"
  → Returns: {downloaded: 58, failed: 6}

Agent: [calls review]
  → run_id: "transformer-seismo-20250222", max_rounds: 5
  → Returns: {reviewed: 58, highly_applicable: 12, moderately: 28, not: 18}

Agent: [calls report]
  → run_id: "transformer-seismo-20250222", format: "markdown"
  → Returns: {report_path: "runs/.../report/report.md"}

Agent: "I've completed the literature review. Found 187 papers, 64 passed screening,
        and 12 are highly applicable. The full report is ready. Key findings: ..."
```

## Async Operations

Long-running tools (`download`, `review`, `report`, `writing_review`) return a `job_id` immediately. Poll progress using `job_status` (or `run_status` to see all jobs for a run):

```
Agent: [calls review] -> {"job_id": "job_review_ab12cd34", ...}
Agent: [calls job_status] -> {"status": "running", "progress": {"current": 15, "total": 58, "message": "review"}}
Agent: [calls job_status] -> {"status": "succeeded", ...}
```

## Troubleshooting

### "MCP support not installed"
```bash
pip install -e '.[mcp]'
```

### "No API key configured"
Set at least one LLM API key:
```bash
export GEMINI_API_KEY=your-key
# or
export ANTHROPIC_API_KEY=your-key
# or
export OPENAI_API_KEY=your-key
```

### MCP server not appearing in Claude Desktop
1. Restart Claude Desktop after editing config
2. Check the config JSON is valid (no trailing commas)
3. Verify `fwma-mcp` is in your PATH: `which fwma-mcp`

### Connection timeout
For large research runs, increase the timeout in your MCP client configuration. The `crawl` tool accepts a `timeout_s` parameter (default: 600 seconds).
