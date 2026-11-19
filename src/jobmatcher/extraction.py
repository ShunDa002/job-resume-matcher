"""Muse-native job extraction: prepare a prompt bundle, Muse fills it in,
then apply validates and commits it.

This replaces the old CLI-agent adapter layer entirely. There are no
subprocess adapters (no Antigravity / Claude / Codex / Copilot CLIs),
no API keys, and no model calls in this code. The extractor is Muse,
working in the loop:

1. ``jobmatch prepare-jobs`` writes one bundle per batch under
   ``data/output/muse-extraction/<run_id>/batch-000000/`` containing
   ``prompt.txt`` (rendered from ``prompts/extract-requirements.v3.md``),
   ``input.json``, ``schema.json``, and an empty ``extraction.json``
   placeholder. Nothing is extracted yet; the batch status is
   ``awaiting_muse``.
2. Muse reads the bundle, extracts structured facts using only the
   supplied job text, and writes the result (one JSON object matching
   ``schemas/extraction-result.schema.json``) into ``extraction.json``.
3. ``jobmatch apply-jobs --run <run_id>`` validates every supplied
   ``extraction.json`` with Pydantic + exact-substring evidence checks.
   Valid batches are committed to SQLite and cached; invalid batches
   get a ``repair-prompt.txt`` and status ``needs_repair``, and Muse
   fixes ``extraction.json`` and re-runs ``apply-jobs``. A batch with
   no ``extraction.json`` yet stays ``awaiting_muse`` and is not a
   failure.

The cache key is still a hash of job content + prompt + schema, plus
the extractor identity (``muse``). The ``adapter_config_hash`` column
in ``extraction_cache`` now stores that extractor hash; the column
name is kept so existing databases keep working.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from typing import Any
from uuid import uuid4

from .db import connect, get_jobs
from .util import sha256_data
from .worker import (
    BatchExtractionResult,
    commit_batch,
    duplicate_evidence_warnings,
    ensure_extraction_cache_table,
    make_batches,
    render_prompt,
    render_repair_prompt,
    validate_agent_result,
)

EXTRACTOR = "muse"


def _paths(workspace: Path) -> dict[str, Path]:
    # Prompts/schemas live with the repo, not necessarily with the cwd
    # the user runs jobmatch from (e.g. tests run from a temp dir).
    # The audit bundles themselves always stay under ``workspace``.
    base = workspace
    if not (base / "schemas" / "extraction-result.schema.json").exists():
        base = Path(__file__).resolve().parents[2]
    return {
        "schema": base / "schemas" / "extraction-result.schema.json",
        "prompt": base / "prompts" / "extract-requirements.v3.md",
        "repair": base / "prompts" / "repair-extraction.v1.md",
    }


def _cache_metadata(workspace: Path) -> dict[str, str]:
    paths = _paths(workspace)
    return {
        "prompt_hash": sha256_data(paths["prompt"].read_text(encoding="utf-8")),
        "schema_hash": sha256_data(json.loads(paths["schema"].read_text(encoding="utf-8"))),
        # Formerly the adapter config hash; now the extractor identity.
        "adapter_config_hash": sha256_data({"extractor": EXTRACTOR}),
    }


def _audit_base(workspace: Path, run_id: str) -> Path:
    return workspace / "data" / "output" / "muse-extraction" / run_id


def _write_status(batch_dir: Path, status: str, **extra: Any) -> None:
    payload = {
        "status": status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        **extra,
    }
    (batch_dir / "status.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _batch_input(chunk: list) -> dict[str, Any]:
    input_jobs = [
        {
            "job_id": job.job_id,
            "title": job.title,
            "company": job.company,
            "location_country_code": job.location_country_code,
            "description": job.description,
        }
        for job, _ in chunk
    ]
    return {"schema_version": "extraction-input.v1", "jobs": input_jobs}


def prepare_extraction(
    db: str,
    workspace: Path | str,
    batch_size: int = 5,
    force: bool = False,
) -> dict[str, Any]:
    """Write Muse prompt bundles for every uncached job. Returns a summary."""
    w = Path(workspace).resolve()
    paths = _paths(w)
    cache_metadata = _cache_metadata(w)

    with connect(db) as conn:
        ensure_extraction_cache_table(conn)

    all_jobs = get_jobs(db)
    pending: list[tuple[Any, str]] = []
    cached = 0

    with connect(db) as conn:
        for j in all_jobs:
            key = sha256_data({
                "job": j.content_hash,
                "prompt": cache_metadata["prompt_hash"],
                "schema": cache_metadata["schema_hash"],
                "config": cache_metadata["adapter_config_hash"],
            })
            row = conn.execute(
                "SELECT 1 FROM extraction_cache WHERE task_key=?", (key,)
            ).fetchone()
            if row and not force:
                cached += 1
            else:
                pending.append((j, key))

    run_id = datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%SZ-") + uuid4().hex[:6]
    run_dir = _audit_base(w, run_id)
    run_dir.mkdir(parents=True, exist_ok=True)

    batches: list[dict[str, Any]] = []
    for batch_number, chunk in enumerate(make_batches(pending, maximum_jobs=batch_size)):
        batch_id = f"batch-{batch_number:06d}"
        batch_dir = run_dir / batch_id
        batch_dir.mkdir(parents=True, exist_ok=True)
        input_object = _batch_input(chunk)
        prompt = render_prompt(paths["prompt"], input_object)
        (batch_dir / "input.json").write_text(
            json.dumps(input_object, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (batch_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
        (batch_dir / "schema.json").write_text(
            paths["schema"].read_text(encoding="utf-8"), encoding="utf-8"
        )
        # Placeholder for Muse to fill in. Apply treats a missing or
        # empty file as "awaiting_muse", never as a failure.
        (batch_dir / "extraction.json").write_text("", encoding="utf-8")
        _write_status(
            batch_dir, "awaiting_muse",
            batch_id=batch_id,
            job_ids=[job.job_id for job, _ in chunk],
        )
        batches.append({
            "batch_id": batch_id,
            "job_ids": [job.job_id for job, _ in chunk],
            "bundle": str(batch_dir),
        })

    summary = {
        "extractor": EXTRACTOR,
        "total": len(all_jobs),
        "cached": cached,
        "pending": len(pending),
        "batches": batches,
        "run_id": run_id,
    }
    (run_dir / "run-summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return summary


def apply_extraction(
    db: str,
    workspace: Path | str,
    run_id: str,
    batch_id: str | None = None,
) -> dict[str, Any]:
    """Validate Muse-supplied extraction.json files and commit valid batches."""
    w = Path(workspace).resolve()
    paths = _paths(w)
    cache_metadata = _cache_metadata(w)
    run_dir = _audit_base(w, run_id)
    if not run_dir.exists():
        raise FileNotFoundError(f"No Muse extraction run found: {run_dir}")

    all_jobs = get_jobs(db)
    jobs_by_id = {j.job_id: j for j in all_jobs}

    batch_dirs = sorted(
        d for d in run_dir.iterdir()
        if d.is_dir() and d.name.startswith("batch-")
        and (batch_id is None or d.name == batch_id)
    )
    if batch_id is not None and not batch_dirs:
        raise FileNotFoundError(f"No batch '{batch_id}' under {run_dir}")

    completed: list[str] = []
    needs_repair: list[dict[str, Any]] = []
    awaiting: list[str] = []
    failed: list[str] = []
    all_warnings: list[dict[str, Any]] = []

    for batch_dir in batch_dirs:
        bid = batch_dir.name
        input_object = json.loads((batch_dir / "input.json").read_text(encoding="utf-8"))
        input_jobs = input_object["jobs"]
        job_keys = [
            (j["job_id"], sha256_data({
                "job": jobs_by_id[j["job_id"]].content_hash,
                "prompt": cache_metadata["prompt_hash"],
                "schema": cache_metadata["schema_hash"],
                "config": cache_metadata["adapter_config_hash"],
            }))
            for j in input_jobs
        ]

        extraction_path = batch_dir / "extraction.json"
        raw_text = extraction_path.read_text(encoding="utf-8").strip() if extraction_path.exists() else ""
        if not raw_text:
            awaiting.append(bid)
            _write_status(batch_dir, "awaiting_muse", batch_id=bid,
                          job_ids=[j["job_id"] for j in input_jobs])
            continue

        try:
            raw = json.loads(raw_text)
            load_errors: list[Any] = []
        except json.JSONDecodeError as e:
            raw, load_errors = None, [f"invalid_json: {e}"]

        started = monotonic()
        parsed, errors = validate_agent_result((raw, load_errors), input_jobs)
        duration = monotonic() - started

        if errors:
            # One repair round per apply: write the repair prompt and
            # wait for Muse to fix extraction.json, then re-run apply.
            invalid = raw
            repair_prompt = render_repair_prompt(
                paths["repair"], input_object, errors, invalid
            )
            (batch_dir / "repair-prompt.txt").write_text(repair_prompt, encoding="utf-8")
            (batch_dir / "validation.json").write_text(
                json.dumps({"valid": False, "errors": errors,
                            "duration_seconds": round(duration, 2),
                            "attempts": 1}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            _write_status(batch_dir, "needs_repair", batch_id=bid,
                          job_ids=[j["job_id"] for j in input_jobs],
                          errors=errors)
            needs_repair.append({"batch_id": bid, "errors": errors})
            continue

        result = BatchExtractionResult(
            batch_id=bid,
            job_keys=job_keys,
            extracted_jobs=parsed.jobs if parsed else [],
            valid=True,
            errors=[],
            attempts=1,
            duration_seconds=round(duration, 2),
        )
        # Non-blocking: same-evidence requirements (usually an 'or'
        # list split into separate requirements). Recorded for Muse to
        # review; the batch still commits.
        warnings = duplicate_evidence_warnings(parsed) if parsed else []
        if warnings:
            all_warnings.append({"batch_id": bid, "warnings": warnings})
        try:
            commit_batch(db, result, jobs_by_id, cache_metadata)
        except Exception as e:  # keep a bad batch from corrupting the DB
            failed.append(bid)
            _write_status(batch_dir, "failed", batch_id=bid,
                          job_ids=[j["job_id"] for j in input_jobs],
                          errors=[str(e)])
            continue

        (batch_dir / "validation.json").write_text(
            json.dumps({"valid": True, "errors": [], "warnings": warnings,
                        "duration_seconds": round(duration, 2),
                        "attempts": 1}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        _write_status(batch_dir, "completed", batch_id=bid,
                      job_ids=[j["job_id"] for j in input_jobs],
                      duration_seconds=round(duration, 2),
                      warnings=warnings)
        completed.extend(j["job_id"] for j in input_jobs)

    summary = {
        "extractor": EXTRACTOR,
        "run_id": run_id,
        "completed": completed,
        "needs_repair": needs_repair,
        "awaiting_muse": awaiting,
        "failed": failed,
        "warnings": all_warnings,
        "batches": len(batch_dirs),
    }
    (run_dir / "run-summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return summary


# Backwards-compatible name for the old single-call flow: preparing and
# applying are now separate steps, so this alias only prepares.
def extract(
    db: str,
    workspace: Path | str,
    batch_size: int = 5,
    force: bool = False,
    **_ignored: Any,
) -> dict[str, Any]:
    return prepare_extraction(db, workspace, batch_size=batch_size, force=force)
