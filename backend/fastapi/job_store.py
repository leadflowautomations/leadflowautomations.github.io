"""Durable Lead Flow research job storage with safe in-memory fallback."""

from __future__ import annotations

import os
import threading
from collections.abc import Iterator, MutableMapping
from typing import Any


class PersistentJob(dict[str, Any]):
    def __init__(self, store: "PersistentJobs", job_id: str, initial: dict[str, Any] | None = None):
        self._store = store
        self._job_id = job_id
        super().__init__(initial or {})

    def __setitem__(self, key: str, value: Any) -> None:
        super().__setitem__(key, value)
        self._store._save(self)

    def update(self, *args: Any, **kwargs: Any) -> None:
        super().update(*args, **kwargs)
        self._store._save(self)

    def setdefault(self, key: str, default: Any = None) -> Any:
        value = super().setdefault(key, default)
        self._store._save(self)
        return value


class PersistentJobs(MutableMapping[str, PersistentJob]):
    """Mapping-compatible job store backed by Render Postgres when DATABASE_URL exists.

    The database is deliberately optional: a transient in-memory mode keeps local
    development and deployments without the database wiring functional.
    """

    def __init__(self) -> None:
        self._cache: dict[str, PersistentJob] = {}
        self._lock = threading.RLock()
        self._database_url = os.getenv("DATABASE_URL", "").strip()
        self._db_ready = False
        if self._database_url:
            self._ensure_schema()

    @property
    def persistent(self) -> bool:
        return bool(self._database_url and self._db_ready)

    def _connect(self):
        if not self._database_url:
            return None
        import psycopg

        return psycopg.connect(self._database_url)

    def _ensure_schema(self) -> None:
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS leadflow_research_jobs (
                        job_id TEXT PRIMARY KEY,
                        payload JSONB NOT NULL,
                        updated_at DOUBLE PRECISION NOT NULL
                    )
                    """
                )
                conn.commit()
            self._db_ready = True
        except Exception as exc:
            self._db_ready = False
            print(f"Lead Flow persistence unavailable; using memory fallback: {exc}", flush=True)

    def _save(self, job: PersistentJob) -> None:
        with self._lock:
            self._cache[job._job_id] = job
            if not self.persistent:
                return
            try:
                from psycopg.types.json import Jsonb

                updated_at = float(job.get("updated_at") or 0)
                with self._connect() as conn:
                    conn.execute(
                        """
                        INSERT INTO leadflow_research_jobs (job_id, payload, updated_at)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (job_id) DO UPDATE SET
                            payload = EXCLUDED.payload,
                            updated_at = EXCLUDED.updated_at
                        """,
                        (job._job_id, Jsonb(dict(job)), updated_at),
                    )
                    conn.commit()
            except Exception as exc:
                print(f"Lead Flow persistence write failed: {exc}", flush=True)

    def _load(self, job_id: str) -> PersistentJob | None:
        if not self.persistent:
            return None
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT payload FROM leadflow_research_jobs WHERE job_id = %s",
                    (job_id,),
                ).fetchone()
            if row:
                job = PersistentJob(self, job_id, row[0])
                self._cache[job_id] = job
                return job
        except Exception as exc:
            print(f"Lead Flow persistence read failed: {exc}", flush=True)
        return None

    def __getitem__(self, job_id: str) -> PersistentJob:
        with self._lock:
            job = self._cache.get(job_id)
            if job is not None:
                return job
            job = self._load(job_id)
            if job is not None:
                return job
            raise KeyError(job_id)

    def __setitem__(self, job_id: str, value: dict[str, Any]) -> None:
        job = value if isinstance(value, PersistentJob) else PersistentJob(self, job_id, dict(value))
        self._cache[job_id] = job
        self._save(job)

    def __delitem__(self, job_id: str) -> None:
        with self._lock:
            self._cache.pop(job_id, None)
            if self.persistent:
                try:
                    with self._connect() as conn:
                        conn.execute("DELETE FROM leadflow_research_jobs WHERE job_id = %s", (job_id,))
                        conn.commit()
                except Exception as exc:
                    print(f"Lead Flow persistence delete failed: {exc}", flush=True)

    def __iter__(self) -> Iterator[str]:
        return iter(self._all_ids())

    def __len__(self) -> int:
        return len(self._all_ids())

    def __contains__(self, job_id: object) -> bool:
        if not isinstance(job_id, str):
            return False
        if job_id in self._cache:
            return True
        return self._load(job_id) is not None

    def _all_ids(self) -> list[str]:
        if not self.persistent:
            return list(self._cache)
        try:
            with self._connect() as conn:
                rows = conn.execute("SELECT job_id FROM leadflow_research_jobs ORDER BY updated_at DESC").fetchall()
            return [row[0] for row in rows]
        except Exception as exc:
            print(f"Lead Flow persistence listing failed: {exc}", flush=True)
            return list(self._cache)

    def values(self):
        for job_id in self._all_ids():
            try:
                yield self[job_id]
            except KeyError:
                continue
