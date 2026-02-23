"""PDF visual extraction using vision models.

Extracts tables, figures, and formulas from PDF pages
using multimodal vision models (e.g., Gemini Flash).
Also provides text extraction via PyMuPDF.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from pathlib import Path

import requests

logger = logging.getLogger(__name__)


def extract_text_from_pdf(pdf_path: str | Path) -> str:
    """Extract text from PDF using PyMuPDF.

    Args:
        pdf_path: Path to PDF file

    Returns:
        Extracted text with page markers
    """
    import fitz  # PyMuPDF

    pdf_path = str(pdf_path)
    text_parts = []

    try:
        doc = fitz.open(pdf_path)
        for page_num in range(len(doc)):
            page = doc[page_num]
            text = str(page.get_text())
            if text.strip():
                text_parts.append(f"--- Page {page_num + 1} ---\n{text}")
        doc.close()
    except Exception as e:
        logger.error(f"Failed to extract text from {pdf_path}: {e}")
        return ""

    return "\n\n".join(text_parts)


def extract_visuals_from_pdf(
    pdf_path: str | Path,
    api_url: str | None = None,
    api_key: str | None = None,
    model: str = "gemini-2.0-flash",
) -> list[dict]:
    """Extract visual elements from PDF using vision model.

    Supports both native Google Gemini API and OpenAI-compatible endpoints.

    Args:
        pdf_path: Path to PDF file
        api_url: API endpoint URL (defaults to Google Gemini)
        api_key: API key (defaults to GEMINI_API_KEY env var)
        model: Model name for vision extraction

    Returns:
        List of dicts with keys: type (table/figure/formula),
        page, description, content
    """
    if api_key is None:
        api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        logger.warning("No API key for vision extraction, skipping")
        return []

    if api_url is None:
        api_url = os.environ.get(
            "GEMINI_VISION_URL",
            "https://generativelanguage.googleapis.com/v1beta/models",
        )

    # Read PDF as base64
    pdf_path = str(pdf_path)
    try:
        with open(pdf_path, "rb") as f:
            pdf_base64 = base64.b64encode(f.read()).decode("utf-8")
    except Exception as e:
        logger.error(f"Failed to read PDF {pdf_path}: {e}")
        return []

    prompt = """请分析这个PDF文档，提取所有重要的视觉元素。对于每个元素，请提供：
1. 类型（table/figure/formula）
2. 页码
3. 描述
4. 内容（表格用markdown格式，公式用LaTeX格式，图表用文字描述）

请以JSON数组格式返回，每个元素包含 type, page, description, content 字段。
如果没有找到视觉元素，返回空数组 []。"""
    system_prompt = (
        """你是一位学术文档视觉解析专家。你必须严格依据PDF内容提取表格、图像与公式信息，并只返回可解析的JSON结果。"""
    )

    try:
        # Detect API type
        is_native_google = "generativelanguage.googleapis.com" in api_url

        if is_native_google:
            # Native Google Gemini API
            url = f"{api_url}/{model}:generateContent?key={api_key}"
            payload = {
                "system_instruction": {"parts": [{"text": system_prompt}]},
                "contents": [
                    {
                        "parts": [
                            {"text": prompt},
                            {
                                "inline_data": {
                                    "mime_type": "application/pdf",
                                    "data": pdf_base64,
                                }
                            },
                        ]
                    }
                ],
            }
            response = requests.post(url, json=payload, timeout=300)
            response.raise_for_status()
            result = response.json()

            # Extract text from response
            text = ""
            if "candidates" in result:
                for candidate in result["candidates"]:
                    if "content" in candidate and "parts" in candidate["content"]:
                        for part in candidate["content"]["parts"]:
                            if "text" in part:
                                text += part["text"]
        else:
            # OpenAI-compatible API
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": model,
                "messages": [
                    {
                        "role": "system",
                        "content": system_prompt,
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:application/pdf;base64,{pdf_base64}"},
                            },
                        ],
                    },
                ],
                "max_tokens": 4096,
            }
            response = requests.post(
                f"{api_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=300,
            )
            response.raise_for_status()
            result = response.json()
            text = result["choices"][0]["message"]["content"]

        # Parse JSON from response
        text = str(text).strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        visuals = json.loads(text)
        if isinstance(visuals, list):
            return visuals
        return []

    except json.JSONDecodeError:
        logger.warning(f"Failed to parse vision response as JSON for {pdf_path}")
        return []
    except Exception as e:
        logger.error(f"Vision extraction failed for {pdf_path}: {e}")
        return []


def extract_full(
    pdf_path: str | Path,
    api_url: str | None = None,
    api_key: str | None = None,
    model: str = "gemini-2.0-flash",
) -> dict:
    """Extract both text and visuals from PDF.

    Returns:
        Dict with 'text' and 'visuals' keys
    """
    text = extract_text_from_pdf(pdf_path)
    visuals = extract_visuals_from_pdf(pdf_path, api_url, api_key, model)
    return {"text": text, "visuals": visuals}


def format_visuals_for_context(visuals: list[dict]) -> str:
    """Format extracted visuals as readable text for LLM context.

    Args:
        visuals: List of visual element dicts from extract_visuals_from_pdf

    Returns:
        Formatted string representation
    """
    if not visuals:
        return ""

    parts = []
    for i, v in enumerate(visuals, 1):
        vtype = v.get("type", "unknown")
        page = v.get("page", "?")
        desc = v.get("description", "")
        content = v.get("content", "")

        if vtype == "table":
            parts.append(f"[表格 {i}] (第{page}页) {desc}\n{content}")
        elif vtype == "figure":
            parts.append(f"[图片 {i}] (第{page}页) {desc}\n{content}")
        elif vtype == "formula":
            parts.append(f"[公式 {i}] (第{page}页) {desc}\n${content}$")
        else:
            parts.append(f"[{vtype} {i}] (第{page}页) {desc}\n{content}")

    return "\n\n".join(parts)
