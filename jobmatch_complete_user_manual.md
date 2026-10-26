# Universal Job-to-Resume Matcher
## Complete User Manual and CLI Workflow Guide

**Implementation scope:** Deterministic matching foundation, universal AI adapter layer, and resume document ingestion  
**Supported AI adapters:** Antigravity CLI, Claude Code, Codex CLI, GitHub Copilot CLI  
**Supported resume formats:** PDF, DOCX, legacy DOC, TXT, Markdown  
**Primary executable:** `jobmatch`

---

# 1. Introduction

The Universal Job-to-Resume Matcher converts job advertisements and a candidate resume into repeatable eligibility decisions, evidence-based match scores, and ranked job recommendations.

The system separates probabilistic AI work from deterministic business rules:

1. **Resume document parsing** extracts text locally from PDF, DOCX, DOC, TXT, or Markdown files.
2. **Resume AI extraction** converts the parsed text into a validated candidate profile.
3. **Job AI extraction** converts job descriptions into normalized requirements and eligibility facts.
4. **Deterministic eligibility rules** filter citizenship, work-authorization, seniority, and experience conflicts.
5. **Deterministic scoring** compares candidate evidence with job requirements.
6. **Reporting** produces detailed JSON and concise CSV output.

The selected AI agent does not calculate the final score and does not decide whether a configured eligibility rule should be applied. It extracts structured facts. Python code applies the business rules and arithmetic.

---

# 2. Implemented Components

## 2.1 Deterministic foundation

- JSON ingestion for jobs
- Structured candidate profiles
- Input validation with Pydantic
- HTML cleanup
- URL normalization
- Salary parsing
- Stable job IDs
- SHA-256 content hashes
- SQLite persistence
- Citizenship filtering
- Experience filtering
- Seniority filtering
- Work-authorization handling
- Skill taxonomy and aliases
- Transferable-skill relationships
- Evidence-weighted scoring
- Critical-gap penalties
- Stable ranking and tie-breaking
- JSON reports
- CSV reports

## 2.2 Universal AI adapter layer

- Antigravity CLI adapter
- Claude Code adapter
- Codex CLI adapter
- GitHub Copilot CLI adapter
- Shared adapter contract
- Capability probing
- Non-interactive invocation
- Provider-specific output parsing
- Common JSON Schema validation
- Common Pydantic validation
- Exact source-evidence checks
- One automatic repair attempt
- Provider-specific audit directories
- Content-hash extraction cache

## 2.3 Resume ingestion

- PDF parsing with embedded-text detection
- DOCX paragraph extraction
- DOCX table extraction
- Legacy DOC conversion or extraction
- TXT and Markdown handling
- Local text normalization
- AI-assisted candidate-profile extraction
- Candidate JSON Schema enforcement
- Exact resume-evidence validation
- Operator overrides for citizenship and work rights
- Resume audit artifacts
- Direct candidate insertion into SQLite

---

# 3. Architecture

```text
Job JSON files
    |
    v
Job ingestion and normalization
    |
    v
SQLite jobs table
    |
    v
Selected AI adapter extracts requirements
    |
    v
Validated canonical job records

Resume PDF/DOCX/DOC/TXT/MD
    |
    v
Local resume parser
    |
    v
Normalized plain text
    |
    v
Selected AI adapter extracts candidate facts
    |
    v
Validated candidate-profile JSON
    |
    v
Operator overrides
    |
    v
SQLite candidate table

Canonical jobs + candidate profile
    |
    v
Deterministic eligibility rules
    |
    v
Deterministic evidence matching and scoring
    |
    v
Stable ranking
    |
    v
JSON and CSV reports
```

---

# 4. Current CLI Commands

The complete CLI contains these commands:

```text
init-db
ingest-jobs
ingest-candidate
parse-resume
ingest-resume
probe-agent
probe-all-agents
extract-jobs
match
report
```

Use:

```bash
jobmatch --help
```

For command-specific help:

```bash
jobmatch COMMAND --help
```

If the console script is unavailable, use:

```bash
python -m jobmatcher.cli COMMAND
```

---

# 5. Installation

## 5.1 Requirements

- Python 3.11 or newer
- `pip`
- SQLite through the Python standard library
- At least one supported AI CLI
- Authentication for the selected AI CLI
- LibreOffice or `antiword` only when parsing legacy `.doc` files
- An OCR utility when processing image-only PDF files

## 5.2 Create a virtual environment

