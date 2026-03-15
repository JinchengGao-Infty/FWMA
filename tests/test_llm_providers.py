"""Regression tests for provider hard timeouts and review execution mode."""

from __future__ import annotations

import socketserver
import threading
import time
from http.server import BaseHTTPRequestHandler

import pytest
import requests

from fwma.llm import providers
from fwma.parliament import review as review_module
from fwma.parliament.debate import Parliament


class _DribbleHandler(BaseHTTPRequestHandler):
    """Send response headers, then keep the chunked body open with tiny chunks."""

    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        deadline = time.monotonic() + 5
        try:
            while time.monotonic() < deadline:
                self.wfile.write(b"1\r\n \r\n")
                self.wfile.flush()
                time.sleep(0.05)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return


class _ReusableTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True


@pytest.fixture
def dribble_server() -> str:
    server = _ReusableTCPServer(("127.0.0.1", 0), _DribbleHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


def test_call_with_retry_enforces_hard_timeout(monkeypatch: pytest.MonkeyPatch, dribble_server: str) -> None:
    monkeypatch.setattr(providers, "MAX_RETRIES", 0)

    started_at = time.monotonic()
    with pytest.raises(requests.exceptions.Timeout, match="hard timeout"):
        providers._call_with_retry(
            requests.post,
            "anthropic",
            f"{dribble_server}/v1/messages",
            headers={"Content-Type": "application/json"},
            json={"model": "claude-opus-4-6", "messages": [], "stream": False},
            timeout=(0.2, 0.2),
            hard_timeout_seconds=0.5,
        )
    elapsed = time.monotonic() - started_at

    assert elapsed < 3


def test_clone_parliament_creates_fresh_client() -> None:
    parliament = Parliament()

    cloned = review_module._clone_parliament(parliament)

    assert cloned is not parliament
    assert cloned.client is not parliament.client
    assert cloned.client.api_keys == parliament.client.api_keys


def test_review_batch_serial_mode_skips_threadpool(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_executor(*args: object, **kwargs: object) -> None:
        raise AssertionError("ThreadPoolExecutor should not be used for concurrency=1")

    def fake_review_paper(
        paper: dict,
        user_requirement: str,
        parliament: object | None = None,
        pdf_path: object | None = None,
        vision_model: str = "gemini/gemini-3-flash",
    ) -> dict:
        return {
            "paper_info": {"title": paper["title"]},
            "debate_history": [],
            "final_verdict": {"score": 4, "requirement": user_requirement},
        }

    monkeypatch.setattr(review_module, "ThreadPoolExecutor", fail_executor)
    monkeypatch.setattr(review_module, "review_paper", fake_review_paper)

    results = review_module.review_batch(
        papers=[{"title": "Paper A"}, {"title": "Paper B"}],
        user_requirement="KAN-Reg",
        parliament=object(),
        concurrency=1,
    )

    assert [result["paper_info"]["title"] for result in results] == ["Paper A", "Paper B"]
