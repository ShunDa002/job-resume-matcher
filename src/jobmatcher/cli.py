from __future__ import annotations
import json
from pathlib import Path
import typer
from .db import init_db,upsert_candidate,upsert_job
from .models import CandidateProfile
from .normalize import normalize_job
from .report import write_report
from .scraper import DEFAULT_URL as DEFAULT_SCRAPE_URL
from .service import run_match
from .util import sha256_data
from .extraction import prepare_extraction, apply_extraction, EXTRACTOR
from .summary_report import build_summary, write_summary
app=typer.Typer(no_args_is_help=True)

ROOT = Path(__file__).resolve().parents[2]

def _ingest_job_items(items, db: str) -> int:
    """Store normalized job records; shared by ingest-jobs and scrape-jobs --ingest."""
    init_db(db)
    for item in items:
        upsert_job(db, normalize_job(item))
    return len(items)

def _base() -> Path:
    """Repo root for prompts/schemas: the cwd when run from the repo,
    otherwise the package location (e.g. tests run from a temp dir)."""
    return Path.cwd() if (Path.cwd() / "schemas").exists() else ROOT

@app.command("init-db")
def init_database(db:str=typer.Option("data/work/jobmatcher.db")):
    init_db(db); typer.echo(f"Initialized {db}")

@app.command("ingest-jobs")
def ingest_jobs(input:str=typer.Option(...),db:str=typer.Option("data/work/jobmatcher.db")):
    raw=json.loads(Path(input).read_text(encoding="utf-8")); items=raw if isinstance(raw,list) else raw["jobs"]
    n=_ingest_job_items(items,db)
    typer.echo(f"Ingested {n} jobs")

@app.command("scrape-jobs")
def scrape_jobs(
    url: str = typer.Option(DEFAULT_SCRAPE_URL, "--url", help="JobStreet search URL to scrape"),
    max_pages: int = typer.Option(1, "--max-pages", min=0, help="Pages to scrape; 0 means no limit"),
    output: str = typer.Option("data/input/jobstreet_ai_jobs.jsonl", "--output", help="JSONL output path for --import (a .json copy is written alongside it)"),
    brief_file: str = typer.Option(None, "--brief-file", help="Also write the browser task brief to this file"),
    import_file: str = typer.Option(None, "--import", help="Import records from a JSON file returned by the cloud browser"),
    ingest: bool = typer.Option(False, "--ingest", help="Also ingest the imported jobs into the database (with --import)"),
    db: str = typer.Option("data/work/jobmatcher.db", "--db"),
):
    """Scrape JobStreet listings via Muse's cloud browser.

    Scraping runs in the cloud browser — the local Playwright path was
    removed, because this machine's proxy blocks JobStreet. Without
    --import, this prints the browser task brief: run that brief in the
    cloud browser, save the JSON array it returns, and bring it back
    with --import. With --import, the returned records are validated
    and written as <output> (.jsonl) plus the converted .json, in the
    format `ingest-jobs` accepts; --ingest also stores them in the
    database.
    """
    from .scraper import build_scrape_brief, import_browser_records

    if import_file:
        try:
            summary = import_browser_records(import_file, output)
        except (ValueError, OSError) as e:
            typer.echo(f"Import failed: {e}", err=True)
            raise typer.Exit(code=1)
        typer.echo(json.dumps(summary, indent=2))
        if ingest:
            raw = json.loads(Path(summary["json"]).read_text(encoding="utf-8"))
            n = _ingest_job_items(raw if isinstance(raw, list) else raw["jobs"], db)
            typer.echo(f"Ingested {n} jobs into {db}")
        return

    brief = build_scrape_brief(target_url=url, max_pages=max_pages or None)
    if brief_file:
        Path(brief_file).write_text(brief + "\n", encoding="utf-8")
        typer.echo(f"Wrote browser scrape brief to {brief_file}")
    typer.echo(brief)
    typer.echo("\nRun this brief in Muse's cloud browser, save the JSON array it returns, then import it with:")
    typer.echo(f"  jobmatch scrape-jobs --import <records.json> --output {output} [--ingest --db {db}]")

@app.command("ingest-candidate")
def ingest_candidate(input:str=typer.Option(...),db:str=typer.Option("data/work/jobmatcher.db")):
    init_db(db); raw=json.loads(Path(input).read_text(encoding="utf-8")); c=CandidateProfile.model_validate(raw); upsert_candidate(db,c,sha256_data(c.model_dump(mode="json"))); typer.echo(f"Ingested {c.candidate_id}")