### Linux or macOS

```bash
python -m venv .venv
source .venv/bin/activate
```

### Windows PowerShell

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

## 5.3 Install the application

```bash
pip install -e ".[dev]"
```

The resume extension requires these Python packages:

```text
pypdf
python-docx
pydantic
PyYAML
```

## 5.4 Confirm installation

```bash
jobmatch --help
pytest -q
python -m compileall -q src
```

---

# 6. Project Structure

```text
job-matcher/
├── config/
│   ├── agents.v1.yaml
│   ├── eligibility-policy.v1.yaml
│   ├── scoring-policy.v1.yaml
│   └── skill-taxonomy.v1.yaml
├── schemas/
│   ├── candidate-profile.schema.json
│   ├── extraction-result.schema.json
│   ├── match-result.schema.json
│   └── normalized-job.schema.json
├── prompts/
│   ├── extract-requirements.v1.md
│   ├── repair-extraction.v1.md
│   ├── extract-resume.v1.md
│   └── repair-resume.v1.md
├── src/
│   ├── jobmatcher/
│   └── jobmatcher_resume/
├── data/
│   ├── input/
│   ├── work/
│   └── output/
├── examples/
├── scripts/
└── tests/
```

## 6.1 Important paths

- `data/input/`: Input jobs and resumes
- `data/work/jobmatcher.db`: Default SQLite database
- `data/output/`: Reports and audit artifacts
- `config/agents.v1.yaml`: Agent executable and behavior configuration
- `config/eligibility-policy.v1.yaml`: Hard and conditional eligibility rules
- `config/scoring-policy.v1.yaml`: Scoring weights and penalties
- `config/skill-taxonomy.v1.yaml`: Aliases and transferable relationships

---

# 7. Agent Configuration

Typical `config/agents.v1.yaml`:

```yaml
version: agents.v1

adapters:
  antigravity:
    executable: agy
    minimum_version: 1.1.10
    timeout_seconds: 310
    native_schema: true

  claude:
    executable: claude
    minimum_version: 1.0.0
    timeout_seconds: 310
    native_schema: true
    bare: true

  codex:
    executable: codex
    minimum_version: 0.1.0
    timeout_seconds: 310
    native_schema: true
    sandbox: read-only

  copilot:
    executable: copilot
    minimum_version: 0.1.0
    timeout_seconds: 310
    native_schema: false
    silent: true
    no_ask_user: true
    model: null
```

Do not place credentials in this file. Authenticate through each provider's normal CLI login process.

---

# 8. Input Formats

## 8.1 Job JSON

Jobs may be supplied as a JSON array:

```json
[
  {
    "source": "jobstreet_sg",
    "source_job_id": "95408528",
    "source_url": "https://sg.jobstreet.com/job/95408528",
    "title": "AI Developer",
    "company": "Example Company",
    "location_country_code": "SG",
    "location_text": "Singapore",
    "employment_type": "full_time",
    "description": "Complete advertisement text"
  }
]
```

Or as an object containing a `jobs` array:

```json
{
  "jobs": [
    {
      "source": "jobstreet_sg",
      "title": "AI Developer",
      "company": "Example Company",
      "location_country_code": "SG",
      "description": "Complete advertisement text"
    }
  ]
}
```

## 8.2 Candidate JSON

Manual candidate ingestion remains supported:

```json
{
  "schema_version": "candidate-profile.v1",
  "candidate_id": "candidate-001",
  "citizenship_country_code": "MY",
  "residence_country_code": "MY",
  "has_target_country_work_rights": false,
  "target_employment_types": ["full_time"],
  "career_level": "fresh_graduate",
  "professional_experience_years": 0,
  "degree_fields": ["software_engineering"],
  "graduation_date": "2026-09-30",
  "skills": [],
  "responsibilities": [],
  "domains": [],
  "soft_skills": [],
  "metadata": {}
}
```

Resume ingestion generates this structure automatically.

## 8.3 Operator overrides

Create a file such as `data/input/candidate-overrides.json`:

```json
{
  "citizenship_country_code": "MY",
  "residence_country_code": "MY",
  "has_target_country_work_rights": false,
  "target_employment_types": ["full_time"]
}
```

Overrides should be used for facts that must not be guessed from a resume.

---

# 9. Recommended End-to-End Workflow

