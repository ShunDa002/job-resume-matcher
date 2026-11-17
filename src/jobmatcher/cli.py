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
from .summary_report import build_summary, write_summary
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
    db: str = typer.Option(
        "data/work/jobmatcher.db",
        "--db",
    ),
    adapter: str = typer.Option(
        "antigravity",
        "--adapter",
    ),
    batch_size: int = typer.Option(
        5,
        "--batch-size",
        min=1,
        max=50,
    ),
    workers: int = typer.Option(
        3,
        "--workers",
        min=1,
        max=8,
        help=(
            "Maximum number of concurrent "
            "agent batch invocations"
        ),
    ),
    force: bool = typer.Option(
        False,
        "--force",
    ),
    executable: str | None = typer.Option(
        None,
        "--executable",
    ),
):
    summary = extract(
        db,
        Path.cwd(),
        batch_size=batch_size,
        workers=workers,
        force=force,
        executable=executable,
        adapter_name=adapter,
    )

    typer.echo(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
        )
    )

@app.command("extraction-status")
def extraction_status_cmd(
    adapter: str = typer.Option("antigravity", "--adapter", help="AI agent adapter name"),
    run: str | None = typer.Option(None, "--run", help="Specific run ID to inspect"),
):
    audit_base = Path.cwd() / "data" / "output" / "extraction-audit" / adapter
    if not audit_base.exists():
        typer.echo(f"No extraction audit directory found for adapter '{adapter}'")
        return

    if run:
        run_dir = audit_base / run
        if not run_dir.exists():
            typer.echo(f"Run directory '{run}' not found under {audit_base}")
            return
    else:
        run_dirs = sorted([d for d in audit_base.iterdir() if d.is_dir() and d.name.startswith("run-")], key=lambda d: d.name)
        if not run_dirs:
            typer.echo(f"No run directories found for adapter '{adapter}'")
            return
        run_dir = run_dirs[-1]

    batch_dirs = sorted([d for d in run_dir.iterdir() if d.is_dir() and d.name.startswith("batch-")], key=lambda d: d.name)

    statuses = []
    completed_cnt = 0
    running_cnt = 0
    failed_cnt = 0

    for b in batch_dirs:
        status_file = b / "status.json"
        val_file = b / "validation.json"
        b_name = b.name
        if status_file.exists():
            try:
                st_data = json.loads(status_file.read_text(encoding="utf-8"))
                st = st_data.get("status", "unknown")
                dur = st_data.get("duration_seconds", 0.0)
                jobs_cnt = len(st_data.get("job_ids", []))
                if st == "completed":
                    completed_cnt += 1
                    statuses.append(f"{b_name} completed {jobs_cnt} jobs {dur:.1f}s")
                elif st == "failed":
                    failed_cnt += 1
                    statuses.append(f"{b_name} failed {jobs_cnt} jobs {dur:.1f}s")
                elif st == "running":
                    running_cnt += 1
                    statuses.append(f"{b_name} running {jobs_cnt} jobs {dur:.1f}s")
                else:
                    statuses.append(f"{b_name} {st}")
            except Exception:
                statuses.append(f"{b_name} unreadable status")
        elif val_file.exists():
            try:
                val_data = json.loads(val_file.read_text(encoding="utf-8"))
                if val_data.get("valid"):
                    completed_cnt += 1
                    statuses.append(f"{b_name} completed {val_data.get('duration_seconds', 0.0):.1f}s")
                else:
                    failed_cnt += 1
                    statuses.append(f"{b_name} failed")
            except Exception:
                statuses.append(f"{b_name} validation recorded")
        else:
            statuses.append(f"{b_name} pending")

    total = len(batch_dirs)
    typer.echo(f"Run: {run_dir.name}")
    typer.echo(f"Adapter: {adapter}\n")
    typer.echo(f"Completed: {completed_cnt}/{total}")
    typer.echo(f"Running: {running_cnt}")
    typer.echo(f"Failed: {failed_cnt}")
    typer.echo(f"Pending: {total - completed_cnt - running_cnt - failed_cnt}\n")
    for s in statuses:
        typer.echo(s)

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

@app.command("summarize")
def summarize(
    candidate_id: str = typer.Option(..., "--candidate-id", help="Candidate identifier"),
    db: str = typer.Option("data/work/jobmatcher.db", "--db", help="SQLite database path"),
    output: str = typer.Option(..., "--output", help="Summary output path (.json or .csv)"),
):
    from .db import get_jobs

    _, results = run_match(db, candidate_id)
    rows = build_summary(results, get_jobs(db))
    write_summary(rows, output)
    typer.echo(f"Wrote summary {output}")

if __name__ == "__main__":
    app()
