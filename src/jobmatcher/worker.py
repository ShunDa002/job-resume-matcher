from __future__ import annotations

from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed,
)
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import random
import sqlite3
import time
from time import monotonic
from typing import Any, Generator, Sequence

from pydantic import ValidationError
import typer

from .adapters import create_adapter
from .db import connect
from .extraction_models import ExtractionResult, XJob
from .models import JobRecord, Requirement

# Alias for compatibility with bounded_worker_pool spec
ExtractedJobFacts = XJob


@dataclass
class BatchExtractionResult:
    batch_id: str
    job_keys: list[tuple[str, str]]
    extracted_jobs: list[XJob]
    valid: bool
    errors: list[Any]
    attempts: int
    duration_seconds: float


def is_retryable_error(error_message: Any) -> bool:
    err = str(error_message).lower()
    retryable_keywords = [
        "timeout",
        "429",
        "rate limit",
        "rate_limit",
        "service unavailable",
        "503",
        "network reset",
        "connection reset",
        "terminated",
    ]
    return any(k in err for k in retryable_keywords)


def retry_delay(
    attempt: int,
    base_seconds: float = 2.0,
    max_seconds: float = 60.0,
    jitter_max: float = 1.5,
) -> float:
    base = min(max_seconds, base_seconds * (2 ** (attempt - 1)))
    jitter = random.uniform(0, jitter_max)
    return base + jitter