```text
1. Initialize the database
2. Ingest jobs
3. Parse the resume locally
4. Probe the selected AI agent
5. Ingest the resume through the selected agent
6. Extract job requirements through the selected agent
7. Calculate matches
8. Generate JSON and CSV reports
```

Commands:

```bash
jobmatch init-db --db data/work/jobmatcher.db

jobmatch ingest-jobs \
  --input data/input/jobs.json \
  --db data/work/jobmatcher.db

jobmatch parse-resume \
  --resume data/input/resume.pdf \
  --output data/output/parsed-resume.json

jobmatch probe-agent --adapter antigravity

jobmatch ingest-resume \
  --resume data/input/resume.pdf \
  --candidate-id candidate-001 \
  --adapter antigravity \
  --overrides data/input/candidate-overrides.json \
  --db data/work/jobmatcher.db

jobmatch extract-jobs \
  --adapter antigravity \
  --db data/work/jobmatcher.db \
  --batch-size 5

jobmatch match \
  --candidate-id candidate-001 \
  --db data/work/jobmatcher.db

jobmatch report \
  --candidate-id candidate-001 \
  --db data/work/jobmatcher.db \
  --output data/output/results.json

jobmatch report \
  --candidate-id candidate-001 \
  --db data/work/jobmatcher.db \
  --output data/output/results.csv
```

---

# 10. Command Reference

## 10.1 `jobmatch init-db`

### Purpose

Creates the SQLite storage used for candidates, jobs, matches, and extraction caches.

### Syntax

```bash
jobmatch init-db [--db PATH]
```

### Example

```bash
jobmatch init-db --db data/work/jobmatcher.db
```

### Notes

- Existing compatible tables are preserved.
- The parent directory is created when needed.
- The command does not delete current records.

---

## 10.2 `jobmatch ingest-jobs`

### Purpose

Loads job JSON into SQLite and performs deterministic normalization.

### Syntax

```bash
jobmatch ingest-jobs \
  --input PATH \
  [--db PATH]
```

### Example

```bash
jobmatch ingest-jobs \
  --input data/input/jobs.json \
  --db data/work/jobmatcher.db
```

### Internal processing

For each job, the command:

1. decodes HTML entities,
2. removes unnecessary markup,
3. extracts clean URLs from HTML anchors,
4. removes tracking parameters and fragments,
5. normalizes the source identifier,
6. creates a stable job ID,
7. parses salary text when supplied,
8. calculates a content hash,
9. validates the record,
10. inserts or updates SQLite.

### Stable IDs

When a source job ID is supplied:

```text
<source>-<source-job-id>
```

Example:

```text
jobstreet_sg-95408528
```

---

## 10.3 `jobmatch ingest-candidate`

### Purpose

Loads a candidate profile that already exists in JSON format.

### Syntax

```bash
jobmatch ingest-candidate \
  --input PATH \
  [--db PATH]
```

### Example

```bash
jobmatch ingest-candidate \
  --input data/input/candidate.json \
  --db data/work/jobmatcher.db
```

### When to use

Use this command when:

- candidate JSON is produced by another system,
- a profile has been manually reviewed and edited,
- resume parsing is not needed,
- a test fixture is being loaded.

For PDF, DOCX, or DOC resumes, use `ingest-resume` instead.

---

## 10.4 `jobmatch parse-resume`

### Purpose

Extracts and normalizes resume text locally without calling an AI agent or modifying the candidate database.

### Syntax

```bash
jobmatch parse-resume \
  --resume PATH \
  --output PATH
```

### PDF example

```bash
jobmatch parse-resume \
  --resume data/input/resume.pdf \
  --output data/output/parsed-resume.json
```

### DOCX example

```bash
jobmatch parse-resume \
  --resume data/input/resume.docx \
  --output data/output/parsed-resume.json
```

### Output structure

```json
{
  "source_path": "/project/data/input/resume.pdf",
  "source_format": "pdf",
  "content_hash": "sha256:...",
  "text": "[Page 1]\nResume content...",
  "page_count": 2,
  "character_count": 3854,
  "extraction_method": "pypdf",
  "warnings": []
}
```

### Recommended use

Always run this command before the first AI ingestion of a new resume. Inspect the output for:

- missing columns,
- incorrect reading order,
- missing tables,
- repeated headers,
- encoding problems,
- insufficient PDF text,
- OCR requirements.

### PDF behavior

The PDF parser:

- reads each page locally,
- inserts page markers,
- combines extracted text,
- normalizes whitespace,
- rejects files with insufficient embedded text.

