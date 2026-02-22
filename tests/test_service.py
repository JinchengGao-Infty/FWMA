"""Tests for FWMA service layer (RunManager, JobManager, FWMAService).

These are contract tests — they verify the service layer's behavior
without making real LLM API calls.
"""

import json
import time
import threading
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from fwma.core.service import RunManager, JobManager, JobStatus, FWMAService


@pytest.fixture
def tmp_runs(tmp_path):
    """Create a temporary runs directory."""
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    return runs_root


class TestRunManager:
    """Tests for RunManager."""

    def test_create_run(self, tmp_runs):
        rm = RunManager(runs_root=tmp_runs)
        result = rm.create_run(
            requirement="Find papers on transformer models",
            sources=[{"type": "openalex", "keywords": ["transformer"]}],
            name="test-run",
        )
        assert "run_id" in result
        assert result["requirement"] == "Find papers on transformer models"
        assert result["name"] == "test-run"
        # Check directory and config file created
        run_dir = tmp_runs / result["run_id"]
        assert run_dir.exists()
        assert (run_dir / "run_config.json").exists()

    def test_create_run_custom_id(self, tmp_runs):
        rm = RunManager(runs_root=tmp_runs)
        result = rm.create_run(
            requirement="test",
            sources=[],
            run_id="my_custom_run",
        )
        assert result["run_id"] == "my_custom_run"
        assert (tmp_runs / "my_custom_run").exists()

    def test_get_run(self, tmp_runs):
        rm = RunManager(runs_root=tmp_runs)
        created = rm.create_run(requirement="test", sources=[])
        run_id = created["run_id"]

        result = rm.get_run(run_id)
        assert result["run_id"] == run_id
        assert result["requirement"] == "test"
        assert "steps" in result
        # No steps completed yet
        assert result["steps"]["crawl"] is False
        assert result["steps"]["screen"] is False

    def test_get_run_not_found(self, tmp_runs):
        rm = RunManager(runs_root=tmp_runs)
        with pytest.raises(ValueError, match="not found"):
            rm.get_run("nonexistent_run")

    def test_list_runs_empty(self, tmp_runs):
        rm = RunManager(runs_root=tmp_runs)
        assert rm.list_runs() == []

    def test_list_runs(self, tmp_runs):
        rm = RunManager(runs_root=tmp_runs)
        rm.create_run(requirement="run1", sources=[])
        rm.create_run(requirement="run2", sources=[])
        runs = rm.list_runs()
        assert len(runs) == 2

    def test_get_run_step_completion(self, tmp_runs):
        rm = RunManager(runs_root=tmp_runs)
        created = rm.create_run(requirement="test", sources=[])
        run_id = created["run_id"]
        run_dir = tmp_runs / run_id

        # Simulate crawl completion
        crawl_dir = run_dir / "crawl"
        crawl_dir.mkdir()
        (crawl_dir / "papers_metadata.json").write_text("[]")

        result = rm.get_run(run_id)
        assert result["steps"]["crawl"] is True
        assert result["steps"]["screen"] is False

    def test_read_artifact(self, tmp_runs):
        rm = RunManager(runs_root=tmp_runs)
        created = rm.create_run(requirement="test", sources=[])
        run_id = created["run_id"]

        # Create an artifact
        report_dir = tmp_runs / run_id / "report"
        report_dir.mkdir()
        (report_dir / "report.md").write_text("# Test Report\nContent here.")

        content = rm.read_artifact(run_id, "report/report.md")
        assert "Test Report" in content

    def test_read_artifact_not_found(self, tmp_runs):
        rm = RunManager(runs_root=tmp_runs)
        created = rm.create_run(requirement="test", sources=[])
        with pytest.raises(FileNotFoundError):
            rm.read_artifact(created["run_id"], "nonexistent.json")


