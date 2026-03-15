from __future__ import annotations

import time

from fwma.core.utils import parse_json_response


def test_parse_json_response_extracts_common_fields_from_invalid_json() -> None:
    response = """
    Here is the result:
    {
      "role": "assistant",
      "content": "Use adaptive grids\\nfor the regularizer.",
      "score": 4,
      "vote": true,
      "next_speaker": "chair",
      "application_ideas": ["grid adaptation", "shape constraints"],
      "concerns": ["refit instability"],
    }
    trailing explanation
    """

    parsed = parse_json_response(response)

    assert parsed["role"] == "assistant"
    assert parsed["content"] == "Use adaptive grids\nfor the regularizer."
    assert parsed["score"] == 4.0
    assert parsed["vote"] is True
    assert parsed["next_speaker"] == "chair"
    assert parsed["application_ideas"] == ["grid adaptation", "shape constraints"]
    assert parsed["concerns"] == ["refit instability"]
    assert parsed["key_points"] == []
    assert parsed["improvement_suggestions"] == []


def test_parse_json_response_returns_quickly_for_large_malformed_content() -> None:
    pathological = '{"role":"assistant","content":"' + ('\\\\\\"' * 80_000) + ',"vote":true'

    started_at = time.perf_counter()
    parsed = parse_json_response(pathological)
    elapsed = time.perf_counter() - started_at

    assert elapsed < 1.5
    assert isinstance(parsed, dict)
    assert parsed.get("role") == "assistant"