### DOCX behavior

The DOCX parser extracts:

- body paragraphs,
- table rows,
- table cells.

Example normalized table:

```text
[Table 1]
Skill | Experience
Python | Three projects
Docker | Model deployment
```

### Legacy DOC behavior

For `.doc` files, the parser tries:

1. LibreOffice or `soffice` conversion to DOCX,
2. `antiword` as a fallback.

If neither is available, parsing fails with an actionable error.

---

## 10.5 `jobmatch ingest-resume`

### Purpose

Runs the complete resume-to-candidate workflow and stores the validated candidate profile in SQLite.

### Syntax

```bash
jobmatch ingest-resume \
  --resume PATH \
  --candidate-id ID \
  [--adapter NAME] \
  [--db PATH] \
  [--overrides PATH] \
  [--executable PATH]
```

### Options

- `--resume`: PDF, DOCX, DOC, TXT, or Markdown resume.
- `--candidate-id`: Stable identifier for the candidate.
- `--adapter`: `antigravity`, `claude`, `codex`, or `copilot`.
- Default adapter: `antigravity`.
- `--db`: SQLite database path.
- Default: `data/work/jobmatcher.db`.
- `--overrides`: Optional JSON overrides.
- `--executable`: Optional provider executable path.

### Antigravity example

```bash
jobmatch ingest-resume \
  --resume data/input/resume.pdf \
  --candidate-id candidate-001 \
  --adapter antigravity \
  --overrides data/input/candidate-overrides.json \
  --db data/work/jobmatcher.db
```

### Claude example

```bash
jobmatch ingest-resume \
  --resume data/input/resume.docx \
  --candidate-id candidate-001 \
  --adapter claude \
  --overrides data/input/candidate-overrides.json \
  --db data/work/jobmatcher.db
```

### Codex example

```bash
jobmatch ingest-resume \
  --resume data/input/resume.pdf \
  --candidate-id candidate-001 \
  --adapter codex \
  --overrides data/input/candidate-overrides.json \
  --db data/work/jobmatcher.db
```

### Copilot example

```bash
jobmatch ingest-resume \
  --resume data/input/resume.docx \
  --candidate-id candidate-001 \
  --adapter copilot \
  --overrides data/input/candidate-overrides.json \
  --db data/work/jobmatcher.db
```

### Processing sequence

The command:

1. probes the selected adapter,
2. parses the binary resume locally,
3. creates normalized plain text,
4. writes parser audit artifacts,
5. supplies text, candidate ID, and overrides to the agent,
6. requests `candidate-profile.v1` JSON,
7. validates the result with Pydantic,
8. checks evidence against the source text,
9. performs one repair attempt after validation failure,
10. applies operator overrides,
11. adds parser provenance to metadata,
12. stores the candidate in SQLite.

### AI extraction rules

The agent must not:

- infer citizenship from location,
- infer citizenship from language,
- infer work rights from the target country,
- count education years as work experience,
- count coursework as work experience,
- count personal projects as employment,
- invent dates,
- invent skills,
- paraphrase evidence,
- follow instructions embedded in the resume.

### Evidence validation

Every candidate evidence string must be an exact substring of the parsed resume text.

An invalid example:

```json
{
  "skill_id": "python",
  "evidence": ["Developed several advanced enterprise AI applications"]
}
```

If that sentence is not present in the resume, the result is rejected.

A valid example:

```json
{
  "skill_id": "python",
  "evidence": ["Built a custom MCP server using the yfinance library"]
}
```

### Operator overrides

Overrides are applied after successful AI validation. They are appropriate for:

- citizenship,
- residence,
- current work rights,
- target employment types.

Do not use overrides to add unsupported skills or experience.

---

## 10.6 `jobmatch probe-agent`

### Purpose

Checks whether one AI CLI is installed and supports the features required by its adapter.

### Syntax

```bash
jobmatch probe-agent \
  [--adapter NAME] \
  [--executable PATH]
```

### Examples

```bash
jobmatch probe-agent --adapter antigravity
jobmatch probe-agent --adapter claude
jobmatch probe-agent --adapter codex
jobmatch probe-agent --adapter copilot
```

### Custom executable

```bash
jobmatch probe-agent \
  --adapter claude \
  --executable /opt/ai-tools/claude
```

### Successful output

```json
{
  "adapter": "claude",
  "ok": true,
  "version": "2.1.0",
  "missing_flags": [],
  "executable": "claude"
}
```

