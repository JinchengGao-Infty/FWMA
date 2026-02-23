# 🏛️ FWMA — Full-Workflow Multi-Agent Literature Review

AI Parliament-driven end-to-end systematic literature review automation.

> FWMA automates systematic literature review end-to-end, using an **AI Parliament** — a structured multi-agent debate — to evaluate papers with transparent, auditable justifications.

## Features

- **Multi-source crawling** — OpenAlex, arXiv, OpenReview with unified format and deduplication
- **AI screening** — LLM-powered relevance filtering (high / medium / low)
- **PDF download** — Multi-strategy fallback (direct → Unpaywall → DOI → browser)
- **AI Parliament review** — Chair + 2 Members structured debate, multi-round voting, scored verdicts
- **Report generation** — Synthesize all reviews into Markdown/JSON research reports
- **Writing review** — Multi-agent feedback on your own manuscripts
- **PDF vision extraction** — Tables, figures, formulas via vision models
- **Citation checking** — Verify citation reasonability in LaTeX manuscripts

## Quick Start

```bash
pip install fwma

# Set at least one API key
export GEMINI_API_KEY=your-key-here

# Let AI suggest a search strategy
fwma suggest "transformer applications in seismology"

# Run the full pipeline
fwma run research.toml
```

## MCP Integration (for AI Agents)

FWMA works as an MCP server, letting AI agents (Claude, Cursor, etc.) run literature reviews autonomously.

```bash
pip install fwma[mcp]
```

Add to your Claude Desktop config (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "fwma": {
      "command": "fwma-mcp"
    }
  }
}
```

Or run directly with uvx:

```bash
uvx --from "fwma[mcp]" fwma-mcp
```

### MCP Tools

| Tool | Type | Description |
|------|------|-------------|
| `suggest_sources` | sync | AI-powered search strategy generation |
| `run_create` | sync | Create research run with sources config |
| `crawl` | sync | Crawl papers from academic sources |
| `screen` | sync | AI relevance screening |
| `download` | async | PDF download with multi-strategy fallback |
| `review` | async | AI Parliament debate review |
| `report` | async | Generate research summary report |
| `writing_review` | async | Manuscript writing quality review |
| `parliament_debate` | sync | Standalone multi-agent debate |
| `pdf_vision` | sync | PDF visual extraction |
| `citation_check` | sync | Citation reasonability check |
| `run_status` | sync | Query run status and artifacts |
| `job_status` | sync | Query status/progress for one async job |
| `artifact_read` | sync | Read run artifacts |

Long-running tools (`download`, `review`, `report`, `writing_review`) return a `job_id` immediately. Poll with `job_status` until `status` becomes `succeeded` or `failed`.

## CLI Reference

```bash
fwma suggest <requirement>          # AI search strategy suggestion
fwma run <config.toml>              # Full pipeline from config
fwma crawl <config.toml>            # Crawl papers
fwma screen --run-dir <dir>         # AI screening
fwma download --run-dir <dir>       # Download PDFs
fwma review --run-dir <dir>         # AI Parliament review
fwma report --run-dir <dir>         # Generate report
fwma writing-review <pdf>           # Manuscript writing review
fwma tools pdf-vision <pdf>         # PDF visual extraction
fwma tools citation-check <tex>     # Citation checking
fwma mcp                            # Start MCP server
```

## Architecture

```
┌─────────────────────────────────────────────┐
│              User / AI Agent                │
├──────────────────┬──────────────────────────┤
│    CLI (typer)   │   MCP Server (fastmcp)   │  ← Thin adapters
├──────────────────┴──────────────────────────┤
│              Core Library                    │
│  ┌─────────┐ ┌──────────┐ ┌──────────────┐ │
│  │Crawlers │ │Screening │ │  Parliament   │ │
│  │OpenAlex │ │   AI     │ │ Chair + 2    │ │
│  │arXiv    │ │ filtering│ │ Members      │ │
│  │OpenRev. │ │          │ │ Multi-round  │ │
│  └─────────┘ └──────────┘ └──────────────┘ │
│  ┌─────────┐ ┌──────────┐ ┌──────────────┐ │
│  │Download │ │  Report  │ │  LLM Client  │ │
│  │Multi-   │ │  MD/JSON │ │ Claude/Gemini│ │
│  │strategy │ │ synthesis│ │ GPT/OpenAI   │ │
│  └─────────┘ └──────────┘ └──────────────┘ │
│  ┌──────────────────────────────────────┐   │
│  │  Tools: pdf-vision, citation-check  │   │
│  └──────────────────────────────────────┘   │
├─────────────────────────────────────────────┤
│         Data Layer (JSON + PDF files)       │
│         runs/<run_id>/crawl/screen/...      │
└─────────────────────────────────────────────┘
```

## Pipeline Flow

```
suggest → crawl → screen → download → review → report
   │         │        │         │         │        │
   │    OpenAlex   AI filter  Multi-   Parliament  Markdown
   │    arXiv     high/med   strategy  debate     /JSON
   │    OpenRev.  /low       fallback  (5 rounds)
   │
   └─ AI generates search config from natural language
```

## Configuration

### API Keys (`.env` or environment variables)

```bash
GEMINI_API_KEY=your-gemini-key
ANTHROPIC_API_KEY=your-anthropic-key    # optional
OPENAI_API_KEY=your-openai-key          # optional
```

### Global defaults (`~/.config/fwma/config.toml`)

```toml
[models]
screener = "gemini/gemini-2.5-flash"
chair = "gemini/gemini-2.5-pro"
member1 = "anthropic/claude-sonnet-4"
member2 = "openai/gpt-4o"

[defaults]
language = "zh"
openalex_mailto = "you@example.com"
```

### Research config (`research.toml`)

```toml
[research]
name = "my-research"
requirement = "Find recent papers on transformer applications in seismology"

[[sources]]
type = "openalex"
keywords = ["transformer", "seismology"]
year_from = 2022
limit = 200

[[sources]]
type = "arxiv"
categories = ["physics.geo-ph", "cs.LG"]
keywords = ["seismic", "deep learning"]
limit = 100
```

## Supported LLM Providers

- Google Gemini (default)
- Anthropic Claude
- OpenAI GPT
- Any OpenAI-compatible endpoint (Ollama, vLLM, etc.)

## Why FWMA?

| | FWMA | ASReview | paper-qa | gpt-researcher |
|---|---|---|---|---|
| Full pipeline | ✅ crawl→screen→download→review→report | ❌ screening only | ❌ Q&A only | ❌ general web |
| Multi-agent debate | ✅ AI Parliament | ❌ | ❌ | ❌ |
| Academic sources | ✅ OpenAlex + arXiv + OpenReview | ✅ | ❌ | ❌ |
| MCP support | ✅ | ❌ | ❌ | ❌ |
| PDF vision | ✅ tables/figures/formulas | ❌ | ❌ | ❌ |
| Writing review | ✅ | ❌ | ❌ | ❌ |

## Contributing

Contributions welcome! Please open an issue first to discuss what you'd like to change.

## License

[Apache-2.0](LICENSE)
