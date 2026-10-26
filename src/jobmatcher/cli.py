from __future__ import annotations
import json
from pathlib import Path
import typer
from .db import init_db,upsert_candidate,upsert_job
from .models import CandidateProfile
from .normalize import normalize_job
from .report import write_report
from .service import run_match
from .util import sha256_data
from .extraction import extract
app=typer.Typer(no_args_is_help=True)

@app.command("init-db")
def init_database(db:str=typer.Option("data/work/jobmatcher.db")):
    init_db(db); typer.echo(f"Initialized {db}")

@app.command("ingest-jobs")
def ingest_jobs(input:str=typer.Option(...),db:str=typer.Option("data/work/jobmatcher.db")):
    init_db(db); raw=json.loads(Path(input).read_text(encoding="utf-8")); items=raw if isinstance(raw,list) else raw["jobs"]
    for item in items: upsert_job(db,normalize_job(item))
    typer.echo(f"Ingested {len(items)} jobs")

@app.command("ingest-candidate")
def ingest_candidate(input:str=typer.Option(...),db:str=typer.Option("data/work/jobmatcher.db")):
    init_db(db); raw=json.loads(Path(input).read_text(encoding="utf-8")); c=CandidateProfile.model_validate(raw); upsert_candidate(db,c,sha256_data(c.model_dump(mode="json"))); typer.echo(f"Ingested {c.candidate_id}")

@app.command("match")
def match(candidate_id:str=typer.Option(...),db:str=typer.Option("data/work/jobmatcher.db")):
    run_key,results=run_match(db,candidate_id); typer.echo(json.dumps({"run_key":run_key,"jobs":len(results),"results":[{"rank":i+1,"job_id":r.job_id,"eligibility":r.eligibility_status.value,"score":r.scores.final_match_score if r.scores else None} for i,r in enumerate(results)]},indent=2))

@app.command("report")
def report(candidate_id:str=typer.Option(...),db:str=typer.Option("data/work/jobmatcher.db"),output:str=typer.Option(...)):
    _,results=run_match(db,candidate_id); write_report(results,output); typer.echo(f"Wrote {output}")

@app.command("probe-agent")
def probe_agent(
    adapter: str = typer.Option("antigravity", "--adapter", help="AI agent adapter name (antigravity, claude, codex, copilot)"),
    executable: str | None = typer.Option(None, "--executable", help="Custom agent executable path"),
):
    from .adapters import get_adapter
    try:
        a = get_adapter(adapter, Path.cwd(), executable)
    except ValueError as e:
        raise typer.BadParameter(str(e))
    typer.echo(json.dumps(a.probe(), indent=2))

@app.command("probe-all-agents")
def probe_all_agents():
    from .adapters import probe_all_adapters
    typer.echo(json.dumps(probe_all_adapters(Path.cwd()), indent=2))

@app.command("extract-jobs")
def extract_jobs_cmd(
    db: str = typer.Option("data/work/jobmatcher.db", "--db", help="SQLite database path"),
    adapter: str = typer.Option("antigravity", "--adapter", help="AI agent adapter name"),
    batch_size: int = typer.Option(5, "--batch-size", help="Batch size for extraction"),
    force: bool = typer.Option(False, "--force", help="Bypass extraction cache"),
    executable: str | None = typer.Option(None, "--executable", help="Custom agent executable path"),
):
    typer.echo(json.dumps(extract(db, Path.cwd(), batch_size, force, executable, adapter=adapter), indent=2))

@app.command("parse-resume")
def parse_resume(
    resume: str = typer.Option(..., "--resume", help="Path to resume file (PDF, DOCX, DOC, TXT, MD)"),
    output: str = typer.Option(..., "--output", help="Path to write parsed JSON output"),
):
    from jobmatcher_resume import ResumeDocumentParser
    doc = ResumeDocumentParser().parse(resume)
    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(doc.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    typer.echo(f"Wrote {output}")

@app.command("ingest-resume")
def ingest_resume(
    resume: str = typer.Option(..., "--resume", help="Path to resume file (PDF, DOCX, DOC, TXT, MD)"),
    candidate_id: str = typer.Option(..., "--candidate-id", help="Candidate identifier"),
    adapter: str = typer.Option("antigravity", "--adapter", help="AI agent adapter name"),
    db: str = typer.Option("data/work/jobmatcher.db", "--db", help="SQLite database path"),
    overrides: str | None = typer.Option(None, "--overrides", help="Path to operator overrides JSON"),
    executable: str | None = typer.Option(None, "--executable", help="Agent executable override"),
):
    from jobmatcher_resume import extract_candidate_from_resume
    from .adapters import get_adapter

    try:
        agent = get_adapter(adapter, Path.cwd(), executable)
    except ValueError as e:
        raise typer.BadParameter(str(e))

    probe = agent.probe()
    if not probe.get("ok"):
        raise typer.BadParameter(f"Agent probe failed: {probe}")

    res_path = Path(resume)
    if not res_path.exists():
        raise typer.BadParameter(f"Resume file not found: {resume}")

    if overrides:
        ov_path = Path(overrides)
        if not ov_path.exists():
            raise typer.BadParameter(f"Overrides file not found: {overrides}")
        ov = json.loads(ov_path.read_text(encoding="utf-8"))
    else:
        ov = {}
    candidate, _ = extract_candidate_from_resume(
        resume_path=resume,
        candidate_id=candidate_id,
        adapter=agent,
        schema_path=Path("schemas/candidate-profile.schema.json"),
        prompt_path=Path("prompts/extract-resume.v1.md"),
        repair_prompt_path=Path("prompts/repair-resume.v1.md"),
        audit_dir=Path("data/output/resume-audit") / adapter / candidate_id,
        overrides=ov,
    )
    init_db(db)
    upsert_candidate(db, candidate, sha256_data(candidate.model_dump(mode="json")))
    typer.echo(f"Ingested {candidate_id} from {resume}")

if __name__ == "__main__":
    app()
