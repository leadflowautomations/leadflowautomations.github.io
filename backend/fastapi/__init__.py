"""Lead Flow FastAPI package runtime bootstrap."""

import builtins
import sys


_original_import = builtins.__import__


def _leadflow_import(name, globals=None, locals=None, fromlist=(), level=0):
    module = _original_import(name, globals, locals, fromlist, level)
    if name == "backend.fastapi.leadflow_v3":
        target = sys.modules.get(name)
        if target is not None and not getattr(target, "_leadflow_package_bootstrapped", False):
            try:
                from .job_store import PersistentJobs

                target.JOBS = PersistentJobs()
                target._leadflow_package_bootstrapped = True
                print(
                    f"Lead Flow durable job store active: {getattr(target.JOBS, 'persistent', False)}",
                    flush=True,
                )
            except Exception as exc:
                print(f"Lead Flow durable job store unavailable: {exc}", flush=True)
    return module


builtins.__import__ = _leadflow_import
