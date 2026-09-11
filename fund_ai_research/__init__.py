"""Fund AI research MVP package.

The package exposes the pipeline for callers that need it, but keeps that
import lazy.  Streamlit imports the analysis module during app startup and
should not have to initialize every data connector before the analysis API is
available.
"""

__all__ = ["PipelineResult", "run_pipeline"]


def __getattr__(name):
    if name in __all__:
        from .pipeline import PipelineResult, run_pipeline

        return {"PipelineResult": PipelineResult, "run_pipeline": run_pipeline}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
