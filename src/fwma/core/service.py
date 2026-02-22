from __future__ import annotations

from collections.abc import Callable
import json
import logging
import threading
import uuid
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from fwma.core.config import FWMAConfig
from fwma.core.pipeline import ResearchPipeline

logger = logging.getLogger(__name__)


def load_config() -> FWMAConfig:
    return FWMAConfig.load()


def load_research_config(config_path: Path) -> dict[str, Any]:
    import importlib

    try:
        toml_module = importlib.import_module("tomllib")
    except ModuleNotFoundError:
        toml_module = importlib.import_module("tomli")

    with open(config_path, "rb") as handle:
        data = toml_module.load(handle)

    requirement = data.get("requirement") or data.get("research", {}).get("requirement")
    sources = data.get("sources") or data.get("research", {}).get("sources") or []
    if not requirement or not sources:
        raise ValueError("Config must contain 'requirement' and 'sources'.")
    return {
        "requirement": requirement,
        "sources": sources,
        "name": data.get("name", config_path.stem),
        "run_id": data.get("run_id"),
    }


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunManager:
    def __init__(self, runs_root: Path | None = None):
        config = load_config()
        self.runs_root = Path(runs_root or config.runs_root or "./fwma_runs")
        self.runs_root.mkdir(parents=True, exist_ok=True)

    def create_run(
        self,
        requirement: str,
        sources: list[dict],
        name: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        generated = run_id is None
        run_id = run_id or f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        run_dir = self.runs_root / run_id
        if run_dir.exists() and generated:
            raise ValueError(f"Run directory already exists: {run_id}")
        run_dir.mkdir(parents=True, exist_ok=True)

        run_config: dict[str, Any] = {
            "run_id": run_id,
            "name": name or run_id,
            "requirement": requirement,
            "sources": sources,
            "created_at": datetime.now().isoformat(),
            "status": "created",
        }
        (run_dir / "run_config.json").write_text(
            json.dumps(run_config, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return run_config

    def get_run(self, run_id: str) -> dict[str, Any]:
        run_dir = self.runs_root / run_id
        config_path = run_dir / "run_config.json"
        if not config_path.exists():
            raise ValueError(f"Run {run_id} not found")

        config = json.loads(config_path.read_text(encoding="utf-8"))
        review_dir = run_dir / "review"
        report_dir = run_dir / "report"
        config["steps"] = {
            "crawl": (run_dir / "crawl" / "papers_metadata.json").exists(),
            "screen": (run_dir / "screen" / "screened_papers.json").exists(),
            "download": (run_dir / "download" / "downloaded_papers.json").exists(),
            "review": review_dir.exists() and any(review_dir.glob("*_review.json")),
            "report": report_dir.exists() and any(report_dir.glob("report_*.md")),
        }
        return config

    def list_runs(self) -> list[dict[str, Any]]:
        runs: list[dict[str, Any]] = []
        for run_dir in sorted(self.runs_root.iterdir(), key=lambda item: item.name):
            if not run_dir.is_dir() or not (run_dir / "run_config.json").exists():
                continue
            try:
                runs.append(self.get_run(run_dir.name))
            except Exception:
                logger.exception("Failed to load run metadata: %s", run_dir)
        return runs

    def get_pipeline(self, run_id: str) -> ResearchPipeline:
        run_dir = self.runs_root / run_id
        if not run_dir.exists():
            raise ValueError(f"Run {run_id} not found")
        config = load_config()
        return ResearchPipeline(
            run_dir=run_dir,
            screener_model=config.models.screener,
            chair_model=config.models.chair,
            member1_model=config.models.member1,
            member2_model=config.models.member2,
            openalex_mailto=config.openalex_mailto,
        )

    def read_artifact(self, run_id: str, path: str) -> str:
        run_dir = (self.runs_root / run_id).resolve()
        if not run_dir.exists():
            raise ValueError(f"Run {run_id} not found")

        artifact_path = (run_dir / path).resolve()
        if run_dir not in artifact_path.parents and artifact_path != run_dir:
            raise ValueError(f"Invalid artifact path: {path}")
        if not artifact_path.exists() or not artifact_path.is_file():
            raise FileNotFoundError(f"Artifact not found: {path}")
        return artifact_path.read_text(encoding="utf-8")


class JobManager:
    def __init__(self, runs_root: Path | None = None):
        self.run_manager = RunManager(runs_root)
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def submit(self, run_id: str, step: str, func: Callable[..., Any], *args: Any, **kwargs: Any) -> str:
        job_id = f"job_{step}_{uuid.uuid4().hex[:8]}"
        job: dict[str, Any] = {
            "job_id": job_id,
            "run_id": run_id,
            "step": step,
            "status": JobStatus.QUEUED,
            "created_at": datetime.now().isoformat(),
            "progress": None,
            "result": None,
            "error": None,
        }
        with self._lock:
            self._jobs[job_id] = job

        self._save_job(run_id, job)
        thread = threading.Thread(target=self._execute, args=(job_id, func, args, kwargs), daemon=True)
        thread.start()
        return job_id

    def get_job(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            if job_id in self._jobs:
                return self._to_jsonable(self._jobs[job_id])

        persisted = self._load_from_disk(job_id)
        if persisted is not None:
            with self._lock:
                self._jobs[job_id] = persisted
            return self._to_jsonable(persisted)

        raise ValueError(f"Job {job_id} not found")

    def list_run_jobs(self, run_id: str) -> list[dict[str, Any]]:
        with self._lock:
            jobs = [self._to_jsonable(job) for job in self._jobs.values() if job.get("run_id") == run_id]
        return sorted(jobs, key=lambda item: item.get("created_at", ""), reverse=True)

    def update_progress(self, job_id: str, current: int, total: int, message: str = "") -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job["progress"] = {"current": current, "total": total, "message": message}
            run_id = str(job["run_id"])
            snapshot = dict(job)
        self._save_job(run_id, snapshot)

    def _execute(
        self,
        job_id: str,
        func: Callable[..., Any],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job["status"] = JobStatus.RUNNING
            job["started_at"] = datetime.now().isoformat()
            run_id = str(job["run_id"])
            snapshot = dict(job)
        self._save_job(run_id, snapshot)

        try:
            result = func(*args, **kwargs)
            with self._lock:
                job["status"] = JobStatus.SUCCEEDED
                job["result"] = result
                job["completed_at"] = datetime.now().isoformat()
                snapshot = dict(job)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Job %s failed", job_id)
            with self._lock:
                job["status"] = JobStatus.FAILED
                job["error"] = str(exc)
                job["completed_at"] = datetime.now().isoformat()
                snapshot = dict(job)

        self._save_job(run_id, snapshot)

    def _save_job(self, run_id: str, job: dict[str, Any]) -> None:
        jobs_dir = self.run_manager.runs_root / run_id / "jobs"
        jobs_dir.mkdir(parents=True, exist_ok=True)
        job_file = jobs_dir / f"{job['job_id']}.json"
        job_file.write_text(json.dumps(self._to_jsonable(job), ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_from_disk(self, job_id: str) -> dict[str, Any] | None:
        for run_dir in self.run_manager.runs_root.iterdir():
            if not run_dir.is_dir():
                continue
            job_file = run_dir / "jobs" / f"{job_id}.json"
            if not job_file.exists():
                continue
            payload = json.loads(job_file.read_text(encoding="utf-8"))
            status = payload.get("status")
            if isinstance(status, str):
                try:
                    payload["status"] = JobStatus(status)
                except ValueError:
                    payload["status"] = JobStatus.FAILED
            return payload
        return None

    @staticmethod
    def _to_jsonable(job: dict[str, Any]) -> dict[str, Any]:
        return {k: (v.value if isinstance(v, JobStatus) else v) for k, v in job.items()}


class FWMAService:
    def __init__(self, runs_root: Path | None = None):
        self.run_manager = RunManager(runs_root)
        self.job_manager = JobManager(runs_root)
        self.config = load_config()

    def suggest_sources(self, requirement: str, model: str | None = None) -> dict[str, Any]:
        tmp_run_id = "_tmp_suggest"
        tmp_dir = self.run_manager.runs_root / tmp_run_id
        tmp_dir.mkdir(parents=True, exist_ok=True)
        pipeline = ResearchPipeline(
            run_dir=tmp_dir,
            screener_model=self.config.models.screener,
            chair_model=self.config.models.chair,
            member1_model=self.config.models.member1,
            member2_model=self.config.models.member2,
            openalex_mailto=self.config.openalex_mailto,
        )
        selected_model = model or "gemini/gemini-2.5-flash"
        suggestion = pipeline.suggest(requirement, model=selected_model)
        return {"requirement": requirement, "model": selected_model, "suggestion": suggestion}

    def create_run(
        self,
        requirement: str,
        sources: list[dict],
        name: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        return self.run_manager.create_run(requirement, sources, name, run_id)

    def crawl(self, run_id: str) -> dict[str, Any]:
        pipeline = self.run_manager.get_pipeline(run_id)
        run_config = self.run_manager.get_run(run_id)
        papers = pipeline.crawl(run_config.get("sources", []))
        return {"run_id": run_id, "papers_count": len(papers), "papers": papers[:5]}

    def screen(self, run_id: str, threshold: str = "high_medium") -> dict[str, Any]:
        pipeline = self.run_manager.get_pipeline(run_id)
        run_config = self.run_manager.get_run(run_id)
        requirement = str(run_config["requirement"])
        papers_file = self.run_manager.runs_root / run_id / "crawl" / "papers_metadata.json"
        if not papers_file.exists():
            raise ValueError(f"No crawled papers found for run {run_id}. Run crawl first.")
        papers = json.loads(papers_file.read_text(encoding="utf-8"))
        screened = pipeline.screen(papers, requirement, threshold)
        return {"run_id": run_id, "screened_count": len(screened), "threshold": threshold}

    def run_status(self, run_id: str) -> dict[str, Any]:
        run_info = self.run_manager.get_run(run_id)
        run_info["active_jobs"] = [
            {
                "job_id": job["job_id"],
                "step": job["step"],
                "status": job["status"],
                "progress": job.get("progress"),
            }
            for job in self.job_manager.list_run_jobs(run_id)
        ]
        return run_info

    def read_artifact(self, run_id: str, path: str) -> str:
        return self.run_manager.read_artifact(run_id, path)

    def download_async(self, run_id: str, concurrency: int = 8) -> str:
        pipeline = self.run_manager.get_pipeline(run_id)
        screened_file = self.run_manager.runs_root / run_id / "screen" / "screened_papers.json"
        if not screened_file.exists():
            raise ValueError(f"No screened papers for run {run_id}. Run screen first.")
        papers = json.loads(screened_file.read_text(encoding="utf-8"))
        return self.job_manager.submit(run_id, "download", pipeline.download, papers, concurrency)

    def review_async(self, run_id: str, max_rounds: int = 5) -> str:
        pipeline = self.run_manager.get_pipeline(run_id)
        run_config = self.run_manager.get_run(run_id)
        requirement = str(run_config["requirement"])
        downloaded_file = self.run_manager.runs_root / run_id / "download" / "downloaded_papers.json"
        if not downloaded_file.exists():
            raise ValueError(f"No downloaded papers for run {run_id}. Run download first.")
        papers = json.loads(downloaded_file.read_text(encoding="utf-8"))
        return self.job_manager.submit(run_id, "review", pipeline.review, papers, requirement, max_rounds)

    def report_async(self, run_id: str, format: str = "markdown") -> str:
        pipeline = self.run_manager.get_pipeline(run_id)
        run_config = self.run_manager.get_run(run_id)
        requirement = str(run_config["requirement"])
        reviews = self._load_reviews(run_id)
        return self.job_manager.submit(run_id, "report", pipeline.report, reviews, requirement, format)

    def writing_review_async(self, manuscript: str, max_rounds: int = 3) -> str:
        from fwma.parliament.writing import review_writing

        run_id = f"writing_{uuid.uuid4().hex[:8]}"
        run_dir = self.run_manager.runs_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        return self.job_manager.submit(run_id, "writing_review", review_writing, manuscript, max_rounds=max_rounds)

    def get_job_status(self, job_id: str) -> dict[str, Any]:
        return self.job_manager.get_job(job_id)

    def parliament_debate(self, topic: str, context: str | None = None, max_rounds: int = 5) -> dict[str, Any]:
        from fwma.parliament.debate import Parliament

        _ = max_rounds
        parliament = Parliament(
            chair_model=self.config.models.chair,
            member1_model=self.config.models.member1,
            member2_model=self.config.models.member2,
        )
        return parliament.hold_debate(topic, context or "")

    def pdf_vision(self, pdf_path: str) -> dict[str, Any]:
        from fwma.tools.pdf_vision import extract_full

        return extract_full(pdf_path)

    def citation_check(
        self,
        bib_index: dict[str, dict[Any, Any]] | str,
        manuscript: str | None = None,
    ) -> dict[str, Any]:
        from fwma.tools.citation_check import check_citations

        if isinstance(bib_index, str):
            parsed: dict[str, dict[Any, Any]] = {}
        else:
            parsed = bib_index
        return check_citations(parsed, manuscript=manuscript)

    def _load_reviews(self, run_id: str) -> list[dict[str, Any]]:
        review_dir = self.run_manager.runs_root / run_id / "review"
        if not review_dir.exists():
            return []

        reviews: list[dict[str, Any]] = []
        for review_file in sorted(review_dir.glob("*_review.json")):
            try:
                reviews.append(json.loads(review_file.read_text(encoding="utf-8")))
            except Exception:
                logger.exception("Failed to read review file: %s", review_file)
        return reviews
