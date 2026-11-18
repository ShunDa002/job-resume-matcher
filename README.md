# Universal Job-to-Resume Matcher

A deterministic, auditable system for matching job postings to candidate resumes. The Universal Job Matcher strictly separates probabilistic AI extraction from deterministic business logic: Muse extracts structured facts into schema-validated models, while deterministic Python code applies hard eligibility gates, evidence scoring, and stable ranking.

There are no external agent CLIs, no API keys, and no model calls in this codebase. Muse is the extractor, working in the loop: the code prepares a prompt bundle, Muse fills in the extraction JSON, and the code validates and commits it.

---

## Architecture Overview

```text
  Raw Jobs (JSON/Text)                  Resume (PDF/DOCX/DOC/TXT/MD)
          │                                           │
          ▼                                           ▼
[Job Extraction (Muse)]                    [Local Document Parser]
  (prompt bundle -> extraction.json)         │
          │                                           ▼
          ▼                                 Normalized Plain Text
  Job Records (SQLite)                                │
          │                                           ▼
          │                               [Resume Extraction (Muse)]
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

## Scraping jobs from JobStreet

Scraping runs in Muse's cloud browser, not in a local browser: this
machine's egress proxy blocks JobStreet, while the cloud browser reaches
it fine. The tool owns the scrape definition and the results; the cloud
browser does the browsing.

```bash
# 1. Print the browser task brief (and save it to a file)
jobmatch scrape-jobs --max-pages 1 --brief-file data/output/scrape-brief.txt

# 2. Run that brief in Muse's cloud browser; it returns the jobs as a
#    JSON array. Save the array to a file, e.g. browser-jobs.json.

# 3. Validate the returned records and write them in the format
#    `ingest-jobs` accepts (JSONL + JSON), ingesting as well:
jobmatch scrape-jobs --import browser-jobs.json \
  --output data/input/jobstreet_ai_jobs.jsonl \
  --ingest --db data/work/jobmatcher.db
```

`scrape-jobs` options: `--url` (default: AI jobs, full-time, recent),
`--max-pages` (default 1; 0 = no limit), `--output`, `--brief-file`,
`--import`, `--ingest`, `--db`.

The import validates every record against the ingest schema: records
missing a title, company, or a JobStreet job link are dropped and
reported; duplicate listings and null descriptions are kept with a
warning (ingest dedups by job id, and a null description normalizes to
an empty string). A detail pane that shows a security check instead of
a description is recorded verbatim, so that job will match poorly —
that is a data problem, not a tool error.

Scraping is an input step only: it never touches matching, scoring,
eligibility, or extraction. There is no browser automation dependency:
no Playwright, no Chromium to install.

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
  - Nothing extractable at all — no requirements, no degree, no experience minimum — (`INSUFFICIENT_INFORMATION`). Such a job is unscored: a score averaged over zero requirements would be a vacuous 100.
- **Evidence-Based Scoring**: Evaluates requirements against demonstrated evidence ([src/jobmatcher/scoring.py](file:///c/Data/ide-sbx-isolation/job-matcher/src/jobmatcher/scoring.py)):
  - Skill taxonomy aliases and transferability relationships ([config/skill-taxonomy.v1.yaml](file:///c/Data/ide-sbx-isolation/job-matcher/config/skill-taxonomy.v1.yaml))
  - Evidence weight levels: `deployed_professional`, `deployed_project`, `substantial_project`, `coursework`, `stated_only`
  - Scoring policy weights and critical gap penalties ([config/scoring-policy.v2.yaml](file:///c/Data/ide-sbx-isolation/job-matcher/config/scoring-policy.v2.yaml))
  - **Evidence-aware confidence**: `assessment_confidence` scales with the number of extracted requirements (full confidence at 8+). A high score over 3 requirements is flagged `thin_evidence` (fewer than 5 requirements) in the report, so it is never mistaken for a well-evidenced match. Reports also list `requirement_count` and the matched vs missing requirements per job.
- **Determinism**: Results are fully stable across runs. Decimal arithmetic and a deterministic job-ID tie breaker ensure identical ranking every time.

---

## Muse Extraction

Extraction parses unstructured job postings into structured requirements. The extractor is Muse, in the loop, in two steps:

1. **Prepare** — `jobmatch prepare-jobs` writes one prompt bundle per batch under `data/output/muse-extraction/<run_id>/batch-000000/`, containing `prompt.txt` (rendered from `prompts/extract-requirements.v2.md`), `input.json`, `schema.json`, and an empty `extraction.json`. Nothing is extracted yet; the batch status is `awaiting_muse`.
2. **Apply** — Muse reads the bundle, extracts facts using only the supplied job text, and writes one JSON object matching `schemas/extraction-result.schema.json` into `extraction.json`. Then `jobmatch apply-jobs --run <run_id>` validates it with Pydantic and exact-substring evidence checks and commits valid batches to SQLite.

- **Security Boundary**: Muse receives only the job text in the bundle. It must not browse, run tools, infer sponsorship, or add facts not in the text. Resume text is likewise treated as untrusted data.
- **Deterministic Caching**: Extractions are cached in SQLite keyed by a composite hash of the job content, prompt, schema, and extractor (`muse`). Use `--force` to bypass the cache.
- **Auditing & Repair**: Each batch writes immutable artifacts to `data/output/muse-extraction/<run_id>/`. A batch with no `extraction.json` yet stays `awaiting_muse` and is not a failure. An invalid extraction gets a `repair-prompt.txt` and status `needs_repair`; Muse fixes `extraction.json` and `apply-jobs` is re-run. A bad batch never corrupts the database.

### Muse Extraction CLI Commands

```bash
# Prepare prompt bundles for uncached jobs
jobmatch prepare-jobs --db data/work/jobmatcher.db --batch-size 5