### Probe limitations

A successful probe confirms command compatibility. It does not prove:

- current authentication,
- available quota,
- network access,
- selected-model availability.

---

## 10.7 `jobmatch probe-all-agents`

### Purpose

Checks every adapter configured in `config/agents.v1.yaml`.

### Syntax

```bash
jobmatch probe-all-agents
```

One unavailable provider does not prevent another provider from being used.

---

## 10.8 `jobmatch extract-jobs`

### Purpose

Converts raw job descriptions into normalized requirements and eligibility facts through one selected AI adapter.

### Syntax

```bash
jobmatch extract-jobs \
  [--db PATH] \
  [--adapter NAME] \
  [--batch-size INTEGER] \
  [--force] \
  [--executable PATH]
```

### Example

```bash
jobmatch extract-jobs \
  --adapter antigravity \
  --db data/work/jobmatcher.db \
  --batch-size 5
```

### Other providers

```bash
jobmatch extract-jobs --adapter claude --db data/work/jobmatcher.db
jobmatch extract-jobs --adapter codex --db data/work/jobmatcher.db
jobmatch extract-jobs --adapter copilot --db data/work/jobmatcher.db
```

### Force re-extraction

```bash
jobmatch extract-jobs \
  --adapter antigravity \
  --db data/work/jobmatcher.db \
  --force
```

### Summary output

```json
{
  "adapter": "antigravity",
  "probe": {
    "ok": true,
    "version": "1.2.4"
  },
  "total": 10000,
  "cached": 9850,
  "completed": 147,
  "failed": [
    "jobstreet_sg-123456",
    "jobstreet_sg-789012"
  ]
}
```

### Batch-size guidance

```text
Very long descriptions: 1-3
Typical descriptions:   5
Short descriptions:     5-10
Precision-first run:    1
```

### Job extraction cache

The cache key incorporates:

- job content hash,
- extraction prompt hash,
- extraction schema hash,
- adapter configuration hash.

A task is rerun when one of these inputs changes or `--force` is used.

### Extracted facts

The agent may extract:

- normalized title,
- normalized company,
- required experience,
- preferred experience,
- career level,
- citizenship restriction,
- sponsorship statement,
- degree fields,
- technical skills,
- responsibilities,
- domains,
- deployment tools,
- soft skills,
- required versus preferred status,
- critical requirements,
- OR alternatives.

---

## 10.9 `jobmatch match`

### Purpose

Applies deterministic eligibility and scoring for one candidate across all stored jobs.

### Syntax

```bash
jobmatch match \
  --candidate-id ID \
  [--db PATH]
```

### Example

```bash
jobmatch match \
  --candidate-id candidate-001 \
  --db data/work/jobmatcher.db
```

### Eligibility statuses

- `ELIGIBLE`
- `CONDITIONALLY_ELIGIBLE`
- `INSUFFICIENT_INFORMATION`
- `INELIGIBLE_WORK_AUTHORIZATION`
- `INELIGIBLE_EXPERIENCE`
- `INELIGIBLE_SENIORITY`
- `INELIGIBLE_CITIZENSHIP`

Hard-ineligible jobs receive no technical score.

### Scoring categories

- Technical skills: 35%
- Responsibility alignment: 20%
- Education: 10%
- Career level: 15%
- Domain alignment: 10%
- Tools and deployment: 5%
- Soft-skill evidence: 5%

### Ranking order

1. Eligibility tier
2. Final score descending
3. Critical-gap count ascending
4. Assessment confidence descending
5. Stable job ID

---

## 10.10 `jobmatch report`

### Purpose

Runs matching and writes a durable JSON or CSV report.

### Syntax

```bash
jobmatch report \
  --candidate-id ID \
  [--db PATH] \
  --output PATH
```

### JSON report

```bash
jobmatch report \
  --candidate-id candidate-001 \
  --db data/work/jobmatcher.db \
  --output data/output/results.json
```

The JSON report contains detailed evidence, gaps, scores, reasons, and policy versions.

### CSV report

```bash
jobmatch report \
  --candidate-id candidate-001 \
  --db data/work/jobmatcher.db \
  --output data/output/results.csv
```

The CSV report is optimized for ranking review in spreadsheet software.

---

# 11. Resume Format Details

## 11.1 PDF

PDF extraction is text-first. A text-based PDF is processed directly.

