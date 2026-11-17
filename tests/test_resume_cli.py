import json
from pathlib import Path
from typer.testing import CliRunner
from jobmatcher.cli import app
from jobmatcher.db import get_candidate
from tests.test_resume_service import RAW

runner = CliRunner()

def test_parse_resume_cli(tmp_path):
    resume = tmp_path / "resume.txt"
    resume.write_text("Python software developer with Docker experience.")
    output = tmp_path / "parsed.json"
    res = runner.invoke(app, ["parse-resume", "--resume", str(resume), "--output", str(output)])
    assert res.exit_code == 0
    assert f"Wrote {output}" in res.output
    assert output.exists()
    assert "Python software developer" in output.read_text()

def test_prepare_and_ingest_resume_cli(tmp_path, monkeypatch):
    # prepare-resume writes its bundle under ./data/output/muse-extraction,
    # so run it from an isolated cwd.
    monkeypatch.chdir(tmp_path)
    resume = tmp_path / "resume.txt"
    resume.write_text("Python student in software engineering")
    res = runner.invoke(app, [
        "prepare-resume",
        "--resume", str(resume),
        "--candidate-id", "cand-test-01",
    ])
    assert res.exit_code == 0, res.output
    bundle = tmp_path / "data" / "output" / "muse-extraction" / "resume" / "cand-test-01"
    assert (bundle / "prompt.txt").exists()
    assert (bundle / "resume-text.txt").exists()

    # Muse fills in extraction.json.
    raw = json.loads(json.dumps(RAW)); raw["candidate_id"] = "cand-test-01"
    (bundle / "extraction.json").write_text(json.dumps(raw), encoding="utf-8")

    db = tmp_path / "test.db"
    res = runner.invoke(app, [
        "ingest-resume",
        "--resume", str(resume),
        "--candidate-id", "cand-test-01",
        "--extraction", str(bundle / "extraction.json"),
        "--db", str(db),
    ])
    assert res.exit_code == 0, res.output
    assert "Ingested cand-test-01" in res.output
    cand = get_candidate(str(db), "cand-test-01")
    assert cand.candidate_id == "cand-test-01"
    assert cand.skills[0].skill_id == "python"

def test_ingest_resume_cli_bad_extraction_needs_repair(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    resume = tmp_path / "resume.txt"
    resume.write_text("Python student in software engineering")
    bad = json.loads(json.dumps(RAW)); bad["candidate_id"] = "cand-test-02"
    bad["skills"][0]["evidence"] = ["Java"]  # not in the resume text
    ext = tmp_path / "bad.json"; ext.write_text(json.dumps(bad), encoding="utf-8")
    db = tmp_path / "test.db"
    res = runner.invoke(app, [
        "ingest-resume",
        "--resume", str(resume),
        "--candidate-id", "cand-test-02",
        "--extraction", str(ext),
        "--db", str(db),
    ])
    assert res.exit_code != 0
    assert "repair-prompt.txt" in res.output
    bundle = tmp_path / "data" / "output" / "muse-extraction" / "resume" / "cand-test-02"
    assert (bundle / "repair-prompt.txt").exists()
