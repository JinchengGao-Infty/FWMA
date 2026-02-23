"""Citation reasonability checker.

Checks whether citations in a LaTeX manuscript are used
appropriately by cross-referencing with the cited papers.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from fwma.llm.client import LLMClient
from fwma.tools.pdf_vision import extract_text_from_pdf

logger = logging.getLogger(__name__)


def check_citations(
    bib_index: dict[str, dict],
    manuscript: str | None = None,
    manuscript_path: Path | str | None = None,
    model: str = "anthropic/claude-haiku-4-5",
) -> dict:
    """Check citation reasonability in a manuscript.

    Args:
        bib_index: Dict mapping citation keys to {title, pdf} info.
            Example: {"smith2023": {"title": "Some Paper", "pdf": "/path/to/paper.pdf"}}
        manuscript: LaTeX manuscript content (string).
        manuscript_path: Path to .tex file (alternative to manuscript).
        model: LLM model for analysis.

    Returns:
        Dict with per-citation assessments and overall score.
    """
    # Load manuscript
    if manuscript is None and manuscript_path is not None:
        manuscript = Path(manuscript_path).read_text(encoding="utf-8")
    if not manuscript:
        raise ValueError("Must provide either manuscript or manuscript_path")

    # Find all citation keys used in manuscript
    cite_pattern = re.compile(r"\\cite[tp]?\{([^}]+)\}")
    used_keys = set()
    for match in cite_pattern.finditer(manuscript):
        for key in match.group(1).split(","):
            used_keys.add(key.strip())

    logger.info(f"Found {len(used_keys)} citation keys in manuscript")

    client = LLMClient()
    assessments = {}

    for cite_key in sorted(used_keys):
        if cite_key not in bib_index:
            assessments[cite_key] = {
                "status": "missing",
                "title": None,
                "reasonable": None,
                "reason": f"Citation key '{cite_key}' not found in bib_index",
            }
            continue

        entry = bib_index[cite_key]
        title = entry.get("title", "Unknown")
        pdf_path = entry.get("pdf")

        # Extract cited paper content
        cited_content = f"Title: {title}"
        if pdf_path and Path(pdf_path).exists():
            try:
                pdf_text = extract_text_from_pdf(pdf_path, max_pages=5)
                cited_content += f"\n\nContent (first 5 pages):\n{pdf_text[:5000]}"
            except Exception as e:
                logger.warning(f"Failed to extract PDF for {cite_key}: {e}")
                cited_content += "\n\n(PDF extraction failed, judging by title only)"
        else:
            cited_content += "\n\n(No PDF available, judging by title only)"

        # Find citation context in manuscript (surrounding text)
        contexts = _find_citation_contexts(manuscript, cite_key)
        context_text = "\n---\n".join(contexts[:5]) if contexts else "(No context found)"

        # Ask LLM to evaluate
        messages = [
            {
                "role": "system",
                "content": (
                    "你是一位学术论文审稿专家。你的任务是判断论文中的引用是否合理。"
                    "请根据手稿中的引用上下文和被引论文的内容，评估引用是否恰当。"
                    "请直接输出JSON格式的评估结果。"
                ),
            },
            {
                "role": "user",
                "content": f"""请评估以下引用是否合理：

## 引用键: {cite_key}

## 手稿中的引用上下文
{context_text}

## 被引论文信息
{cited_content}

请输出JSON格式：
{{
  "reasonable": true/false,
  "confidence": "high"/"medium"/"low",
  "reason": "判断理由（2-3句话）",
  "suggestion": "如果不合理，给出改进建议；如果合理，写'无'"
}}

直接输出JSON，不要用markdown代码块包裹。""",
            },
        ]

        try:
            response = client.call(model=model, messages=messages)
            from fwma.core.utils import parse_json_response

            result = parse_json_response(response)
            assessments[cite_key] = {
                "status": "checked",
                "title": title,
                **result,
            }
        except Exception as e:
            logger.warning(f"Failed to assess {cite_key}: {e}")
            assessments[cite_key] = {
                "status": "error",
                "title": title,
                "reasonable": None,
                "reason": f"Assessment failed: {e}",
            }

    # Overall summary
    checked = [a for a in assessments.values() if a.get("status") == "checked"]
    reasonable_count = sum(1 for a in checked if a.get("reasonable"))
    total_checked = len(checked)

    return {
        "total_citations": len(used_keys),
        "checked": total_checked,
        "reasonable": reasonable_count,
        "unreasonable": total_checked - reasonable_count,
        "missing_from_index": sum(1 for a in assessments.values() if a["status"] == "missing"),
        "errors": sum(1 for a in assessments.values() if a["status"] == "error"),
        "score": round(reasonable_count / total_checked * 5, 1) if total_checked > 0 else 0,
        "assessments": assessments,
    }


def _find_citation_contexts(manuscript: str, cite_key: str, window: int = 300) -> list[str]:
    """Find text surrounding each occurrence of a citation key."""
    contexts = []
    # Match \cite{key}, \cite{...,key,...}, \citep{key}, \citet{key}
    pattern = re.compile(rf"\\cite[tp]?\{{[^}}]*\b{re.escape(cite_key)}\b[^}}]*\}}")
    for match in pattern.finditer(manuscript):
        start = max(0, match.start() - window)
        end = min(len(manuscript), match.end() + window)
        context = manuscript[start:end].strip()
        contexts.append(context)
    return contexts


def parse_bib_file(bib_path: Path | str) -> dict[str, dict]:
    """Parse .bib file into bib_index format.

    Returns dict mapping citation keys to {title, pdf} info.
    """
    bib_path = Path(bib_path)
    if not bib_path.exists():
        raise FileNotFoundError(f"Bib file not found: {bib_path}")

    content = bib_path.read_text(encoding="utf-8")

    bib_index = {}
    # Match @type{key, ... }
    entry_pattern = re.compile(r"@\w+\{(\w+)\s*,(.+?)\n\}", re.DOTALL)

    for match in entry_pattern.finditer(content):
        key = match.group(1)
        body = match.group(2)

        # Extract title
        title_match = re.search(r"title\s*=\s*\{(.+?)\}", body, re.DOTALL)
        title = title_match.group(1).strip() if title_match else "Unknown"

        bib_index[key] = {"title": title, "pdf": None}

    logger.info(f"Parsed {len(bib_index)} entries from {bib_path}")
    return bib_index