def ensure_extraction_cache_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS extraction_cache(
            task_key TEXT PRIMARY KEY,
            job_id TEXT,
            job_content_hash TEXT,
            prompt_hash TEXT,
            schema_hash TEXT,
            adapter_config_hash TEXT,
            payload TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cursor = connection.execute("PRAGMA table_info(extraction_cache)")
    existing_cols = {
        row["name"] if isinstance(row, sqlite3.Row) else row[1]
        for row in cursor.fetchall()
    }
    for col in [
        "job_content_hash",
        "prompt_hash",
        "schema_hash",
        "adapter_config_hash",
    ]:
        if col not in existing_cols:
            connection.execute(f"ALTER TABLE extraction_cache ADD COLUMN {col} TEXT")


def apply_extracted_facts(job: JobRecord, fact: XJob) -> None:
    job.title = fact.normalized_title or job.title
    job.company = fact.normalized_company or job.company
    job.minimum_experience_years = fact.minimum_experience_years
    job.experience_requirement_type = fact.experience_requirement_type
    job.career_level = fact.career_level
    job.required_citizenship_country_code = (
        fact.citizenship.country_code
        if fact.citizenship.requirement == "explicit"
        else None
    )
    job.sponsorship = fact.work_authorization.sponsorship
    job.degree_fields = fact.degree_fields
    job.requirements = [
        Requirement.model_validate(r.model_dump())
        for r in fact.requirements
    ]


def render_prompt(prompt_path: Path | str, input_object: dict[str, Any]) -> str:
    template = Path(prompt_path).read_text(encoding="utf-8")
    return template.replace(
        "{{INPUT_JSON}}",
        json.dumps(input_object, indent=2, ensure_ascii=False),
    )


def render_repair_prompt(
    repair_path: Path | str,
    input_object: dict[str, Any],
    errors: Any,
    invalid_output: Any,
) -> str:
    template = Path(repair_path).read_text(encoding="utf-8")
    return (
        template.replace(
            "{{INPUT_JSON}}",
            json.dumps(input_object, indent=2, ensure_ascii=False),
        )
        .replace(
            "{{VALIDATION_ERRORS}}",
            json.dumps(errors or [], indent=2, ensure_ascii=False),
        )
        .replace(
            "{{INVALID_OUTPUT}}",
            json.dumps(invalid_output, indent=2, ensure_ascii=False),
        )
    )


def verify(x: ExtractionResult, inputs: list[dict[str, Any]]) -> list[str]:
    exp = {j["job_id"]: j for j in inputs}
    errs = []
    if sorted(exp) != sorted(j.job_id for j in x.jobs):
        errs.append("job_id_set_mismatch")
    for j in x.jobs:
        d = exp.get(j.job_id, {}).get("description", "")
        if j.citizenship.evidence_text and j.citizenship.evidence_text not in d:
            errs.append(f"{j.job_id}:bad_citizenship_evidence")
        for r in j.requirements:
            if r.original_text not in d:
                errs.append(f"{j.job_id}:{r.requirement_id}:bad_evidence")
    return errs


def validate_agent_result(
    result: Any,
    input_jobs: list[dict[str, Any]],
) -> tuple[ExtractionResult | None, list[Any]]:
    if hasattr(result, "data"):
        raw = result.data
        errors = list(getattr(result, "errors", []))
    elif isinstance(result, tuple) and len(result) == 2:
        raw, errors = result
        errors = list(errors) if errors else []
    else:
        raw = result
        errors = []

    if errors:
        return None, errors
    if not raw:
        return None, ["empty_response"]

    try:
        parsed = ExtractionResult.model_validate(raw)
    except ValidationError as e:
        return None, e.errors(include_url=False)

    verify_errors = verify(parsed, input_jobs)
    if verify_errors:
        return parsed, verify_errors

    return parsed, []


def format_progress_message(
    *,
    completed_count: int,
    total_batches: int,
    result: BatchExtractionResult,
) -> str:
    status = (
        "completed"
        if result.valid
        else "failed"
    )

    return (
        f"[{completed_count}/{total_batches}] "
        f"{result.batch_id} {status}: "
        f"{len(result.job_keys)} jobs, "
        f"{result.duration_seconds:.1f}s, "
        f"{result.attempts} attempt(s)"
    )


def make_batches(
    jobs: Sequence[Any],
    *,
    maximum_jobs: int = 5,
    maximum_characters: int = 55_000,
) -> Generator[list[Any], None, None]:
    batch: list[Any] = []
    characters = 0

    for item in jobs:
        job, _ = item
        size = len(getattr(job, "description", "") or "")

        would_overflow = (
            batch
            and (
                len(batch) >= maximum_jobs
                or (characters + size > maximum_characters and len(batch) >= 1)
            )
        )

        if would_overflow:
            yield batch
            batch = []
            characters = 0

        batch.append(item)
        characters += size

    if batch:
        yield batch


def process_batch(
    *,
    batch_number: int,
    chunk: list[tuple[JobRecord, str]],
    adapter_name: str,
    adapter_config: dict[str, Any],
    workspace: Path,
    executable: str | None,
    schema_path: Path,
    prompt_path: Path,
    repair_path: Path,
    run_id: str | None = None,
) -> BatchExtractionResult:
    batch_id = f"batch-{batch_number:06d}"

    if run_id:
        audit_dir = (
            workspace
            / "data"
            / "output"
            / "extraction-audit"
            / adapter_name
            / run_id
            / batch_id
        )
    else:
        audit_dir = (
            workspace
            / "data"
            / "output"
            / "extraction-audit"
            / adapter_name
            / batch_id
        )

    audit_dir.mkdir(parents=True, exist_ok=True)

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

    input_object = {
        "schema_version": "extraction-input.v1",
        "jobs": input_jobs,
    }

    (audit_dir / "input.json").write_text(
        json.dumps(
            input_object,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    status_path = audit_dir / "status.json"
    try:
        status_path.write_text(
            json.dumps(
                {
                    "batch_id": batch_id,
                    "status": "running",
                    "started_at": datetime.now(timezone.utc).isoformat(),
                    "attempt": 1,
                    "job_ids": [job.job_id for job, _ in chunk],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception:
        pass

    adapter = create_adapter(
        adapter_name,
        adapter_config,
        workspace,
        executable,
    )

    started = monotonic()
    prompt = render_prompt(prompt_path, input_object)

    max_retries = 3
    result: Any = None

    for retry_idx in range(1, max_retries + 1):
        attempt_dir = audit_dir / ("attempt-1" if retry_idx == 1 else f"attempt-1-retry-{retry_idx}")
        raw, invoke_errs = adapter.invoke(
            prompt,
            schema_path,
            attempt_dir,
        )
        result = (raw, invoke_errs)
        if invoke_errs:
            err_str = " ".join(str(e) for e in invoke_errs)
            if retry_idx < max_retries and is_retryable_error(err_str):
                time.sleep(retry_delay(retry_idx))
                continue
        break

    parsed, errors = validate_agent_result(
        result,
        input_jobs,
    )

    attempts = 1

    if errors:
        attempts = 2
        try:
            status_path.write_text(
                json.dumps(
                    {
                        "batch_id": batch_id,
                        "status": "running",
                        "started_at": datetime.now(timezone.utc).isoformat(),
                        "attempt": 2,
                        "job_ids": [job.job_id for job, _ in chunk],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        except Exception:
            pass

        raw_data = result[0] if isinstance(result, tuple) else getattr(result, "data", None)
        repair_prompt = render_repair_prompt(
            repair_path,
            input_object,
            errors,
            raw_data,
        )

        repaired_result: Any = None
        for retry_idx in range(1, max_retries + 1):
            attempt_dir = audit_dir / ("attempt-2" if retry_idx == 1 else f"attempt-2-retry-{retry_idx}")
            repaired_raw, repaired_errs = adapter.invoke(
                repair_prompt,
                schema_path,
                attempt_dir,
            )
            repaired_result = (repaired_raw, repaired_errs)
            if repaired_errs:
                err_str = " ".join(str(e) for e in repaired_errs)
                if retry_idx < max_retries and is_retryable_error(err_str):
                    time.sleep(retry_delay(retry_idx))
                    continue
            break

        parsed, errors = validate_agent_result(
            repaired_result,
            input_jobs,
        )

    duration = monotonic() - started

    (audit_dir / "validation.json").write_text(
        json.dumps(
            {
                "valid": not errors and parsed is not None,
                "errors": errors,
                "duration_seconds": round(duration, 2),
                "attempts": attempts,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    try:
        status_path.write_text(
            json.dumps(
                {
                    "batch_id": batch_id,
                    "status": "completed" if (not errors and parsed is not None) else "failed",
                    "duration_seconds": round(duration, 2),
                    "attempts": attempts,
                    "job_ids": [job.job_id for job, _ in chunk],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception:
        pass

    return BatchExtractionResult(
        batch_id=batch_id,
        job_keys=[
            (job.job_id, task_key)
            for job, task_key in chunk
        ],
        extracted_jobs=(
            parsed.jobs if parsed and not errors else []
        ),
        valid=not errors and parsed is not None,
        errors=errors,
        attempts=attempts,
        duration_seconds=round(duration, 2),
    )


def commit_batch(
    db_path: str,
    result: BatchExtractionResult,
    jobs_by_id: dict[str, JobRecord],
    cache_metadata: dict[str, str],
) -> None:
    facts_by_id = {
        fact.job_id: fact
        for fact in result.extracted_jobs
    }

    connection = connect(db_path)
    ensure_extraction_cache_table(connection)

    connection.isolation_level = None
    try:
        connection.execute("BEGIN IMMEDIATE")

        for job_id, task_key in result.job_keys:
            job = jobs_by_id[job_id]
            fact = facts_by_id[job_id]

            apply_extracted_facts(job, fact)

            connection.execute(
                """
                INSERT INTO jobs(
                    job_id,
                    content_hash,
                    payload
                )
                VALUES (?, ?, ?)
                ON CONFLICT(job_id)
                DO UPDATE SET
                    content_hash = excluded.content_hash,
                    payload = excluded.payload,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    job.job_id,
                    job.content_hash,
                    job.model_dump_json(),
                ),
            )

            connection.execute(
                """
                INSERT OR REPLACE INTO extraction_cache(
                    task_key,
                    job_id,
                    job_content_hash,
                    prompt_hash,
                    schema_hash,
                    adapter_config_hash,
                    payload
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_key,
                    job.job_id,
                    job.content_hash,
                    cache_metadata.get("prompt_hash"),
                    cache_metadata.get("schema_hash"),
                    cache_metadata.get("adapter_config_hash"),
                    json.dumps(
                        fact.model_dump(mode="json"),
                        ensure_ascii=False,
                    ),
                ),
            )

        connection.execute("COMMIT")

    except Exception:
        connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()


def execute_batches_parallel(
    *,
    pending: list[tuple[JobRecord, str]],
    batch_size: int,
    workers: int,
    process_kwargs: dict[str, Any],
    db_path: str | None = None,
    jobs_by_id: dict[str, JobRecord] | None = None,
    cache_metadata: dict[str, str] | None = None,
    submission_delay_seconds: float = 0.0,
) -> tuple[list[BatchExtractionResult], list[BatchExtractionResult]]:
    batches = list(make_batches(pending, maximum_jobs=batch_size))
    if not batches:
        return [], []

    completed_batches: list[BatchExtractionResult] = []
    failed_batches: list[BatchExtractionResult] = []

    max_workers = max(1, min(workers, len(batches)))

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        for batch_number, chunk in enumerate(batches):
            future = executor.submit(
                process_batch,
                batch_number=batch_number,
                chunk=chunk,
                **process_kwargs,
            )
            futures[future] = (batch_number, chunk)

            if submission_delay_seconds > 0 and workers > 1 and batch_number < len(batches) - 1:
                time.sleep(submission_delay_seconds)

        total = len(futures)

        for completed_count, future in enumerate(
            as_completed(futures),
            start=1,
        ):
            batch_number, chunk = futures[future]
            try:
                result = future.result()
            except Exception as error:
                result = BatchExtractionResult(
                    batch_id=f"batch-{batch_number:06d}",
                    job_keys=[(job.job_id, task_key) for job, task_key in chunk],
                    extracted_jobs=[],
                    valid=False,
                    errors=[
                        {
                            "error": str(error),
                            "type": error.__class__.__name__,
                        }
                    ],
                    attempts=1,
                    duration_seconds=0.0,
                )

            if result.valid:
                if db_path and jobs_by_id is not None and cache_metadata is not None:
                    try:
                        commit_batch(
                            db_path=db_path,
                            result=result,
                            jobs_by_id=jobs_by_id,
                            cache_metadata=cache_metadata,
                        )
                        completed_batches.append(result)
                    except Exception as commit_error:
                        result.valid = False
                        result.errors.append({
                            "error": f"Database commit failed: {commit_error}",
                            "type": commit_error.__class__.__name__,
                        })
                        failed_batches.append(result)
                else:
                    completed_batches.append(result)
            else:
                failed_batches.append(result)

            typer.echo(
                format_progress_message(
                    completed_count=completed_count,
                    total_batches=total,
                    result=result,
                ),
                err=True,
            )

    return completed_batches, failed_batches



def execute_batches_parallel(
    *,
    pending: list[tuple[JobRecord, str]],
    batch_size: int,
    workers: int,
    process_kwargs: dict[str, Any],
    db_path: str | None = None,
    jobs_by_id: dict[str, JobRecord] | None = None,
    cache_metadata: dict[str, str] | None = None,
    submission_delay_seconds: float = 0.0,
) -> tuple[list[BatchExtractionResult], list[BatchExtractionResult]]:
    batches = list(make_batches(pending, maximum_jobs=batch_size))
    if not batches:
        return [], []

    completed_batches: list[BatchExtractionResult] = []
    failed_batches: list[BatchExtractionResult] = []

    max_workers = max(1, min(workers, len(batches)))

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        for batch_number, chunk in enumerate(batches):
            future = executor.submit(
                process_batch,
                batch_number=batch_number,
                chunk=chunk,
                **process_kwargs,
            )
            futures[future] = (batch_number, chunk)

            if submission_delay_seconds > 0 and workers > 1 and batch_number < len(batches) - 1:
                time.sleep(submission_delay_seconds)

        total = len(futures)

        for completed_count, future in enumerate(
            as_completed(futures),
            start=1,
        ):
            batch_number, chunk = futures[future]
            try:
                result = future.result()
            except Exception as error:
                result = BatchExtractionResult(
                    batch_id=f"batch-{batch_number:06d}",
                    job_keys=[(job.job_id, task_key) for job, task_key in chunk],
                    extracted_jobs=[],
                    valid=False,
                    errors=[
                        {
                            "error": str(error),
                            "type": error.__class__.__name__,
                        }
                    ],
                    attempts=1,
                    duration_seconds=0.0,
                )

            if result.valid:
                if db_path and jobs_by_id is not None and cache_metadata is not None:
                    try:
                        commit_batch(
                            db_path=db_path,
                            result=result,
                            jobs_by_id=jobs_by_id,
                            cache_metadata=cache_metadata,
                        )
                        completed_batches.append(result)
                    except Exception as commit_error:
                        result.valid = False
                        result.errors.append({
                            "error": f"Database commit failed: {commit_error}",
                            "type": commit_error.__class__.__name__,
                        })
                        failed_batches.append(result)
                else:
                    completed_batches.append(result)
            else:
                failed_batches.append(result)

            typer.echo(
                format_progress_message(
                    completed_count=completed_count,
                    total_batches=total,
                    result=result,
                ),
                err=True,
            )

    return completed_batches, failed_batches