# (Muse fills in extraction.json in each bundle)

# Validate and commit Muse's extractions
jobmatch apply-jobs --db data/work/jobmatcher.db --run run-20261117T000000Z-abc123

# Check the status of the latest run
jobmatch extraction-status
```

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
# 1. Prepare the Muse bundle (parses the resume locally first)
jobmatch prepare-resume \
  --resume data/input/resume.pdf \
  --candidate-id candidate-001 \
  --overrides examples/operator-overrides.json

# 2. Muse reads data/output/muse-extraction/resume/candidate-001/prompt.txt
#    and writes extraction.json in that bundle.

# 3. Validate Muse's extraction and store the candidate
jobmatch ingest-resume \
  --resume data/input/resume.pdf \
  --candidate-id candidate-001 \
  --extraction data/output/muse-extraction/resume/candidate-001/extraction.json \
  --overrides examples/operator-overrides.json \
  --db data/work/jobmatcher.db
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
Muse extraction (reads prompt bundle, writes extraction.json)
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
data/output/muse-extraction/resume/<candidate-id>/
  parsed-resume.json     # Output of local document parser
  resume-text.txt        # Exact text sent to Muse
  prompt.txt             # Rendered extraction prompt
  schema.json            # Candidate-profile JSON schema
  extraction.json        # Muse-supplied extraction (filled in by Muse)
  repair-prompt.txt      # Written only when validation fails
  validation.json        # Schema and substring verification log
  candidate-profile.json # Validated profile (written only on success)
```

### PDF OCR Workflow

If `parse-resume` indicates insufficient embedded text, create a searchable PDF prior to ingestion:

```bash
# Example using an OCR utility
python scripts/ocr_pdf.py data/input/resume-scanned.pdf --output data/input/resume-searchable.pdf

# Prepare, let Muse fill in extraction.json, then ingest
jobmatch prepare-resume \
  --resume data/input/resume-searchable.pdf \
  --candidate-id candidate-001 \
  --overrides examples/operator-overrides.json
jobmatch ingest-resume \
  --resume data/input/resume-searchable.pdf \
  --candidate-id candidate-001 \
  --extraction data/output/muse-extraction/resume/candidate-001/extraction.json \
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
    "assessment_confidence": 85.0,
    "requirement_count": 4,
    "thin_evidence": true,
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
| `jobmatch prepare-resume`   | Parse resume locally and prepare a Muse extraction bundle                 |
| `jobmatch ingest-resume`    | Validate Muse's resume extraction and store the candidate in DB           |
| `jobmatch prepare-jobs`     | Prepare Muse extraction bundles for uncached jobs                         |
| `jobmatch apply-jobs`       | Validate Muse's job extractions and commit valid batches                  |
| `jobmatch extraction-status`| Show Muse extraction run status (awaiting / needs repair / completed)     |
| `jobmatch match`            | Run deterministic matching and print ranked results                       |
| `jobmatch report`           | Export detailed match results to JSON or CSV                              |
| `jobmatch summarize`        | Export consolidated match summary to JSON or CSV                          |

---

## Tests

Run the test suite:

```bash
pytest -q
```