Image-only or scanned PDFs are rejected when too little embedded text is detected. This prevents the AI from receiving a nearly empty resume and inventing missing content.

### OCR workflow

```bash
python /home/oai/skills/pdfs/scripts/ocr_pdf.py \
  data/input/resume-scanned.pdf \
  --output data/input/resume-searchable.pdf
```

Then verify:

```bash
jobmatch parse-resume \
  --resume data/input/resume-searchable.pdf \
  --output data/output/parsed-resume.json
```

Then ingest:

```bash
jobmatch ingest-resume \
  --resume data/input/resume-searchable.pdf \
  --candidate-id candidate-001 \
  --adapter antigravity \
  --overrides data/input/candidate-overrides.json
```

## 11.2 DOCX

DOCX parsing reads paragraphs and tables. It does not use document styling as evidence of a skill or qualification.

Text embedded only in drawings, unsupported text boxes, or images may not be extracted. Always inspect `parsed-resume.json` before AI ingestion.

## 11.3 Legacy DOC

Install LibreOffice where possible:

```bash
libreoffice --version
```

Or install `antiword`:

```bash
antiword -h
```

The parser prefers LibreOffice conversion because it usually retains more text and table structure.

## 11.4 TXT and Markdown

UTF-8 text is read directly. Invalid byte sequences are replaced rather than crashing the run.

---

# 12. Audit Artifacts

## 12.1 Resume audits

```text
data/output/resume-audit/
└── <adapter>/
    └── <candidate-id>/
        ├── parsed-resume.json
        ├── resume-text.txt
        ├── validation.json
        ├── candidate-profile.json
        ├── attempt-1/
        └── attempt-2/
```

### `parsed-resume.json`

Local parser result and provenance.

### `resume-text.txt`

The exact text supplied to the AI agent.

### `candidate-profile.json`

Final validated profile after overrides.

### `validation.json`

Validation outcome and errors.

### `attempt-1/` and `attempt-2/`

Provider invocation records. Attempt 2 is created only after a failed first result.

## 12.2 Job audits

```text
data/output/extraction-audit/
├── antigravity/
├── claude/
├── codex/
└── copilot/
```

Each batch may contain:

```text
input.json
validation.json
attempt-1/
  prompt.txt
  invocation.json
  stdout.raw
  stderr.log
  envelope.json
  structured.json
  last-message.json
attempt-2/
```

Not every provider creates every provider-specific file.

---

# 13. Privacy and Security

Resume files contain personal data. Recommended controls:

- use pseudonymous candidate IDs,
- avoid sending phone numbers, email addresses, or home addresses when not needed,
- store resumes outside source control,
- restrict database and audit-directory access,
- define retention periods,
- verify the selected provider's data-handling terms,
- use operator overrides rather than asking the AI to infer legally important facts.

The resume binary is parsed locally. The AI adapter receives normalized resume text, candidate ID, and explicit overrides.

Resume content is treated as untrusted input. Instructions embedded in the resume are not supposed to override the extraction prompt.

---

# 14. Troubleshooting

## 14.1 `jobmatch` command not found

```bash
python -m jobmatcher.cli --help
```

If that works, reinstall the package:

```bash
pip install -e ".[dev]"
```

## 14.2 Agent executable not found

Run:

```bash
jobmatch probe-agent --adapter antigravity
```

Supply an absolute path when necessary:

```bash
jobmatch probe-agent \
  --adapter antigravity \
  --executable /opt/tools/agy
```

## 14.3 Agent is installed but extraction fails

Inspect:

```text
stderr.log
stdout.raw
validation.json
```

Possible reasons:

- authentication expired,
- model unavailable,
- quota exhausted,
- timeout,
- unsupported CLI version,
- malformed provider output,
- schema validation failure.

## 14.4 PDF requires OCR

The parser reports insufficient embedded text. OCR the PDF, then run `parse-resume` again before ingestion.

## 14.5 DOCX text is missing

Possible causes:

- content exists only inside images,
- content exists in unsupported drawing text boxes,
- layout reading order differs from document order,
- the file is corrupted.

Open `parsed-resume.json` and compare it with the visible document.

## 14.6 Legacy DOC cannot be parsed

Install LibreOffice or `antiword`. Confirm the executable is available on `PATH`.

## 14.7 Candidate evidence is rejected

The AI paraphrased evidence instead of returning an exact substring. Inspect:

