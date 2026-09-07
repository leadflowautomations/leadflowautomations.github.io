"""Persistent production entrypoint for the Lead Flow complete pipeline."""

from . import leadflow_v3 as core
from .job_store import PersistentJobs


# Keep the existing API/routes and replace only the volatile job registry.
core.JOBS = PersistentJobs()

app = core.app
