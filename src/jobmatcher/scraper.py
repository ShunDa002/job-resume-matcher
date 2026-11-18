"""Scrape job listings from JobStreet (Singapore) via Muse's cloud browser.

Architecture
-----------
The scraper used to drive a local Chromium with Playwright. That path is
gone: this machine's egress proxy denies sg.jobstreet.com (HTTP 403), so a
local browser can never load the site here, while Muse's cloud browser
reaches it fine. There is no library or CLI the tool can use to drive the
cloud browser — it is driven by the agent through the browser task — so
this module is the *contract* between the tool and that browser task:

1. :func:`build_scrape_brief` produces the exact task text the cloud
   browser runs: search URL, page count, per-listing instructions, and
   the record schema. The brief is the reproducible scrape definition.
2. The browser returns the records as a JSON array.
3. :func:`import_browser_records` validates those records
   (:func:`validate_records`), writes them as JSONL + JSON in the format
   ``jobmatch ingest-jobs`` accepts, and the CLI can ingest them with
   ``--ingest``.

Nothing in this module touches matching, scoring, eligibility, or
extraction, and it imports no browser automation library at all — the
tool's core works on a plain install with no optional dependencies.

The record shape is the one ``normalize_job`` already ingests: ``page``,
``page_job_index``, ``total_job_index``, ``title``, ``company``,
``location``, ``salary``, ``work_type``, ``role_classification``,
``job_url``, ``description``. ``normalize_job`` derives the source and
job id from ``job_url`` and ignores the page/index bookkeeping fields,
so imported files feed ``ingest-jobs`` directly.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

DEFAULT_URL = (
    "https://sg.jobstreet.com/AI-jobs/full-time?pos=1&source=RECENT"
)

RECORD_FIELDS = (
    "page",
    "page_job_index",
    "total_job_index",
    "title",
    "company",
    "location",
    "salary",
    "work_type",
    "role_classification",
    "job_url",
    "description",
)

# Fields that must be non-empty strings; the rest may be None (the
# listing simply did not state them) or a string.
_REQUIRED_TEXT_FIELDS = ("title", "company", "job_url")
_JOB_URL_RE = re.compile(r"^https://sg\.jobstreet\.com/job/(\d+)")


def build_scrape_brief(
    target_url: str = DEFAULT_URL,
    max_pages: Optional[int] = 1,
) -> str:
    """Build the exact task text the cloud browser runs for a scrape.

    ``max_pages`` of 0 or None means "all pages, until the Next button
    disappears". The brief is deterministic for a given URL and page
    count, so a scrape is reproducible from the brief alone.
    """
    pages = (
        "all pages, until the Next button disappears"
        if not max_pages
        else f"{max_pages} page(s)"
    )
    return (
        "Scrape JobStreet Singapore search results in the cloud browser.\n"
        "\n"
        f"Search URL: {target_url}\n"
        f"Pages to scrape: {pages}\n"
        "\n"
        "For each search-results page, open every job listing card one by "
        "one, wait for the detail pane to load, and record the job. Do not "
        "sign in, do not apply to anything, do not go beyond the requested "
        "pages.\n"
        "\n"
        "For each job record exactly these fields:\n"
        "- page: the search page number (1-based)\n"
        "- page_job_index: the listing's position on its page (1-based)\n"
        "- total_job_index: running count across all pages (1-based)\n"
        "- title: the job title from the detail pane\n"
        "- company: the employer name from the detail pane\n"
        "- location: the location from the detail pane\n"
        '- salary: the salary from the detail pane, or "Not Disclosed" if '
        "none is shown\n"
        '- work_type: e.g. "Full time"\n'
        "- role_classification: the classification from the detail pane\n"
        "- job_url: the listing's full link "
        "(https://sg.jobstreet.com/job/<id>...)\n"
        "- description: the full job description text from the detail pane. "
        "If the detail pane shows a security check or an external "
        "application page instead of a description, record exactly what the "
        "pane shows.\n"
        "\n"
        "If the same job appears twice on a page, record both cards as "
        "separate records.\n"
        "If a listing fails to open, note which one and keep going with the "
        "rest.\n"
        "\n"
        "When done, return the complete list as a JSON array of these "
        "records, with nothing omitted — the full description text for "
        "every job matters."
    )


def _job_id(job_url: Any) -> Optional[str]:
    if not isinstance(job_url, str):
        return None
    m = _JOB_URL_RE.match(job_url.strip())
    return m.group(1) if m else None


def validate_records(records: Any) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    """Validate browser-returned records against the ingest schema.

    Returns ``(kept, issues)``. ``kept`` holds the records that are safe
    to import, in order. ``issues`` holds one entry per problem,
    ``{"index": <position in the input>, "severity": "error"|"warning",
    "message": ...}``. Records with an error are dropped; records with
    only warnings are kept (the matcher dedups by job id on ingest, and
    a missing description normalizes to an empty string).
    """
    if not isinstance(records, list):
        raise ValueError("Scraped records must be a JSON array (a list of jobs).")

    kept: List[Dict[str, Any]] = []
    issues: List[Dict[str, str]] = []
    seen_ids: Dict[str, int] = {}

    for idx, rec in enumerate(records):
        if not isinstance(rec, dict):
            issues.append({"index": idx, "severity": "error",
                           "message": "record is not an object; dropped"})
            continue

        missing = [f for f in RECORD_FIELDS if f not in rec]
        if missing:
            issues.append({"index": idx, "severity": "error",
                           "message": f"missing fields {missing}; dropped"})
            continue

        bad: List[str] = []
        for field in ("page", "page_job_index", "total_job_index"):
            value = rec[field]
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                bad.append(f"{field} must be a positive integer, got {value!r}")
        for field in _REQUIRED_TEXT_FIELDS:
            value = rec[field]
            if not isinstance(value, str) or not value.strip():
                bad.append(f"{field} must be a non-empty string")
        for field in ("location", "salary", "work_type", "role_classification", "description"):
            if rec[field] is not None and not isinstance(rec[field], str):
                bad.append(f"{field} must be a string or null")
        job_id = _job_id(rec["job_url"])
        if job_id is None:
            bad.append(f"job_url is not a JobStreet job link: {rec['job_url']!r}")
        if bad:
            issues.append({"index": idx, "severity": "error",
                           "message": "; ".join(bad) + "; dropped"})
            continue

        if job_id in seen_ids:
            issues.append({"index": idx, "severity": "warning",
                           "message": f"duplicate of record {seen_ids[job_id]} "
                                      f"(job id {job_id}); kept, ingest dedups it"})
        else:
            seen_ids[job_id] = idx
        if rec["description"] is None:
            issues.append({"index": idx, "severity": "warning",
                           "message": "description is null; ingests as empty"})
        kept.append(rec)

    return kept, issues


def convert_jsonl_to_json(jsonl_file: str, json_file: Optional[str] = None) -> str:
    input_path = os.path.abspath(jsonl_file)
    output_path = (
        os.path.abspath(json_file)
        if json_file
        else os.path.splitext(input_path)[0] + ".json"
    )

    records: List[Any] = []
    with open(input_path, "r", encoding="utf-8") as in_f:
        for line_number, line in enumerate(in_f, start=1):
            stripped_line = line.strip()
            if not stripped_line:
                continue
            try:
                records.append(json.loads(stripped_line))
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid JSON in {jsonl_file} at line {line_number}: {exc.msg}"
                ) from exc

    with open(output_path, "w", encoding="utf-8") as out_f:
        json.dump(records, out_f, ensure_ascii=False, indent=2)
        out_f.write("\n")

    logger.info(f"Converted {len(records)} records from {jsonl_file} to {output_path}.")
    return output_path


def write_records(records: List[Dict[str, Any]], output_file: str) -> Tuple[str, str]:
    """Write validated records as JSONL plus the converted JSON.

    Returns ``(jsonl_path, json_path)``.
    """
    output_file = os.path.abspath(os.path.expanduser(output_file))
    output_directory = os.path.dirname(output_file)
    if output_directory:
        os.makedirs(output_directory, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as out_f:
        for job in records:
            out_f.write(json.dumps(job, ensure_ascii=False) + "\n")
    json_path = convert_jsonl_to_json(output_file)
    return output_file, json_path


def import_browser_records(source_file: str, output_file: str) -> Dict[str, Any]:
    """Validate records from a browser-returned JSON file and write them out.

    ``source_file`` holds the JSON array the cloud browser returned.
    Returns a summary dict: total/kept/dropped counts, the issue list,
    and the written ``jsonl``/``json`` paths. Raises ValueError on an
    unreadable file or a non-array payload.
    """
    with open(source_file, "r", encoding="utf-8") as in_f:
        try:
            raw = json.load(in_f)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in {source_file}: {exc.msg}") from exc
    kept, issues = validate_records(raw)
    dropped = sum(1 for i in issues if i["severity"] == "error")
    jsonl_path, json_path = write_records(kept, output_file)
    for issue in issues:
        level = logger.error if issue["severity"] == "error" else logger.warning
        level(f"Record {issue['index']}: {issue['message']}")
    logger.info(f"Imported {len(kept)} of {len(raw)} records "
                f"({dropped} dropped) to {json_path}.")
    return {
        "total": len(raw),
        "kept": len(kept),
        "dropped": dropped,
        "issues": issues,
        "jsonl": jsonl_path,
        "json": json_path,
    }
