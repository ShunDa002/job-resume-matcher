from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from typing import Any
from uuid import uuid4

from .adapters import get_adapter
from .db import connect, get_jobs
from .util import sha256_data
from .worker import (
    BatchExtractionResult,
    commit_batch,
    ensure_extraction_cache_table,
    execute_batches_parallel,
    make_batches,
    process_batch,
    render_prompt,
    render_repair_prompt,
    verify,
)

DDL = "CREATE TABLE IF NOT EXISTS extraction_cache(task_key TEXT PRIMARY KEY,job_id TEXT,payload TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP)"


def render(path: Path | str, inp: dict[str, Any], errors: Any = None, invalid: Any = None) -> str:
    if errors or invalid:
        return render_repair_prompt(path, inp, errors, invalid)
    return render_prompt(path, inp)


def extract(
    db: str,
    workspace: Path | str,
    batch_size: int = 5,
    force: bool = False,
    executable: str | None = None,
    adapter: str = "antigravity",
    workers: int = 3,
    adapter_name: str | None = None,
    submission_delay_seconds: float = 0.0,
) -> dict[str, Any]:
    w = Path(workspace).resolve()
    name = adapter_name or adapter
    a = get_adapter(name, w, executable)
    probe = a.probe()
    if not probe.get("ok"):
        raise RuntimeError(f"{name} probe failed: {probe}")

    schema_path = w / "schemas/extraction-result.schema.json"
    prompt_path = w / "prompts/extract-requirements.v1.md"
    repair_path = w / "prompts/repair-extraction.v1.md"

    ph = sha256_data(prompt_path.read_text(encoding="utf-8"))
    sh = sha256_data(json.loads(schema_path.read_text(encoding="utf-8")))
    ch = sha256_data(a.c)
    cache_metadata = {
        "prompt_hash": ph,
        "schema_hash": sh,
        "adapter_config_hash": ch,
    }

    with connect(db) as conn:
        ensure_extraction_cache_table(conn)

    all_jobs = get_jobs(db)
    jobs_by_id = {j.job_id: j for j in all_jobs}
    pending: list[tuple[Any, str]] = []
    cached = 0

    with connect(db) as conn:
        for j in all_jobs:
            key = sha256_data({
                "job": j.content_hash,
                "prompt": ph,
                "schema": sh,
                "config": ch,
            })
            row = conn.execute("SELECT 1 FROM extraction_cache WHERE task_key=?", (key,)).fetchone()
            if row and not force:
                cached += 1
            else:
                pending.append((j, key))

    run_id = datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%SZ-") + uuid4().hex[:6]
    run_audit_dir = w / "data" / "output" / "extraction-audit" / name / run_id

    total_duration = 0.0
    completed_job_count = 0
    failed_job_ids: list[str] = []
    total_batch_count = 0

    if pending:
        process_kwargs = {
            "adapter_name": name,
            "adapter_config": a.c,
            "workspace": w,
            "executable": executable,
            "schema_path": schema_path,
            "prompt_path": prompt_path,
            "repair_path": repair_path,
            "run_id": run_id,
        }

        start_time = monotonic()
        completed_batches, failed_batches = execute_batches_parallel(
            pending=pending,
            batch_size=batch_size,
            workers=workers,
            process_kwargs=process_kwargs,
            db_path=db,
            jobs_by_id=jobs_by_id,
            cache_metadata=cache_metadata,
            submission_delay_seconds=submission_delay_seconds,
        )
        total_duration = monotonic() - start_time
        completed_job_count = sum(len(b.job_keys) for b in completed_batches)
        failed_job_ids = [job_id for b in failed_batches for job_id, _ in b.job_keys]
        total_batch_count = len(completed_batches) + len(failed_batches)

    run_audit_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "probe": probe,
        "adapter": name,
        "total": len(all_jobs),
        "cached": cached,
        "completed": completed_job_count,
        "failed": failed_job_ids,
        "workers": workers,
        "batches": total_batch_count,
        "duration_seconds": round(total_duration, 2),
        "run_id": run_id,
    }

    try:
        (run_audit_dir / "run-summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass

    return summary
