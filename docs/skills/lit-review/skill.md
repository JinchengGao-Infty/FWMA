---
name: lit-review
description: "Lightweight literature review: Claude directly searches arXiv, screens abstracts, reads key papers, and produces a structured Markdown report. Use for quick topic surveys, related work exploration, or catching up on a research area. For heavy systematic reviews with multi-agent debate, use fwma instead."
---

# Lit-Review — Lightweight Literature Survey

You ARE the reviewer. No external pipeline, no PDF downloads, no multi-agent debate.
Search → Screen → Read → Report, all in-conversation.

**Topic**: $ARGUMENTS

---

## Step 0: Clarify Scope (30s)

If the user gave a clear topic, proceed directly. Otherwise ask ONE round of questions:
- What specific aspect/problem are you investigating?
- Any time range preference? (default: last 2-3 years)
- Breadth vs depth? (default: balanced, ~10 key papers)
- Language preference for the report? (default: Chinese)

Extract from the topic:
- **Keywords**: 2-4 core search terms (English, for arXiv API)
- **Categories**: arXiv categories (e.g., cs.LG, cs.CL, stat.ML)
- **Time range**: year_min (default: current_year - 2)
- **Focus questions**: what specifically the user wants to learn

---

## Step 1: Search Papers (1-2min)

Use MULTIPLE search strategies in parallel:

### 1a. arXiv API (primary)
```bash
curl -s "http://export.arxiv.org/api/query?search_query=all:{query}&start=0&max_results={N}&sortBy=submittedDate&sortOrder=descending" | head -500
```
- Build query: `all:keyword1+AND+all:keyword2` (max 2-3 terms per query, AND logic)
- Run 2-3 variant queries to cover different angles
- Fetch 30-80 papers total
- Parse XML: extract `<entry>` blocks with title, summary, id, published, authors

### 1b. OpenAlex API (backup, broader coverage)
When arXiv results are insufficient (e.g., non-CS fields, interdisciplinary topics, or need citation counts):
```bash
curl -s "https://api.openalex.org/works?filter=title_and_abstract.search:{query},from_publication_date:{year_min}-01-01&sort=relevance_score:desc&per_page=50&select=id,title,authorships,publication_year,primary_location,abstract_inverted_index,cited_by_count,concepts" | python3 -c "import sys,json; print(json.dumps(json.load(sys.stdin),indent=2,ensure_ascii=False))" | head -500
```
- Free, no API key needed (polite pool: add `mailto=user@example.com` param for faster rate)
- Covers journals, conferences, preprints — much broader than arXiv alone
- Provides `cited_by_count` for importance ranking
- `abstract_inverted_index` needs reconstruction: `" ".join(w for w,_ in sorted(((w,p) for w,pos in idx.items() for p in pos), key=lambda x:x[1]))`

### 1c. OpenReview API (backup, for ML venues)
When the topic targets specific ML venues (NeurIPS, ICLR, ICML) and you need review scores or acceptance status:
```bash
curl -s "https://api.openreview.net/notes/search?query={query}&limit=50&source=forum" | python3 -c "import sys,json; print(json.dumps(json.load(sys.stdin),indent=2,ensure_ascii=False))" | head -500
```
- Best for: NeurIPS, ICLR, ICML, EMNLP papers with peer review data
- Can filter by venue: add `&venue=ICLR.cc/2025/Conference`

### 1d. grok-search (supplementary)
Use grok-search skill to find:
- Seminal/highly-cited works that API searches might miss
- Very recent preprints or blog posts about the topic
- Survey papers that already exist on this topic

### 1e. ACE tool (if codebase-related)
If the topic relates to code in the current project, use `mcp__ace-tool__search_context` to find relevant implementations, then trace back to their source papers.

### Search strategy priority
1. **arXiv API** — always first, best for CS/ML/AI preprints
2. **OpenAlex** — when arXiv coverage is thin, or need citation data
3. **OpenReview** — when targeting specific ML venue papers
4. **grok-search** — fill gaps, find seminal works, latest news

**Output of Step 1**: A deduplicated list of papers with title, authors, year, abstract, source_url.

