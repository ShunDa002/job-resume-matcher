import json
from pathlib import Path
from typer.testing import CliRunner

from jobmatcher.cli import app
from jobmatcher.db import init_db, upsert_job, get_jobs
from jobmatcher.normalize import normalize_job
from jobmatcher.extraction import prepare_extraction, apply_extraction
from jobmatcher.worker import make_batches, BatchExtractionResult
from tests.test_muse_extraction import _extraction


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


def test_prepare_and_apply_batches(tmp_path):
    root = Path.cwd()
    db = tmp_path / "parallel.db"
    init_db(db)

    jobs = []
    for i in range(6):
        job = normalize_job({
            "source": "x", "source_job_id": str(i + 1),
            "title": f"Engineer {i + 1}", "company": f"Company {i + 1}",
            "location_country_code": "SG",
            "description": f"Role {i + 1} with 4+ years experience in Python.",
        })
        jobs.append(job)
        upsert_job(db, job)

    prep = prepare_extraction(str(db), root, batch_size=2, force=True)
    assert len(prep["batches"]) == 3

    # Muse fills in each batch bundle.
    for b in prep["batches"]:
        bundle = Path(b["bundle"])
        batch_jobs = [j for j in jobs if j.job_id in b["job_ids"]]
        (bundle / "extraction.json").write_text(
            json.dumps(_extraction(batch_jobs), indent=2), encoding="utf-8")

    summary = apply_extraction(str(db), root, prep["run_id"])
    assert len(summary["completed"]) == 6
    assert not summary["failed"] and not summary["needs_repair"]

    stored = get_jobs(db)
    assert len(stored) == 6
    for job in stored:
        assert job.minimum_experience_years == 4

    audit_run_dir = root / "data" / "output" / "muse-extraction" / prep["run_id"]
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


def test_cli_prepare_apply_and_status(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    db = tmp_path / "cli.db"
    init_db(db)
    job = normalize_job({
        "source": "cli_test", "source_job_id": "100",
        "title": "Lead Architect", "company": "Tech Corp",
        "location_country_code": "SG",
        "description": "Tech Corp seeks Lead Architect with 4+ years. Applicants must be Singaporean citizens.",
    })
    upsert_job(db, job)

    result = runner.invoke(app, ["prepare-jobs", "--db", str(db), "--batch-size", "1"])
    assert result.exit_code == 0, result.output
    prep = json.loads(result.stdout)
    run_id = prep["run_id"]
    bundle = Path(prep["batches"][0]["bundle"])
    (bundle / "extraction.json").write_text(
        json.dumps(_extraction([job]), indent=2), encoding="utf-8")

    result = runner.invoke(app, ["apply-jobs", "--db", str(db), "--run", run_id])
    assert result.exit_code == 0, result.output
    parsed = json.loads(result.stdout)
    assert parsed["completed"] == [job.job_id]

    status_result = runner.invoke(app, ["extraction-status", "--run", run_id])
    assert status_result.exit_code == 0
    assert "Completed: 1/1" in status_result.stdout
    assert "Extractor: muse" in status_result.stdout


def test_failed_batch_quarantined_without_corrupting_db(tmp_path):
    root = Path.cwd()
    db = tmp_path / "failed_batch.db"
    init_db(db)

    good = normalize_job({
        "source": "t", "source_job_id": "good", "title": "Valid Engineer",
        "company": "Good Corp", "location_country_code": "SG",
        "description": "Requires 4+ years in software engineering.",
    })
    bad = normalize_job({
        "source": "t", "source_job_id": "bad", "title": "Invalid Engineer",
        "company": "Bad Corp", "location_country_code": "SG",
        "description": "Requires Singaporean citizens only.",
    })
    upsert_job(db, good)
    upsert_job(db, bad)

    prep = prepare_extraction(str(db), root, batch_size=1, force=True)
    assert len(prep["batches"]) == 2

    # Muse supplies a good extraction for the good job, and a bad-evidence
    # extraction for the bad job (evidence not a substring of its description).
    for b in prep["batches"]:
        bundle = Path(b["bundle"])
        batch_jobs = [good if "good" in b["job_ids"][0] else bad]
        data = _extraction(batch_jobs)
        if batch_jobs[0] is bad:
            data["jobs"][0]["citizenship"] = {
                "requirement": "explicit", "country_code": "SG",
                "evidence_text": "Applicants must be Singaporean citizens.",
            }
        (bundle / "extraction.json").write_text(json.dumps(data), encoding="utf-8")

    summary = apply_extraction(str(db), root, prep["run_id"])
    assert summary["completed"] == ["t-good"]
    assert len(summary["needs_repair"]) == 1
    assert summary["needs_repair"][0]["batch_id"] in {b["batch_id"] for b in prep["batches"]}

    jobs = {j.job_id: j for j in get_jobs(db)}
    assert jobs["t-good"].minimum_experience_years == 4
    assert jobs["t-bad"].minimum_experience_years is None
