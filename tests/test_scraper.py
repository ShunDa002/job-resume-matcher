"""Scraper: browser-scrape brief, record validation, import, CLI wiring.

The scrape itself runs in Muse's cloud browser (driven by the agent);
these tests cover everything the tool owns: the brief, validation of
the records the browser returns, writing them out, and ingesting them.
No test needs a browser.
"""
import json
from pathlib import Path

import pytest

import jobmatcher.scraper as scraper_mod
from jobmatcher.db import get_jobs, init_db, upsert_job
from jobmatcher.normalize import normalize_job


def _record(**overrides):
    rec = {
        "page": 1, "page_job_index": 1, "total_job_index": 1,
        "title": "AI Engineer", "company": "Acme Pte Ltd",
        "location": "Singapore", "salary": "Not Disclosed",
        "work_type": "Full time",
        "role_classification": "Engineering - Software (Information & Communication Technology)",
        "job_url": "https://sg.jobstreet.com/job/95952409?jobId=95952409&type=standard",
        "description": "Build LLM features with Python.",
    }
    rec.update(overrides)
    return rec


# --- convert_jsonl_to_json ------------------------------------------------

def test_convert_jsonl_to_json(tmp_path):
    src = tmp_path / "jobs.jsonl"
    src.write_text('{"a": 1}\n\n{"a": 2}\n', encoding="utf-8")
    out = scraper_mod.convert_jsonl_to_json(str(src))
    assert out == str(tmp_path / "jobs.json")
    assert json.loads(Path(out).read_text(encoding="utf-8")) == [{"a": 1}, {"a": 2}]


def test_convert_jsonl_to_json_bad_line_names_the_line(tmp_path):
    src = tmp_path / "jobs.jsonl"
    src.write_text('{"a": 1}\nnot json\n', encoding="utf-8")
    try:
        scraper_mod.convert_jsonl_to_json(str(src))
    except ValueError as e:
        assert "line 2" in str(e)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError")


def test_convert_jsonl_to_json_empty_file(tmp_path):
    src = tmp_path / "jobs.jsonl"
    src.write_text("", encoding="utf-8")
    out = scraper_mod.convert_jsonl_to_json(str(src))
    assert json.loads(Path(out).read_text(encoding="utf-8")) == []


# --- build_scrape_brief ---------------------------------------------------

def test_build_scrape_brief_default():
    brief = scraper_mod.build_scrape_brief()
    assert scraper_mod.DEFAULT_URL in brief
    assert "1 page(s)" in brief
    assert "Do not sign in" in brief
    for field in scraper_mod.RECORD_FIELDS:
        assert field in brief
    # Deterministic: same inputs, same brief.
    assert scraper_mod.build_scrape_brief() == brief


def test_build_scrape_brief_custom_url_and_unlimited_pages():
    brief = scraper_mod.build_scrape_brief(
        target_url="https://sg.jobstreet.com/data-analyst-jobs",
        max_pages=0,
    )
    assert "https://sg.jobstreet.com/data-analyst-jobs" in brief
    assert "all pages, until the Next button disappears" in brief


# --- validate_records -----------------------------------------------------

def test_validate_records_accepts_valid_record():
    kept, issues = scraper_mod.validate_records([_record()])
    assert len(kept) == 1 and issues == []


def test_validate_records_rejects_non_list():
    with pytest.raises(ValueError, match="JSON array"):
        scraper_mod.validate_records({"page": 1})


def test_validate_records_drops_bad_records_and_keeps_good_ones():
    records = [
        _record(),
        _record(page_job_index=2, total_job_index=2,
                job_url="https://sg.jobstreet.com/job/95952410"),
        {"not": "a record"},
        _record(page_job_index=3, total_job_index=3, title="  "),
        _record(page_job_index=4, total_job_index=4,
                job_url="https://example.com/job/1"),
        _record(page_job_index=5, total_job_index=5, page=0),
        _record(page_job_index=6, total_job_index=6, description=None,
                job_url="https://sg.jobstreet.com/job/95952411"),
    ]
    kept, issues = scraper_mod.validate_records(records)
    assert [k["page_job_index"] for k in kept] == [1, 2, 6]
    errors = [i for i in issues if i["severity"] == "error"]
    warnings = [i for i in issues if i["severity"] == "warning"]
    assert len(errors) == 4  # non-dict, empty title, bad url, page 0
    assert len(warnings) == 1  # null description on record 6
    assert all(i["index"] in (2, 3, 4, 5) for i in errors)


def test_validate_records_flags_duplicate_job_ids_but_keeps_both():
    records = [_record(), _record(page_job_index=2, total_job_index=2)]
    kept, issues = scraper_mod.validate_records(records)
    assert len(kept) == 2
    assert len(issues) == 1
    assert issues[0]["severity"] == "warning"
    assert "duplicate" in issues[0]["message"]