---

## Step 2: Screen & Rank (1-2min)

Read ALL abstracts yourself. For each paper, assign:
- **High**: Directly addresses the user's focus questions
- **Medium**: Related methodology or adjacent problem
- **Low**: Tangential or irrelevant

Selection criteria:
- Keep all High papers (target: 5-15)
- Keep Medium papers only if total High < 8
- Drop all Low papers

Sort selected papers by relevance (not date).

---

## Step 3: Deep Read Key Papers (3-5min)

For the top 5-10 High papers:

### 3a. Fetch extended content
Use WebFetch on `https://ar5iv.labs.arxiv.org/html/{arxiv_id}` (HTML version of arXiv papers, much easier to parse than PDF).

If ar5iv is unavailable, fall back to the abstract page: `https://arxiv.org/abs/{arxiv_id}`

### 3b. Extract key information
For each paper, note:
- **Problem**: What problem does it solve?
- **Method**: Core technical approach (1-3 sentences)
- **Results**: Key quantitative results or claims
- **Limitations**: Acknowledged or apparent weaknesses
- **Relevance**: How it connects to the user's questions

### 3c. Identify connections
- Which papers build on each other?
- What are the competing approaches?
- Where do results conflict?

---

## Step 4: Generate Report (2-3min)

Write a structured Markdown report in the user's preferred language (default: Chinese).

### Report Template

```markdown
# {Topic} 文献调研报告

> 生成时间: {date} | 检索范围: arXiv {year_min}-{year_max} | 筛选: {total_found} 篇中选出 {selected} 篇

## 1. 研究现状概览
<!-- 2-3 段，勾勒该领域的整体脉络和发展趋势 -->

## 2. 关键方法分类
<!-- 按方法/思路分类，不是按时间 -->

### 2.1 {Method Category A}
- 核心思路
- 代表工作: [Paper1], [Paper2]
- 优劣势

### 2.2 {Method Category B}
...

## 3. 关键论文详评

| # | 论文 | 年份 | 核心贡献 | 方法要点 |
|---|------|------|----------|----------|
| 1 | [Title](arxiv_url) | 2025 | ... | ... |
| ... |

### 3.1 {Paper Title}
- **问题**: ...
- **方法**: ...
- **结果**: ...
- **局限**: ...

<!-- repeat for top papers -->

## 4. 方法对比

| 方法 | 优势 | 劣势 | 适用场景 |
|------|------|------|----------|
| ... | ... | ... | ... |

## 5. Research Gaps 与未来方向
<!-- 基于以上分析，指出尚未解决的问题和值得探索的方向 -->

## 参考文献
<!-- 所有引用的论文，按出现顺序编号 -->
[1] Author et al. "Title." arXiv:XXXX.XXXXX, Year.
```

### Report output
- Save to: `~/Desktop/lit-review-{topic-slug}-{date}.md`
- Also display a concise summary (5-8 sentences) in the conversation

---

## Step 5: Persist to Memory Palace

Save key findings to Memory Palace for future reference:

```
mcp__memory-palace__create_memory:
  title: "Lit Review: {topic}"
  body: |
    ## Summary
    {3-5 sentence overview}
    ## Key Papers
    {top 5 papers with one-line descriptions}
    ## Key Findings
    {main takeaways relevant to user's work}
  domain: "research"
  path: "lit-review/{topic-slug}"
  priority: 1
```

This ensures future conversations can recall what was surveyed without re-running the review.

---

## Key Principles

1. **You are the reviewer** — don't delegate to external tools. Read, think, synthesize.
2. **Abstracts are enough for screening** — only fetch full text for papers you're actually analyzing.
3. **arXiv keyword tips** (from FWMA lessons): max 2-3 keywords per query, AND logic, too many = 0 results.
4. **Prefer breadth first** — it's better to survey 30 papers shallowly than 5 papers deeply, then zoom in on what matters.
5. **Be honest about limitations** — you can't read PDFs with complex math/figures as well as a human. Flag when a paper needs human attention.
6. **Chinese by default** — unless user specifies otherwise, report in Chinese.
