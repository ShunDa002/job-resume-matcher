# Universal Job-to-Resume Matcher

A deterministic, auditable system for matching job postings to candidate resumes. The Universal Job Matcher strictly separates probabilistic AI extraction from deterministic business logic: AI agents extract structured facts into schema-validated models, while deterministic Python code applies hard eligibility gates, evidence scoring, and stable ranking.

---

## Architecture Overview

```text
  Raw Jobs (JSON/Text)                  Resume (PDF/DOCX/DOC/TXT/MD)
          │                                           │
          ▼                                           ▼
[Job Extraction (AI Adapter)]              [Local Document Parser]
  (Antigravity / Claude / Codex / Copilot)            │
          │                                           ▼
          ▼                                 Normalized Plain Text
  Job Records (SQLite)                                │
          │                                           ▼
          │                               [Resume Extraction (AI Adapter)]
          │                                           │
          │                                           ▼
          │                                Candidate Profile (SQLite)
          │                                           │
          └───────────────────┬───────────────────────┘
                              ▼
                  [Deterministic Eligibility Gates]
                    - Citizenship requirements
                    - Professional experience years
                    - Seniority level exclusions
                    - Work authorization / sponsorship
                              │
                              ▼
                  [Evidence-Based Scoring]
                    - Skill taxonomy & transferability
                    - Requirement importance weights
                    - Critical gap penalties
                              │
                              ▼
                  [Deterministic Ranking & Reports]
                    - JSON and CSV output
                    - Stable tie-breaking
```

---

## Requirements

- Python 3.11+
- Optional document conversion tools for legacy `.doc` files:
  - `libreoffice` / `soffice` (preferred)
  - `antiword` (fallback)
- Optional OCR tool for image-only PDFs (e.g. `tesseract` / OCR script)

---

## Installation

```bash
# 1. Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate

# 2. Install package and dependencies in editable mode
pip install -e '.[dev]'

# 3. Generate candidate JSON schema
python scripts/generate_schema.py
```

---

## Quick Demo

Run the end-to-end demo script:

```bash
bash scripts/demo.sh
```

Or execute the steps manually with the `jobmatch` CLI:

```bash
# Initialize SQLite database
jobmatch init-db --db data/work/jobmatcher.db

# Ingest normalized jobs and candidate profile
jobmatch ingest-jobs --input data/input/jobs_1.json --db data/work/jobmatcher.db
jobmatch ingest-candidate --input examples/candidate.json --db data/work/jobmatcher.db

# Run deterministic matching
jobmatch match --candidate-id candidate-001 --db data/work/jobmatcher.db

# Generate reports (JSON and CSV)
jobmatch report --candidate-id candidate-001 --db data/work/jobmatcher.db --output data/output/results.json
jobmatch report --candidate-id candidate-001 --db data/work/jobmatcher.db --output data/output/results.csv

# Generate summary reports (JSON and CSV)
jobmatch summarize --candidate-id candidate-001 --db data/work/jobmatcher.db --output data/output/match-summary.json
jobmatch summarize --candidate-id candidate-001 --db data/work/jobmatcher.db --output data/output/match-summary.csv
```

---

## Deterministic Matching Engine

The core matching engine deliberately contains **no LLM calls**. It provides a reproducible mathematical and rule-based evaluation pipeline:

- **Input Contracts**: Jobs and candidates are validated against Pydantic models ([src/jobmatcher/models.py](file:///c/Data/ide-sbx-isolation/job-matcher/src/jobmatcher/models.py)) and JSON Schemas ([schemas/](file:///c/Data/ide-sbx-isolation/job-matcher/schemas/)).
- **Hard Eligibility Gates**: Evaluates candidate eligibility prior to scoring ([src/jobmatcher/eligibility.py](file:///c/Data/ide-sbx-isolation/job-matcher/src/jobmatcher/eligibility.py)):
  - Explicit citizenship requirements (`INELIGIBLE_CITIZENSHIP`)
  - Required minimum experience years (`INELIGIBLE_EXPERIENCE`)
  - Seniority exclusions for career levels (`INELIGIBLE_SENIORITY`)
  - Target country work authorization and visa sponsorship status (`INELIGIBLE_WORK_AUTHORIZATION`)
- **Evidence-Based Scoring**: Evaluates requirements against demonstrated evidence ([src/jobmatcher/scoring.py](file:///c/Data/ide-sbx-isolation/job-matcher/src/jobmatcher/scoring.py)):
  - Skill taxonomy aliases and transferability relationships ([config/skill-taxonomy.v1.yaml](file:///c/Data/ide-sbx-isolation/job-matcher/config/skill-taxonomy.v1.yaml))
  - Evidence weight levels: `deployed_professional`, `deployed_project`, `substantial_project`, `coursework`, `stated_only`
  - Scoring policy weights and critical gap penalties ([config/scoring-policy.v1.yaml](file:///c/Data/ide-sbx-isolation/job-matcher/config/scoring-policy.v1.yaml))
- **Determinism**: Results are fully stable across runs. Decimal arithmetic and a deterministic job-ID tie breaker ensure identical ranking every time.

---

## AI Extraction & Universal Adapter Layer

Automated extraction parses unstructured job postings into structured requirements using CLI-based AI assistants:

- **Supported Adapters**: `antigravity` (default), `claude`, `codex`, and `copilot`. Custom binary paths can be specified with `--executable`.
- **Execution & Security Boundary**: Adapters run headless with JSON output, bounded workspaces (`--add-dir`), and disabled slash commands or interactive prompts.
- **Schema Enforcement**: Claude, Codex, and Antigravity enforce schemas natively. Copilot receives schemas within bounded prompts with `-s`, disallows interactive questions, and is validated by identical local Pydantic rules.
- **Deterministic Caching**: Extractions are cached in SQLite keyed by a composite hash of the job content, prompt, schema, and adapter configuration. Use `--force` to bypass the cache.
- **Auditing & Repair**: Each batch writes immutable execution artifacts to `data/output/extraction-audit/`. Malformed outputs trigger a single schema-guided repair attempt.

### Adapter CLI Commands

```bash
# Probe agent availability and flags across adapters
jobmatch probe-agent --adapter antigravity
jobmatch probe-agent --adapter claude
jobmatch probe-agent --adapter codex
jobmatch probe-agent --adapter copilot
jobmatch probe-all-agents

# Extract structured requirements from raw jobs into SQLite
jobmatch extract-jobs --adapter antigravity --db data/work/jobmatcher.db --batch-size 5
jobmatch extract-jobs --adapter claude --db data/work/jobmatcher.db
```

---

## Resume Parsing & Ingestion

Extracts validated candidate profiles from resumes in multiple document formats.

### Security Boundary

- The binary document is parsed **entirely locally**.
- Only normalized plain text, candidate ID, and explicit operator overrides are provided to the AI agent.
- Resume text is treated as **untrusted data**. The agent is strictly prohibited from browsing, executing tools, inferring missing citizenship, or counting coursework as professional employment years.
- All evidence strings in the extracted candidate profile must match exact substrings of the resume text.

### Supported Document Formats

- **PDF**: Text extraction via `pypdf` with whitespace normalization and minimum character checks.
- **DOCX**: Paragraphs and structured tables via `python-docx`.
- **Legacy DOC**: Conversion via headless LibreOffice with `antiword` fallback.
- **Plain Text & Markdown**: UTF-8 ingestion.

Scanned/image-only PDFs with insufficient embedded text are rejected with an actionable OCR-required error.

### 1. Parse Resume Locally (No AI)

Inspect extracted text quality and check whether OCR is required:

```bash
jobmatch parse-resume \
  --resume data/input/resume.pdf \
  --output data/output/parsed-resume.json
```

Output structure:

```json
{
  "source_path": "/path/to/resume.pdf",
  "source_format": "pdf",
  "content_hash": "sha256:...",
  "text": "[Page 1]\nResume text content...",
  "page_count": 2,
  "character_count": 3854,
  "extraction_method": "pypdf",
  "warnings": []
}
```

### 2. Parse, Extract with AI, Validate, and Ingest

Run the end-to-end ingestion pipeline:

```bash
jobmatch ingest-resume \
  --resume data/input/resume.pdf \
  --candidate-id candidate-001 \
  --adapter antigravity \
  --overrides examples/operator-overrides.json \
  --db data/work/jobmatcher.db
```

Other adapters are selected similarly:

```bash
jobmatch ingest-resume --resume resume.docx --candidate-id candidate-001 --adapter claude
jobmatch ingest-resume --resume resume.pdf  --candidate-id candidate-001 --adapter codex
jobmatch ingest-resume --resume resume.docx --candidate-id candidate-001 --adapter copilot
```

### Operator Overrides

Use operator overrides for facts that must not be guessed or inferred from resume text (especially citizenship and work authorization):

```json
{
  "citizenship_country_code": "MY",
  "residence_country_code": "MY",
  "has_target_country_work_rights": false,
  "target_employment_types": ["full_time"]
}
```

### Ingestion Pipeline Sequence

```text
Binary Resume (PDF/DOCX/DOC/TXT/MD)
  │
  ▼
Format-specific local parser
  │
  ▼
Normalized plain text & SHA-256 hash
  │
  ▼
Selected AI adapter invocation (with candidate-profile JSON schema)
  │
  ▼
Local Pydantic schema validation & exact substring evidence check
  │
  ├── Failure ──► One AI repair attempt
  │
  ▼
Apply explicit operator overrides
  │
  ▼
Store validated CandidateProfile in SQLite & write audit logs
```

### Audit Logs

All extraction attempts and validation results are preserved immutably:

```text
data/output/resume-audit/<adapter>/<candidate-id>/
  parsed-resume.json     # Output of local document parser
  resume-text.txt        # Exact text sent to agent
  validation.json        # Schema and substring verification log
  candidate-profile.json # Validated profile (written only on success)
  attempt-1/             # Initial prompt, invocation arguments, stdout, stderr
  attempt-2/             # Repair prompt and response (only if attempt 1 failed)
```

### PDF OCR Workflow

If `parse-resume` indicates insufficient embedded text, create a searchable PDF prior to ingestion:

```bash
# Example using an OCR utility
python scripts/ocr_pdf.py data/input/resume-scanned.pdf --output data/input/resume-searchable.pdf

# Ingest searchable PDF
jobmatch ingest-resume \
  --resume data/input/resume-searchable.pdf \
  --candidate-id candidate-001 \
  --adapter antigravity \
  --overrides examples/operator-overrides.json
```

---

## Readable Match Summary

The detailed `jobmatch report` output is intended for audits and programmatic processing. Use `jobmatch summarize` when you need a compact result containing only:

- `rank`
- `job_id`
- `eligibility`
- `final_match_score`
- `requirements`
- `jobstreet_url`

### JSON summary

```bash
jobmatch summarize \
  --candidate-id candidate-001 \
  --db data/work/jobmatcher.db \
  --output data/output/match-summary.json
```

### CSV summary

```bash
jobmatch summarize \
  --candidate-id candidate-001 \
  --db data/work/jobmatcher.db \
  --output data/output/match-summary.csv
```

The output format is selected from the file extension. A `.csv` path creates CSV; other extensions create formatted JSON.

Example JSON:

```json
[
  {
    "rank": 1,
    "job_id": "jobstreet_sg-95408528",
    "eligibility": "CONDITIONALLY_ELIGIBLE",
    "final_match_score": 93.69,
    "requirements": [
      "Good grasp of Python [required, core, critical]",
      "React or TypeScript (alternatives: react) [required, supporting]",
      "Docker or Kubernetes (alternatives: kubernetes) [required, supporting]"
    ],
    "jobstreet_url": "https://sg.jobstreet.com/job/95408528"
  }
]
```

Hard-ineligible jobs have `null` for `final_match_score`. If a stored job has no requirements or URL, the command writes an empty requirements list or `null` URL rather than inventing data.

## CLI Command Summary

| Command                     | Description                                                               |
| --------------------------- | ------------------------------------------------------------------------- |
| `jobmatch init-db`          | Initialize SQLite tables and indexes                                      |
| `jobmatch ingest-jobs`      | Ingest normalized canonical job JSON into SQLite                          |
| `jobmatch ingest-candidate` | Ingest canonical candidate profile JSON into SQLite                       |
| `jobmatch parse-resume`     | Parse PDF/DOCX/DOC/TXT/MD resume locally to JSON without AI               |
| `jobmatch ingest-resume`    | Parse resume, extract candidate via AI adapter, validate, and store in DB |
| `jobmatch probe-agent`      | Probe availability and flags for a specific AI CLI agent                  |
| `jobmatch probe-all-agents` | Check availability across all configured adapters                         |
| `jobmatch extract-jobs`     | Extract structured requirements from raw jobs via AI adapter              |
| `jobmatch match`            | Run deterministic matching and print ranked results                       |
| `jobmatch report`           | Export detailed match results to JSON or CSV                              |
| `jobmatch summarize`        | Export consolidated match summary to JSON or CSV                          |

---

## Tests

Run the test suite:

```bash
pytest -q
```