def test_validate_records_missing_field_is_an_error():
    rec = _record()
    del rec["company"]
    kept, issues = scraper_mod.validate_records([rec])
    assert kept == []
    assert issues[0]["severity"] == "error"
    assert "company" in issues[0]["message"]


# --- import_browser_records -----------------------------------------------

def test_import_browser_records_writes_jsonl_and_json(tmp_path):
    src = tmp_path / "browser.json"
    src.write_text(json.dumps([
        _record(),
        _record(page_job_index=2, total_job_index=2,
                job_url="https://sg.jobstreet.com/job/95952410"),
        _record(page_job_index=3, total_job_index=3, title=""),
    ]), encoding="utf-8")
    out = tmp_path / "jobs.jsonl"
    summary = scraper_mod.import_browser_records(str(src), str(out))
    assert summary["total"] == 3
    assert summary["kept"] == 2
    assert summary["dropped"] == 1
    assert json.loads(Path(summary["json"]).read_text(encoding="utf-8")) == [
        _record(),
        _record(page_job_index=2, total_job_index=2,
                job_url="https://sg.jobstreet.com/job/95952410"),
    ]
    assert Path(summary["jsonl"]).read_text(encoding="utf-8").count("\n") == 2


def test_import_browser_records_rejects_bad_json(tmp_path):
    src = tmp_path / "browser.json"
    src.write_text("{nope", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid JSON"):
        scraper_mod.import_browser_records(str(src), str(tmp_path / "jobs.jsonl"))


def test_import_browser_records_rejects_non_array(tmp_path):
    src = tmp_path / "browser.json"
    src.write_text(json.dumps({"page": 1}), encoding="utf-8")
    with pytest.raises(ValueError, match="JSON array"):
        scraper_mod.import_browser_records(str(src), str(tmp_path / "jobs.jsonl"))


# --- CLI wiring -----------------------------------------------------------

def test_scrape_jobs_command_prints_brief(tmp_path):
    from typer.testing import CliRunner
    from jobmatcher.cli import app

    brief_file = tmp_path / "brief.txt"
    r = CliRunner().invoke(app, ["scrape-jobs", "--max-pages", "2",
                                 "--brief-file", str(brief_file)])
    assert r.exit_code == 0, r.output
    assert "Scrape JobStreet" in r.output
    assert "2 page(s)" in r.output
    assert brief_file.read_text(encoding="utf-8").strip() in r.output


def test_scrape_jobs_import_ingests_and_dedups(tmp_path):
    from typer.testing import CliRunner
    from jobmatcher.cli import app

    src = tmp_path / "browser.json"
    src.write_text(json.dumps([
        _record(),
        _record(page_job_index=2, total_job_index=2),  # same job id
        _record(page_job_index=3, total_job_index=3,
                job_url="https://sg.jobstreet.com/job/95952410"),
    ]), encoding="utf-8")
    out = tmp_path / "jobs.jsonl"
    db = tmp_path / "x.db"
    r = CliRunner().invoke(app, ["scrape-jobs", "--import", str(src),
                                 "--output", str(out),
                                 "--ingest", "--db", str(db)])
    assert r.exit_code == 0, r.output
    assert '"kept": 3' in r.output
    assert "Ingested 3 jobs into" in r.output
    stored = get_jobs(str(db))
    assert {j.job_id for j in stored} == {"jobstreet_sg-95952409",
                                          "jobstreet_sg-95952410"}


def test_scrape_jobs_import_missing_file_exits_1(tmp_path):
    from typer.testing import CliRunner
    from jobmatcher.cli import app

    r = CliRunner().invoke(app, ["scrape-jobs", "--import",
                                 str(tmp_path / "nope.json")])
    assert r.exit_code == 1
    assert "Import failed" in r.output


# --- scrape -> ingest contract --------------------------------------------

def test_scraper_record_ingests(tmp_path):
    record = _record(description=None)  # browser may return a null description
    job = normalize_job(record)
    assert job.job_id == "jobstreet_sg-95952409"
    assert job.source == "jobstreet_sg"
    assert job.description == ""
    assert job.salary.disclosed is False
    assert job.employment_type == "full_time"
    assert job.location_country_code == "SG"

    db = tmp_path / "x.db"
    init_db(db)
    upsert_job(db, job)
    assert len(get_jobs(str(db))) == 1


def test_scraper_record_with_salary_parses(tmp_path):
    record = _record(salary="$5,000 - $7,000 per month",
                     job_url="https://sg.jobstreet.com/job/95952410")
    job = normalize_job(record)
    assert job.salary.disclosed is True
    assert job.salary.minimum == 5000
    assert job.salary.maximum == 7000
    assert job.salary.period == "month"
