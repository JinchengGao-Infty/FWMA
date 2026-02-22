# FWMA Architecture

## Overview

FWMA is a layered system with a clear separation between core logic and interface adapters.

```
┌──────────────────────────────────────────────────┐
│                 Interface Layer                    │
│   ┌──────────────┐    ┌────────────────────┐     │
│   │  CLI (typer)  │    │ MCP Server (fastmcp)│     │
│   └──────┬───────┘    └────────┬───────────┘     │
├──────────┴─────────────────────┴─────────────────┤
│                  Core Library                      │
│                                                    │
│  ┌────────────┐  ┌───────────┐  ┌──────────────┐ │
│  │  Pipeline   │  │  Crawlers  │  │  Parliament   │ │
│  │ orchestrate │  │ OpenAlex   │  │ debate engine │ │
│  │ all steps   │  │ arXiv      │  │ chair+members │ │
│  │             │  │ OpenReview │  │ multi-round   │ │
│  └────────────┘  └───────────┘  └──────────────┘ │
│                                                    │
│  ┌────────────┐  ┌───────────┐  ┌──────────────┐ │
│  │ Screening   │  │ Download   │  │   Report     │ │
│  │ AI filter   │  │ multi-     │  │  MD / JSON   │ │
│  │ high/med/lo │  │ strategy   │  │  synthesis   │ │
│  └────────────┘  └───────────┘  └──────────────┘ │
│                                                    │
│  ┌────────────┐  ┌──────────────────────────────┐ │
│  │ LLM Client  │  │  Tools                       │ │
│  │ Claude      │  │  pdf-vision, citation-check  │ │
│  │ Gemini      │  │                              │ │
│  │ GPT         │  │                              │ │
│  │ OpenAI-compat│ │                              │ │
│  └────────────┘  └──────────────────────────────┘ │
├──────────────────────────────────────────────────┤
│                  Data Layer                        │
│  runs/<run_id>/                                    │
│    crawl/papers_metadata.json                      │
│    screen/screened_papers.json                     │
│    download/*.pdf                                  │
│    review/<paper_id>.json                          │
│    report/report.md                                │
└──────────────────────────────────────────────────┘
```

## Pipeline Flow

```
suggest → crawl → screen → download → review → report
```

Each step reads from the previous step's output directory and writes to its own. All steps support resume — if interrupted, re-running skips completed work.

### Step 0: Suggest

AI generates a multi-source search configuration from a natural language research requirement. Outputs a TOML/JSON config with sources for OpenAlex, arXiv, and OpenReview.

### Step 1: Crawl

Queries academic APIs in parallel:
- **OpenAlex**: Rich metadata, citation counts, open access status, field classification
- **arXiv**: Preprints by category and keyword
- **OpenReview**: Conference submissions by venue

All results normalized to a unified `Paper` model. Deduplication by DOI and title similarity.

### Step 2: Screen

LLM evaluates each paper's relevance to the research requirement. Classification: high / medium / low. Batch processing with configurable threshold filtering.

### Step 3: Download

Multi-strategy PDF acquisition:
1. Direct URL from paper metadata
2. Unpaywall API (open access lookup)
3. DOI redirect following
4. Browser automation fallback (requires playwright)

Threaded downloads with configurable concurrency. PDF validation after download.

### Step 4: Review (AI Parliament)

The core differentiator. Each paper goes through a structured multi-agent debate:

```
┌─────────────────────────────────────────┐
│              AI Parliament               │
│                                          │
│  1. Chair opens with topic framing       │
│  2. Member 1 (Engineer) argues           │
│  3. Member 2 (Theorist) responds         │
│  4. Multi-round debate (up to 5 rounds)  │
│  5. Vote check — consensus reached?      │
│  6. Chair delivers final verdict          │
│     - Score (0-5)                        │
│     - Recommendation                     │
│     - Key findings                       │
│     - Application ideas                  │
└─────────────────────────────────────────┘
```

Before debate, the paper's PDF is processed:
- Text extraction (PyMuPDF)
- Visual extraction (tables, figures, formulas via vision model)
- Combined context fed to all debate participants

Each role can use a different LLM model (e.g., Chair=Gemini, Member1=Claude, Member2=GPT).

### Step 5: Report

LLM synthesizes all review results into a coherent research report. Supports Markdown and JSON output formats.

## Module Reference

| Module | File | Purpose |
|--------|------|---------|
| Pipeline | `core/pipeline.py` | Step orchestration, resume logic |
| Config | `core/config.py` | Environment + TOML config loading |
| Models | `core/models.py` | Pydantic data models (Paper, ReviewResult, etc.) |
| OpenAlex | `crawlers/openalex.py` | OpenAlex API crawler |
| arXiv | `crawlers/arxiv.py` | arXiv API crawler |
| OpenReview | `crawlers/openreview.py` | OpenReview API crawler |
| Screener | `screening/screener.py` | AI relevance screening |
| Downloader | `download/downloader.py` | Multi-strategy PDF download |
| Parliament | `parliament/debate.py` | Multi-agent debate engine |
| Paper Review | `parliament/review.py` | Paper evaluation via debate |
| Writing Review | `parliament/writing.py` | Manuscript writing feedback |
| Report | `report/generator.py` | Research report synthesis |
| LLM Client | `llm/client.py` | Unified LLM API abstraction |
| PDF Vision | `tools/pdf_vision.py` | Visual extraction from PDFs |
| Citation Check | `tools/citation_check.py` | Citation reasonability checking |
| CLI | `cli.py` | Command-line interface (typer) |
| MCP Server | `mcp/server.py` | MCP server for AI agents (fastmcp) |

## Data Directory Structure

```
runs/<run_id>/
├── config.toml              # Research configuration
├── crawl/
│   └── papers_metadata.json # All crawled papers
├── screen/
│   └── screened_papers.json # Filtered papers with relevance scores
├── download/
│   └── *.pdf                # Downloaded paper PDFs
├── review/
│   ├── <paper_id>.json      # Per-paper review with debate log
│   └── ...
└── report/
    ├── report.md            # Markdown research report
    └── report.json          # JSON structured report
```