```text
resume-text.txt
validation.json
attempt-1/structured.json
attempt-2/structured.json
```

## 14.8 Candidate citizenship is null

This is expected when citizenship is not explicitly written in the resume. Supply an operator-overrides JSON file.

## 14.9 Professional experience is zero

This is expected for a resume containing projects but no paid professional roles. Personal and academic projects are intentionally excluded from professional experience years.

## 14.10 Too many jobs are conditionally eligible

Likely reasons:

- sponsorship is not stated,
- candidate work rights are false,
- target employment type differs,
- modest experience mismatch,
- incomplete job extraction.

Inspect the detailed JSON report.

## 14.11 Scores seem too high

Check whether:

- job requirements were extracted completely,
- missing categories defaulted positively,
- taxonomy relationships are too generous,
- critical skills were not marked critical,
- candidate evidence levels are overstated.

## 14.12 Scores seem too low

Check:

- skill aliases,
- categories,
- evidence strength,
- OR alternatives,
- critical-gap designations,
- candidate project evidence.

Do not add unsupported facts merely to increase a score.

---

# 15. Updating Data

## 15.1 New jobs only

```bash
jobmatch ingest-jobs \
  --input data/input/jobs-latest.json \
  --db data/work/jobmatcher.db

jobmatch extract-jobs \
  --adapter antigravity \
  --db data/work/jobmatcher.db
```

Unchanged cached jobs are skipped.

## 15.2 Updated resume only

```bash
jobmatch parse-resume \
  --resume data/input/resume-updated.pdf \
  --output data/output/parsed-resume-updated.json

jobmatch ingest-resume \
  --resume data/input/resume-updated.pdf \
  --candidate-id candidate-001 \
  --adapter antigravity \
  --overrides data/input/candidate-overrides.json \
  --db data/work/jobmatcher.db

jobmatch match \
  --candidate-id candidate-001 \
  --db data/work/jobmatcher.db
```

Job extraction does not need to rerun when only the candidate changes.

## 15.3 Scoring policy only

After versioning a scoring-policy change:

```bash
jobmatch match \
  --candidate-id candidate-001 \
  --db data/work/jobmatcher.db
```

Then regenerate reports.

## 15.4 Job extraction prompt or schema changed

The changed hash normally invalidates corresponding cache keys. To guarantee re-extraction:

```bash
jobmatch extract-jobs \
  --adapter antigravity \
  --db data/work/jobmatcher.db \
  --force
```

Use `--force` carefully because it consumes model calls for every stored job.

---

# 16. Provider-Specific Guidance

## 16.1 Antigravity CLI

Recommended default when it was selected as the operating agent.

```bash
jobmatch probe-agent --adapter antigravity
```

Use the same adapter for both resume and job extraction when consistent model behavior is desired:

```bash
jobmatch ingest-resume --adapter antigravity ...
jobmatch extract-jobs --adapter antigravity ...
```

## 16.2 Claude Code

Configured for bounded headless extraction. Bare mode reduces environment-specific behavior.

```bash
jobmatch probe-agent --adapter claude
```

## 16.3 Codex CLI

Configured for ephemeral, read-only extraction with a dedicated final structured message.

```bash
jobmatch probe-agent --adapter codex
```

## 16.4 GitHub Copilot CLI

Uses silent output and no-question mode. Local validation remains authoritative.

```bash
jobmatch probe-agent --adapter copilot
```

Because the current implementation does not depend on a native Copilot schema flag, begin with smaller batches.

---

# 17. Reproducibility Checklist

For each production run, record:

- source resume hash,
- parsed resume hash or content hash,
- candidate ID,
- operator overrides,
- job dataset hash,
- selected resume adapter,
- selected job adapter,
- CLI versions,
- configured models,
- extraction prompt versions,
- JSON Schema versions,
- eligibility policy version,
- scoring policy version,
- taxonomy version,
- batch size,
- use of `--force`,
- failed job IDs,
- report date,
- database backup.

---

# 18. Database Backup

Before a large run:

```bash
cp data/work/jobmatcher.db \
  data/work/jobmatcher-backup.db
```

Windows PowerShell:

```powershell
Copy-Item data/work/jobmatcher.db `
  data/work/jobmatcher-backup.db
