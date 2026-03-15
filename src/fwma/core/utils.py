"""
FWMA Core Utilities — JSON parsing, text processing helpers.
"""

import json
import logging
import re

logger = logging.getLogger(__name__)


def parse_json_response(text: str) -> dict:
    """Robust JSON parsing for LLM responses with regex fallback.

    Handles malformed JSON from LLMs by extracting key fields via regex.
    """
    if not text or not text.strip():
        return {"error": "empty_response", "raw": ""}

    try:
        # Clean markdown code blocks
        cleaned = text.strip()
        if cleaned.startswith("```"):
            first_newline = cleaned.find("\n")
            if first_newline != -1:
                cleaned = cleaned[first_newline + 1 :]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        # Try direct JSON parse
        return json.loads(cleaned)

    except json.JSONDecodeError as e:
        logger.debug(f"Direct JSON parse failed, trying regex fallback: {str(e)[:100]}")

        try:            # Regex fallback for common LLM response fields
            result = {}
            json_str = text

            # Extract role
            role_match = re.search(r'"role"\s*:\s*"([^"]+)"', json_str)
            if role_match:
                result["role"] = role_match.group(1)

            # Extract score
            score_match = re.search(r'"score"\s*:\s*(\d+(?:\.\d+)?)', json_str)
            if score_match:
                result["score"] = float(score_match.group(1))

            # Extract content (handles escaped quotes and newlines)
            content_match = re.search(r'"content"\s*:\s*"((?:[^"\\]|\\.|\\n)*)"', json_str, re.DOTALL)
            if content_match:
                raw_content = content_match.group(1)
                result["content"] = raw_content.replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\")
            else:
                content_match2 = re.search(r'"content"\s*:\s*"([^"]*(?:"[^"]*)*)"', json_str)
                if content_match2:
                    result["content"] = content_match2.group(1)

            # Extract vote
            vote_match = re.search(r'"vote"\s*:\s*(true|false)', json_str)
            if vote_match:
                result["vote"] = vote_match.group(1) == "true"
            else:
                result["vote"] = False

            # Extract next_speaker
            speaker_match = re.search(r'"next_speaker"\s*:\s*"([^"]+)"', json_str)
            if speaker_match:
                result["next_speaker"] = speaker_match.group(1)

            # Extract array fields
            for field in ["key_points", "application_ideas", "improvement_suggestions", "concerns"]:
                array_match = re.search(rf'"{field}"\s*:\s*\[(.*?)\]', json_str, re.DOTALL)
                if array_match:
                    array_content = array_match.group(1)
                    items = re.findall(r'"((?:[^"\\]|\\.)*)"', array_content)
                    result[field] = [item.replace("\\n", "\n").replace('\\"', '"') for item in items]
                else:
                    result[field] = []

            if result.get("role") or result.get("content"):
                return result

        except Exception as e2:
            logger.warning(f"Regex extraction failed: {str(e2)[:100]}")

        logger.warning(f"JSON parse error: {str(e)[:100]}")
        logger.warning(f"Raw text (first 300 chars): {text[:300]!r}")

    except Exception as e:
        logger.warning(f"Parse exception: {str(e)[:100]}")

    return {"error": "JSON解析失败", "raw": text[:500]}
