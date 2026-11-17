from pathlib import Path
from typer.testing import CliRunner
from jobmatcher.cli import app
runner=CliRunner()
def test_end_to_end(tmp_path):
    db=tmp_path/"x.db"; out=tmp_path/"r.json"
    assert runner.invoke(app,["init-db","--db",str(db)]).exit_code==0
    assert runner.invoke(app,["ingest-jobs","--input","examples/jobs.json","--db",str(db)]).exit_code==0
    assert runner.invoke(app,["ingest-candidate","--input","examples/candidate.json","--db",str(db)]).exit_code==0
    r=runner.invoke(app,["report","--candidate-id","candidate-001","--db",str(db),"--output",str(out)])
    assert r.exit_code==0 and out.exists()
    assert "INELIGIBLE_CITIZENSHIP" in out.read_text()
