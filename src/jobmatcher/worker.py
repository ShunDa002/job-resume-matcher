"""Shared extraction helpers: batching, validation, and DB commit.

There is no agent subprocess here, and no model call anywhere in this
codebase. Extraction is done by Muse, in the loop: Muse reads a prompt
bundle prepared by ``extraction.prepare_extraction`` and writes
``extraction.json`` into that bundle. This module only validates what
Muse supplied (Pydantic schema + exact-substring evidence checks) and
commits valid facts to SQLite. The deterministic matching engine is
untouched by extraction and still contains no LLM calls.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generator, Sequence

from pydantic import ValidationError

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
    job.requires_current_enrollment = fact.requires_current_enrollment
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
        if j.enrollment_evidence_text and j.enrollment_evidence_text not in d:
            errs.append(f"{j.job_id}:bad_enrollment_evidence")
        if j.requires_current_enrollment and not j.enrollment_evidence_text:
            errs.append(f"{j.job_id}:missing_enrollment_evidence")
        for r in j.requirements:
            if r.original_text not in d:
                errs.append(f"{j.job_id}:{r.requirement_id}:bad_evidence")
    return errs


def duplicate_evidence_warnings(x: ExtractionResult) -> list[dict[str, Any]]:
    """Non-blocking warnings: two requirements in one job sharing the
    same original_text. Usually an 'or' list split into separate
    requirements instead of one requirement with alternatives (see the
    extraction prompt). Distinct skills joined by 'and' legitimately
    share one evidence sentence, so this warns instead of failing --
    the extractor (Muse) decides whether a merge is right.
    """
    warnings = []
    for j in x.jobs:
        seen: dict[str, list[Any]] = {}
        for r in j.requirements:
            seen.setdefault(" ".join(r.original_text.split()), []).append(r)
        for text, reqs in seen.items():
            if len(reqs) > 1:
                warnings.append({
                    "job_id": j.job_id,
                    "original_text": text,
                    "requirement_ids": [r.requirement_id for r in reqs],
                    "canonical_values": [r.canonical_value for r in reqs],
                })
    return warnings


def validate_agent_result(
    result: Any,
    input_jobs: list[dict[str, Any]],
) -> tuple[ExtractionResult | None, list[Any]]:
    """Validate Muse-supplied extraction JSON.

    Accepts a raw dict (the parsed ``extraction.json``), or a
    ``(raw, errors)`` tuple for callers that already unpacked it.
    Returns ``(parsed, [])`` on success, otherwise ``(parsed_or_None,
    errors)`` where ``parsed`` is set when the schema parsed but the
    evidence check failed, so the repair prompt can quote it.
    """
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