class TestJobManager:
    """Tests for JobManager."""

    def test_submit_and_get(self, tmp_runs):
        jm = JobManager(runs_root=tmp_runs)
        # Create a run first
        jm.run_manager.create_run(requirement="test", sources=[], run_id="test_run")

        def dummy_task():
            return {"result": "ok"}

        job_id = jm.submit("test_run", "crawl", dummy_task)
        assert job_id.startswith("job_crawl_")

        # Wait for completion
        time.sleep(0.5)
        job = jm.get_job(job_id)
        assert job["status"] == JobStatus.SUCCEEDED
        assert job["result"] == {"result": "ok"}

    def test_submit_failing_task(self, tmp_runs):
        jm = JobManager(runs_root=tmp_runs)
        jm.run_manager.create_run(requirement="test", sources=[], run_id="test_run")

        def failing_task():
            raise ValueError("Something went wrong")

        job_id = jm.submit("test_run", "download", failing_task)
        time.sleep(0.5)

        job = jm.get_job(job_id)
        assert job["status"] == JobStatus.FAILED
        assert "Something went wrong" in job["error"]

    def test_job_not_found(self, tmp_runs):
        jm = JobManager(runs_root=tmp_runs)
        with pytest.raises(ValueError, match="not found"):
            jm.get_job("nonexistent_job")

    def test_update_progress(self, tmp_runs):
        jm = JobManager(runs_root=tmp_runs)
        jm.run_manager.create_run(requirement="test", sources=[], run_id="test_run")
        import threading
        barrier = threading.Event()
        progress_job_id = {"id": None}
        def slow_task():
            barrier.wait()
            for i in range(3):
                jm.update_progress(progress_job_id["id"], i + 1, 3, f"Step {i + 1}")
                time.sleep(0.1)
            return "done"
        job_id = jm.submit("test_run", "review", slow_task)
        progress_job_id["id"] = job_id
        barrier.set()
        time.sleep(1)
        job = jm.get_job(job_id)
        assert job["status"] == JobStatus.SUCCEEDED
        assert job["progress"] is not None

    def test_job_persisted_to_disk(self, tmp_runs):
        jm = JobManager(runs_root=tmp_runs)
        jm.run_manager.create_run(requirement="test", sources=[], run_id="test_run")

        job_id = jm.submit("test_run", "crawl", lambda: "ok")
        time.sleep(0.5)

        # Check job file exists on disk
        job_file = tmp_runs / "test_run" / "jobs" / f"{job_id}.json"
        assert job_file.exists()
        job_data = json.loads(job_file.read_text())
        assert job_data["status"] == "succeeded"


class TestFWMAService:
    """Tests for FWMAService (high-level API)."""

    @patch("fwma.core.service.FWMAConfig")
    def test_create_run(self, mock_config_cls, tmp_runs):
        mock_config = MagicMock()
        mock_config.runs_root = str(tmp_runs)
        mock_config.models = {}
        mock_config_cls.load.return_value = mock_config

        service = FWMAService(runs_root=tmp_runs)
        result = service.create_run(
            requirement="test requirement",
            sources=[{"type": "openalex", "keywords": ["test"]}],
        )
        assert "run_id" in result
        assert result["requirement"] == "test requirement"

    @patch("fwma.core.service.FWMAConfig")
    def test_run_status(self, mock_config_cls, tmp_runs):
        mock_config = MagicMock()
        mock_config.runs_root = str(tmp_runs)
        mock_config.models = {}
        mock_config_cls.load.return_value = mock_config

        service = FWMAService(runs_root=tmp_runs)
        created = service.create_run(requirement="test", sources=[])

        status = service.run_status(created["run_id"])
        assert status["run_id"] == created["run_id"]
        assert "steps" in status
        assert "active_jobs" in status

    @patch("fwma.core.service.FWMAConfig")
    def test_get_job_status(self, mock_config_cls, tmp_runs):
        mock_config = MagicMock()
        mock_config.runs_root = str(tmp_runs)
        mock_config.models = {}
        mock_config_cls.load.return_value = mock_config

        service = FWMAService(runs_root=tmp_runs)
        created = service.create_run(requirement="test", sources=[], run_id="test_run")

        # Submit a dummy job via job_manager
        job_id = service.job_manager.submit("test_run", "test", lambda: "ok")
        time.sleep(0.5)

        status = service.get_job_status(job_id)
        assert status["status"] == JobStatus.SUCCEEDED