@app.command("match")
def match(candidate_id:str=typer.Option(...),db:str=typer.Option("data/work/jobmatcher.db")):
    run_key,results=run_match(db,candidate_id); typer.echo(json.dumps({"run_key":run_key,"jobs":len(results),"results":[{"rank":i+1,"job_id":r.job_id,"eligibility":r.eligibility_status.value,"score":r.scores.final_match_score if r.scores else None} for i,r in enumerate(results)]},indent=2))

@app.command("report")
def report(candidate_id:str=typer.Option(...),db:str=typer.Option("data/work/jobmatcher.db"),output:str=typer.Option(...)):
    _,results=run_match(db,candidate_id); write_report(results,output); typer.echo(f"Wrote {output}")

@app.command("prepare-jobs")
def prepare_jobs_cmd(
    db: str = typer.Option("data/work/jobmatcher.db", "--db"),
    batch_size: int = typer.Option(5, "--batch-size", min=1, max=50),
    force: bool = typer.Option(False, "--force"),
):
    """Prepare Muse extraction bundles for uncached jobs.

    Writes one bundle per batch under data/output/muse-extraction/<run_id>/
    with prompt.txt, input.json, schema.json and an empty extraction.json.
    Muse then fills in extraction.json; run `apply-jobs` to validate it.
    """
    summary = prepare_extraction(db, Path.cwd(), batch_size=batch_size, force=force)
    typer.echo(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["batches"]:
        typer.echo(
            f"Next: Muse fills in extraction.json in each bundle above, "
            f"then run: jobmatch apply-jobs --db {db} --run {summary['run_id']}",
            err=True,
        )

@app.command("apply-jobs")
def apply_jobs_cmd(
    db: str = typer.Option("data/work/jobmatcher.db", "--db"),
    run: str = typer.Option(..., "--run", help="Run ID from prepare-jobs"),
    batch: str | None = typer.Option(None, "--batch", help="Apply one batch only, e.g. batch-000000"),
):
    """Validate Muse-supplied extraction.json files and commit valid batches.

    Batches with no extraction.json yet stay awaiting_muse. Invalid
    batches get repair-prompt.txt and status needs_repair; fix
    extraction.json and re-run this command.
    """
    try:
        summary = apply_extraction(db, Path.cwd(), run_id=run, batch_id=batch)
    except FileNotFoundError as e:
        raise typer.BadParameter(str(e))
    typer.echo(json.dumps(summary, ensure_ascii=False, indent=2))

@app.command("extraction-status")
def extraction_status_cmd(
    run: str | None = typer.Option(None, "--run", help="Specific run ID to inspect"),
):
    audit_base = Path.cwd() / "data" / "output" / "muse-extraction"
    if not audit_base.exists():
        typer.echo("No Muse extraction runs found under data/output/muse-extraction")
        return

    if run:
        run_dir = audit_base / run
        if not run_dir.exists():
            typer.echo(f"Run directory '{run}' not found under {audit_base}")
            return
    else:
        run_dirs = sorted([d for d in audit_base.iterdir() if d.is_dir() and d.name.startswith("run-")], key=lambda d: d.name)
        if not run_dirs:
            typer.echo("No run directories found under data/output/muse-extraction")
            return
        run_dir = run_dirs[-1]

    # Job batches live directly under the run dir; resume bundles live
    # under resume/<candidate-id>/, so report both.
    batch_dirs = sorted([d for d in run_dir.iterdir() if d.is_dir() and d.name.startswith("batch-")], key=lambda d: d.name)
    resume_dirs = sorted((run_dir / "resume").glob("*")) if (run_dir / "resume").exists() else []

    typer.echo(f"Run: {run_dir.name}")
    typer.echo(f"Extractor: {EXTRACTOR}\n")
    counts = {"completed": 0, "awaiting_muse": 0, "needs_repair": 0, "failed": 0}
    lines: list[str] = []
    for b in batch_dirs:
        status_file = b / "status.json"
        st = "unknown"
        if status_file.exists():
            try:
                st = json.loads(status_file.read_text(encoding="utf-8")).get("status", "unknown")
            except Exception:
                st = "unreadable"
        counts[st] = counts.get(st, 0) + 1
        lines.append(f"{b.name} {st}")
    for r in resume_dirs:
        status_file = r / "status.json"
        st = "unknown"
        if status_file.exists():
            try:
                st = json.loads(status_file.read_text(encoding="utf-8")).get("status", "unknown")
            except Exception:
                st = "unreadable"
        counts[st] = counts.get(st, 0) + 1
        lines.append(f"resume/{r.name} {st}")
    total = len(batch_dirs) + len(resume_dirs)
    typer.echo(f"Completed: {counts['completed']}/{total}")
    typer.echo(f"Awaiting Muse: {counts['awaiting_muse']}")
    typer.echo(f"Needs repair: {counts['needs_repair']}")
    typer.echo(f"Failed: {counts['failed']}\n")
    for s in lines:
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

@app.command("prepare-resume")
def prepare_resume(
    resume: str = typer.Option(..., "--resume", help="Path to resume file (PDF, DOCX, DOC, TXT, MD)"),
    candidate_id: str = typer.Option(..., "--candidate-id", help="Candidate identifier"),
    overrides: str | None = typer.Option(None, "--overrides", help="Path to operator overrides JSON"),
):
    """Parse a resume locally and prepare a Muse extraction bundle.

    Writes prompt.txt, resume-text.txt, parsed-resume.json, schema.json
    and an empty extraction.json under
    data/output/muse-extraction/resume/<candidate-id>/.
    Muse fills in extraction.json; run `ingest-resume --extraction ...`
    to validate and store it.
    """
    from jobmatcher_resume import prepare_resume_extraction
    res_path = Path(resume)
    if not res_path.exists():
        raise typer.BadParameter(f"Resume file not found: {resume}")
    ov = {}
    if overrides:
        ov_path = Path(overrides)
        if not ov_path.exists():
            raise typer.BadParameter(f"Overrides file not found: {overrides}")
        ov = json.loads(ov_path.read_text(encoding="utf-8"))
    audit_dir = Path("data/output/muse-extraction") / "resume" / candidate_id
    _doc, _prompt, audit = prepare_resume_extraction(
        resume_path=resume,
        candidate_id=candidate_id,
        schema_path=_base() / "schemas/candidate-profile.schema.json",
        prompt_path=_base() / "prompts/extract-resume.v1.md",
        repair_prompt_path=_base() / "prompts/repair-resume.v1.md",
        audit_dir=audit_dir,
        overrides=ov,
    )
    typer.echo(f"Prepared Muse bundle for {candidate_id} at {audit}")
    typer.echo(
        f"Next: Muse fills in {audit / 'extraction.json'}, then run: "
        f"jobmatch ingest-resume --resume {resume} --candidate-id {candidate_id} "
        f"--extraction {audit / 'extraction.json'}",
        err=True,
    )

@app.command("ingest-resume")
def ingest_resume(
    resume: str = typer.Option(..., "--resume", help="Path to resume file (PDF, DOCX, DOC, TXT, MD)"),
    candidate_id: str = typer.Option(..., "--candidate-id", help="Candidate identifier"),
    extraction: str = typer.Option(..., "--extraction", help="Path to Muse-supplied candidate-profile JSON (extraction.json from prepare-resume)"),
    db: str = typer.Option("data/work/jobmatcher.db", "--db", help="SQLite database path"),
    overrides: str | None = typer.Option(None, "--overrides", help="Path to operator overrides JSON"),
):
    """Validate Muse's resume extraction and store the candidate profile.

    Run `prepare-resume` first if you do not have an extraction.json yet.
    On validation failure this writes repair-prompt.txt into the bundle
    and exits non-zero; have Muse fix extraction.json and re-run.
    """
    from jobmatcher_resume import ingest_resume_extraction
    res_path = Path(resume)
    if not res_path.exists():
        raise typer.BadParameter(f"Resume file not found: {resume}")
    ext_path = Path(extraction)
    if not ext_path.exists():
        raise typer.BadParameter(f"Extraction file not found: {extraction}")
    try:
        raw = json.loads(ext_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise typer.BadParameter(f"Extraction file is not valid JSON: {e}")
    ov = {}
    if overrides:
        ov_path = Path(overrides)
        if not ov_path.exists():
            raise typer.BadParameter(f"Overrides file not found: {overrides}")
        ov = json.loads(ov_path.read_text(encoding="utf-8"))
    audit_dir = Path("data/output/muse-extraction") / "resume" / candidate_id
    try:
        candidate, _ = ingest_resume_extraction(
            resume_path=resume,
            candidate_id=candidate_id,
            extraction=raw,
            schema_path=_base() / "schemas/candidate-profile.schema.json",
            prompt_path=_base() / "prompts/extract-resume.v1.md",
            repair_prompt_path=_base() / "prompts/repair-resume.v1.md",
            audit_dir=audit_dir,
            overrides=ov,
        )
    except RuntimeError as e:
        raise typer.BadParameter(f"{e} See repair-prompt.txt in {audit_dir}")
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
