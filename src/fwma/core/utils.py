"""
FWMA Core Utilities — JSON parsing, text processing helpers.
"""

import json
import logging

logger = logging.getLogger(__name__)

# Max text length for regex fallback — longer texts cause catastrophic backtracking
_MAX_REGEX_LEN = 5000


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

        # Try to find JSON object in text
        start = cleaned.find("{")
        if start > 0:
            cleaned = cleaned[start:]

        # Find matching closing brace
        if cleaned.startswith("{"):
            depth = 0
            in_string = False
            escape = False
            for i, ch in enumerate(cleaned):
                if escape:
                    escape = False
                    continue
                if ch == '\\' and in_string:
                    escape = True
                    continue
                if ch == '"' and not escape:
                    in_string = not in_string
                    continue
                if in_string:
                    continue
                if ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0:
                        cleaned = cleaned[:i + 1]
                        break

        # Try direct JSON parse
        return json.loads(cleaned)

    except json.JSONDecodeError as e:
        logger.debug(f"Direct JSON parse failed: {str(e)[:100]}")

        # Simple field extraction — no complex regex, no backtracking risk
        try:
            result = {}

            # score — just find the number
            import re
            score_match = re.search(r'"score"\s*:\s*(\d+(?:\.\d+)?)', text[:2000])
            if score_match:
                result["score"] = float(score_match.group(1))

            # vote
            vote_match = re.search(r'"vote"\s*:\s*(true|false|"end"|"continue")', text[:2000])
            if vote_match:
                v = vote_match.group(1)
                result["vote"] = v in ("true", '"end"')
            else:
                result["vote"] = False

            # role
            role_match = re.search(r'"role"\s*:\s*"([^"]+)"', text[:1000])
            if role_match:
                result["role"] = role_match.group(1)

            # content — just take everything after "content": " up to a reasonable limit
            # Avoid catastrophic backtracking by not using .* or DOTALL
            content_start = text.find('"content"')
            if content_start != -1:
                # Find the opening quote of the value
                colon_pos = text.find(':', content_start + 9)
                if colon_pos != -1:
                    quote_pos = text.find('"', colon_pos + 1)
                    if quote_pos != -1:
                        # Take up to 5000 chars as content preview
                        result["content"] = text[quote_pos + 1:quote_pos + 5001].split('","')[0]

            # key_points — simple extraction
            for field in ["key_points", "application_ideas", "improvement_suggestions", "concerns"]:
                field_start = text.find(f'"{field}"')
                if field_start != -1:
                    bracket_start = text.find('[', field_start)
                    bracket_end = text.find(']', bracket_start) if bracket_start != -1 else -1
                    if bracket_start != -1 and bracket_end != -1 and (bracket_end - bracket_start) < 10000:
                        try:
                            result[field] = json.loads(text[bracket_start:bracket_end + 1])
                        except json.JSONDecodeError:
                            result[field] = []
                    else:
                        result[field] = []
                else:
                    result[field] = []

            if result.get("score") is not None or result.get("content"):
                return result

        except Exception as e2:
            logger.warning(f"Field extraction failed: {str(e2)[:100]}")

        logger.warning(f"JSON parse error: {str(e)[:100]}")
        logger.warning(f"Raw text (first 300 chars): {text[:300]!r}")

    except Exception as e:
        logger.warning(f"Parse exception: {str(e)[:100]}")

    return {"error": "JSON解析失败", "raw": text[:500]}
