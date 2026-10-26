from pathlib import Path
import shutil, sys

source = Path(__file__).resolve().parents[1]
arg = sys.argv[1] if len(sys.argv) > 1 else "."
target = Path(arg).resolve()

if not (target / 'src/jobmatcher').exists():
    raise SystemExit(f"Target directory {target} does not contain 'src/jobmatcher'.\nUsage: python scripts/integrate_phase3.py [path-to-target-repo-or-.]")

if target != source:
    for rel in ['src/jobmatcher_resume', 'prompts/extract-resume.v1.md', 'prompts/repair-resume.v1.md', 'schemas/candidate-profile.schema.json']:
        src = source / rel
        dst = target / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)

cli = target / 'src/jobmatcher/cli.py'
s = cli.read_text(encoding='utf-8')
if 'parse-resume' not in s:
    commands_code = '''
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
    from .adapters import AntigravityAdapter
    from .config import load_yaml, default_config

    if adapter == "antigravity":
        agent_cfg_path = default_config("agent-antigravity.v1.yaml")
        if not agent_cfg_path.exists() and default_config("agents.v1.yaml").exists():
            cfg = load_yaml(default_config("agents.v1.yaml"))["adapters"]["antigravity"]
        else:
            cfg = load_yaml(agent_cfg_path)
        agent = AntigravityAdapter(cfg, Path.cwd(), executable)
    else:
        raise typer.BadParameter(f"Adapter '{adapter}' is not supported yet (supported: antigravity)")

    probe = agent.probe()
    if not probe.get("ok"):
        raise typer.BadParameter(f"Agent probe failed: {probe}")

    ov = json.loads(Path(overrides).read_text(encoding="utf-8")) if overrides else {}
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
'''
    if "if __name__" in s:
        parts = s.split("if __name__")
        s = parts[0] + commands_code + "\nif __name__" + parts[1]
    else:
        s += "\n" + commands_code
    cli.write_text(s, encoding='utf-8')

py = target / 'pyproject.toml'
if py.exists():
    t = py.read_text(encoding='utf-8')
    for dep in ['"pypdf>=5,<7",', '"python-docx>=1.1,<2",']:
        if dep not in t:
            t = t.replace('dependencies = [', 'dependencies = [\n  ' + dep)
    py.write_text(t, encoding='utf-8')

print('Integrated resume parser and AI extraction commands into', target)
