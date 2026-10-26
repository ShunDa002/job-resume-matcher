from pathlib import Path
from typer.testing import CliRunner
from jobmatcher.cli import app
from jobmatcher.db import get_candidate

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

def test_ingest_resume_cli(tmp_path):
    root = Path.cwd()
    fake_exe = str(root / "tests/fixtures/fake_agy.py")
    resume = tmp_path / "resume.txt"
    resume.write_text("Python developer with substantial project experience.")
    db = tmp_path / "test.db"
    res = runner.invoke(app, [
        "ingest-resume",
        "--resume", str(resume),
        "--candidate-id", "cand-test-01",
        "--adapter", "antigravity",
        "--db", str(db),
        "--executable", fake_exe
    ])
    assert res.exit_code == 0
    assert "Ingested cand-test-01" in res.output
    cand = get_candidate(str(db), "cand-test-01")
    assert cand.candidate_id == "cand-test-01"
    assert cand.skills[0].skill_id == "python"

def test_probe_agent_cli():
    root = Path.cwd()
    fake_exe = str(root / "tests/fixtures/fake_agy.py")
    res = runner.invoke(app, ["probe-agent", "--adapter", "antigravity", "--executable", fake_exe])
    assert res.exit_code == 0
    assert '"ok": true' in res.output
    assert '"adapter": "antigravity"' in res.output

def test_probe_all_agents_cli():
    res = runner.invoke(app, ["probe-all-agents"])
    assert res.exit_code == 0
    assert "antigravity" in res.output