```

Do not copy the database while another process is actively writing unless using a SQLite-aware backup procedure.

---

# 19. Testing

Run the complete suite:

```bash
pytest -q
```

Compile source files:

```bash
python -m compileall -q src
```

Check CLI registration:

```bash
jobmatch --help
jobmatch parse-resume --help
jobmatch ingest-resume --help
jobmatch extract-jobs --help
```

The test suite should include fake provider executables so adapter behavior can be validated without credentials or live model calls.

---

# 20. Complete Daily Procedure

```bash
# Activate environment
source .venv/bin/activate

# Verify selected agent
jobmatch probe-agent --adapter antigravity

# Back up the database
cp data/work/jobmatcher.db \
  data/work/jobmatcher-before-run.db

# Ingest latest jobs
jobmatch ingest-jobs \
  --input data/input/jobs-latest.json \
  --db data/work/jobmatcher.db

# Verify resume parsing when the resume changed
jobmatch parse-resume \
  --resume data/input/resume.pdf \
  --output data/output/parsed-resume.json

# Ingest or update candidate
jobmatch ingest-resume \
  --resume data/input/resume.pdf \
  --candidate-id candidate-001 \
  --adapter antigravity \
  --overrides data/input/candidate-overrides.json \
  --db data/work/jobmatcher.db

# Extract only new or changed jobs
jobmatch extract-jobs \
  --adapter antigravity \
  --db data/work/jobmatcher.db \
  --batch-size 5

# Calculate matches
jobmatch match \
  --candidate-id candidate-001 \
  --db data/work/jobmatcher.db

# Generate detailed JSON
jobmatch report \
  --candidate-id candidate-001 \
  --db data/work/jobmatcher.db \
  --output data/output/job-matches.json

# Generate spreadsheet-friendly CSV
jobmatch report \
  --candidate-id candidate-001 \
  --db data/work/jobmatcher.db \
  --output data/output/job-matches.csv
```

---

# 21. Result Interpretation

## Eligible

No configured hard barrier was identified. This does not guarantee sponsorship, an interview, or an offer.

## Conditionally eligible

The candidate may be technically relevant, but an unresolved eligibility issue remains, commonly unknown sponsorship.

## Ineligible citizenship

The advertisement explicitly requires citizenship the candidate does not possess.

## Ineligible experience

The required professional experience crosses the configured threshold for the candidate's career level.

## Ineligible seniority

The role's seniority is excluded for the candidate's current level.

## Ineligible work authorization

The candidate lacks target-country work rights and sponsorship is explicitly unavailable.

## Match score

The score measures alignment with extracted requirements and configured weights. It is not the statistical probability of receiving an interview or offer.

## Assessment confidence

Assessment confidence reflects data completeness and reliability. It is separate from compatibility.

---

# 22. Recommended Decision Process

1. Remove hard-ineligible jobs.
2. Review conditional eligibility reasons.
3. Verify sponsorship directly when unknown.
4. Inspect critical skill gaps.
5. Inspect resume evidence linked to matches.
6. Prioritize eligible jobs with strong, credible evidence.
7. Tailor the resume without inventing experience.
8. Preserve the report, policies, schemas, prompts, and run metadata.

The matcher is a decision-support system. Final application decisions should also consider role timing, location, sponsorship, interests, compensation, and current job availability.

---

# 23. Quick Command Summary

```bash
# Initialize
jobmatch init-db --db data/work/jobmatcher.db

# Load jobs
jobmatch ingest-jobs --input data/input/jobs.json --db data/work/jobmatcher.db

# Load prebuilt candidate JSON
jobmatch ingest-candidate --input data/input/candidate.json --db data/work/jobmatcher.db

# Parse resume locally
jobmatch parse-resume --resume data/input/resume.pdf --output data/output/parsed-resume.json

# Parse, extract, validate, and ingest resume
jobmatch ingest-resume --resume data/input/resume.pdf --candidate-id candidate-001 --adapter antigravity --overrides data/input/candidate-overrides.json --db data/work/jobmatcher.db

# Probe one AI provider
jobmatch probe-agent --adapter antigravity

# Probe all providers
jobmatch probe-all-agents

# Extract job requirements
jobmatch extract-jobs --adapter antigravity --db data/work/jobmatcher.db --batch-size 5

# Match candidate against jobs
jobmatch match --candidate-id candidate-001 --db data/work/jobmatcher.db

# JSON report
jobmatch report --candidate-id candidate-001 --db data/work/jobmatcher.db --output data/output/results.json

# CSV report
jobmatch report --candidate-id candidate-001 --db data/work/jobmatcher.db --output data/output/results.csv
```
