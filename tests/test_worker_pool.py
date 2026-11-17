import json
from pathlib import Path
from typer.testing import CliRunner

from jobmatcher.cli import app
from jobmatcher.db import init_db, upsert_job, get_jobs
from jobmatcher.extraction import extract
from jobmatcher.normalize import normalize_job
from jobmatcher.worker import (
    make_batches,
    retry_delay,
    is_retryable_error,
    format_progress_message,
    BatchExtractionResult,
)


def test_make_batches_adaptive():
    class DummyJob:
        def __init__(self, jid: str, desc: str):
            self.job_id = jid
            self.description = desc

    # 1. Test batch size split
    items = [(DummyJob(f"j{i}", "short"), f"key_{i}") for i in range(7)]
    batches = list(make_batches(items, maximum_jobs=3, maximum_characters=1000))
    assert len(batches) == 3
    assert len(batches[0]) == 3
    assert len(batches[1]) == 3
    assert len(batches[2]) == 1

    # 2. Test character overflow split
    long_desc = "x" * 600
    items_overflow = [
        (DummyJob("j1", long_desc), "k1"),
        (DummyJob("j2", long_desc), "k2"),
        (DummyJob("j3", "short"), "k3"),
    ]
    batches_overflow = list(make_batches(items_overflow, maximum_jobs=5, maximum_characters=1000))
    # j1 is 600 chars, adding j2 would exceed 1000 chars, so j2 goes to next batch
    assert len(batches_overflow) == 2
    assert len(batches_overflow[0]) == 1
    assert len(batches_overflow[1]) == 2


def test_retry_helpers():
    assert is_retryable_error("HTTP 429 Too Many Requests")
    assert is_retryable_error("Subprocess timeout after 300s")
    assert is_retryable_error("Service Unavailable 503")
    assert not is_retryable_error("ValidationError: missing field")
    assert not is_retryable_error("unknown executable")

    d1 = retry_delay(1, base_seconds=2.0, max_seconds=10.0, jitter_max=0.5)
    assert 2.0 <= d1 <= 2.5
    d2 = retry_delay(2, base_seconds=2.0, max_seconds=10.0, jitter_max=0.5)
    assert 4.0 <= d2 <= 4.5


def test_format_progress_message():
    res = BatchExtractionResult(
        batch_id="batch-000001",
        job_keys=[("j1", "k1"), ("j2", "k2")],
        extracted_jobs=[],
        valid=True,
        errors=[],
        attempts=1,
        duration_seconds=12.34,
    )
    msg = format_progress_message(completed_count=1, total_batches=3, result=res)
    assert "[1/3] batch-000001 completed: 2 jobs, 12.3s, 1 attempt(s)" in msg


def test_parallel_batches_and_audit(tmp_path):
    root = Path.cwd()
    db = tmp_path / "parallel.db"
    init_db(db)
    exe = str(root / "tests/fixtures/fake_agy.py")

    # Ingest 6 jobs
    for i in range(6):
        upsert_job(
            db,
            normalize_job(
                {
                    "source": "x",
                    "source_job_id": str(i + 1),
                    "title": f"Engineer {i + 1}",
                    "company": f"Company {i + 1}",
                    "location_country_code": "SG",
                    "description": f"Role {i + 1} with 4+ years experience in Python.",
                }
            ),
        )

    # Run extraction with batch size 2 and 3 workers
    summary = extract(
        str(db),
        root,
        batch_size=2,
        force=True,
        executable=exe,
        workers=3,
        submission_delay_seconds=0.0,
    )

    assert summary["completed"] == 6
    assert not summary["failed"]
    assert summary["batches"] == 3
    assert summary["workers"] == 3

    # Check that database records were updated
    jobs = get_jobs(db)
    assert len(jobs) == 6
    for job in jobs:
        assert job.minimum_experience_years == 4

    # Check audit files
    run_id = summary["run_id"]
    audit_run_dir = root / "data" / "output" / "extraction-audit" / "antigravity" / run_id
    assert audit_run_dir.exists()
    assert (audit_run_dir / "run-summary.json").exists()

    for b in range(3):
        bdir = audit_run_dir / f"batch-{b:06d}"
        assert bdir.exists()
        assert (bdir / "input.json").exists()
        assert (bdir / "status.json").exists()
        assert (bdir / "validation.json").exists()
        st = json.loads((bdir / "status.json").read_text(encoding="utf-8"))
        assert st["status"] == "completed"


def test_cli_extract_jobs_and_status(tmp_path, monkeypatch):
    runner = CliRunner()
    root = Path.cwd()
    db = tmp_path / "cli.db"
    init_db(db)
    exe = str(root / "tests/fixtures/fake_agy.py")

    upsert_job(
        db,
        normalize_job(
            {
                "source": "cli_test",
                "source_job_id": "100",
                "title": "Lead Architect",
                "company": "Tech Corp",
                "location_country_code": "SG",
                "description": "Tech Corp seeks Lead Architect with 4+ years. Applicants must be Singaporean citizens.",
            }
        ),
    )

    result = runner.invoke(
        app,
        [
            "extract-jobs",
            "--db",
            str(db),
            "--batch-size",
            "1",
            "--workers",
            "2",
            "--executable",
            exe,
        ],
    )
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert parsed["completed"] == 1
    assert parsed["workers"] == 2

    # Test extraction-status command
    status_result = runner.invoke(app, ["extraction-status", "--adapter", "antigravity"])
    assert status_result.exit_code == 0
    assert "Completed:" in status_result.stdout
    assert "Adapter: antigravity" in status_result.stdout


def test_failed_batch_quarantined_without_corrupting_db(tmp_path):
    root = Path.cwd()
    db = tmp_path / "failed_batch.db"
    init_db(db)
    exe = str(root / "tests/fixtures/fake_agy.py")

    # Ingest 2 jobs:
    # Job 1 has valid description for fake_agy.
    # Job 2 triggers a bad evidence failure in fake_agy because it has 'Singaporean citizens' without 'Applicants must be...'.
    upsert_job(
        db,
        normalize_job(
            {
                "source": "t",
                "source_job_id": "good",
                "title": "Valid Engineer",
                "company": "Good Corp",
                "location_country_code": "SG",
                "description": "Requires 4+ years in software engineering.",
            }
        ),
    )
    upsert_job(
        db,
        normalize_job(
            {
                "source": "t",
                "source_job_id": "bad",
                "title": "Invalid Engineer",
                "company": "Bad Corp",
                "location_country_code": "SG",
                "description": "Requires Singaporean citizens only.",
            }
        ),
    )

    # Run with batch size 1, so 1 batch succeeds, 1 batch fails
    summary = extract(
        str(db),
        root,
        batch_size=1,
        force=True,
        executable=exe,
        workers=2,
    )

    assert summary["completed"] == 1
    assert "t-bad" in summary["failed"]
    assert "t-good" not in summary["failed"]

    # Verify DB: good job was updated, bad job was NOT updated
    jobs = {j.job_id: j for j in get_jobs(db)}
    assert jobs["t-good"].minimum_experience_years == 4
    assert jobs["t-bad"].minimum_experience_years is None
