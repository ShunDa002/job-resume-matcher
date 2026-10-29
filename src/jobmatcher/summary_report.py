from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


def _requirement_label(requirement: Any) -> str:
    """Convert a structured requirement into one concise, readable string."""
    original_text = getattr(requirement, "original_text", None)
    canonical_value = getattr(requirement, "canonical_value", None)
    label = original_text or canonical_value or "Unspecified requirement"

    tags: list[str] = []
    necessity = getattr(requirement, "necessity", None)
    importance = getattr(requirement, "importance", None)
    critical = bool(getattr(requirement, "critical", False))

    if necessity is not None:
        tags.append(getattr(necessity, "value", str(necessity)))
    if importance is not None:
        tags.append(getattr(importance, "value", str(importance)))
    if critical:
        tags.append("critical")

    alternatives = list(getattr(requirement, "alternatives", []) or [])
    if alternatives:
        label = f"{label} (alternatives: {', '.join(alternatives)})"

    if tags:
        label = f"{label} [{', '.join(tags)}]"
    return label


def build_summary(results: list[Any], jobs: list[Any]) -> list[dict[str, Any]]:
    """Join ranked match results with canonical job records."""
    jobs_by_id = {job.job_id: job for job in jobs}
    rows: list[dict[str, Any]] = []

    for rank, result in enumerate(results, start=1):
        job = jobs_by_id.get(result.job_id)
        requirements = []
        jobstreet_url = None

        if job is not None:
            requirements = [_requirement_label(req) for req in job.requirements]
            jobstreet_url = job.source_url

        rows.append(
            {
                "rank": rank,
                "job_id": result.job_id,
                "eligibility": result.eligibility_status.value,
                "final_match_score": (
                    result.scores.final_match_score if result.scores else None
                ),
                "requirements": requirements,
                "jobstreet_url": jobstreet_url,
            }
        )

    return rows


def write_summary(rows: list[dict[str, Any]], output: str | Path) -> None:
    """Write summary rows as readable JSON or spreadsheet-friendly CSV."""
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if output_path.suffix.lower() == ".csv":
        fieldnames = [
            "rank",
            "job_id",
            "eligibility",
            "final_match_score",
            "requirements",
            "jobstreet_url",
        ]
        with output_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                csv_row = dict(row)
                csv_row["requirements"] = json.dumps(
                    row["requirements"], ensure_ascii=False
                )
                writer.writerow(csv_row)
        return

    output_path.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
