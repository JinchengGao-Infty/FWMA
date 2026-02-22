"""FWMA — Full-Workflow Multi-Agent Literature Review."""

__version__ = "0.1.0"

from fwma.core.pipeline import ResearchPipeline
from fwma.parliament.debate import Parliament
from fwma.llm.client import LLMClient

__all__ = ["ResearchPipeline", "Parliament", "LLMClient", "__version__"]
