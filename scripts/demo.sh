#!/usr/bin/env bash
set -euo pipefail

# Ensure virtual environment binaries are accessible if .venv exists
if [[ -d ".venv/bin" ]]; then
  export PATH=".venv/bin:$PATH"
fi

# Ensure workspace and output directories exist
mkdir -p data/work data/output

# 1. Initialize the database
rm -f data/work/jobmatcher.db
jobmatch init-db --db data/work/jobmatcher.db

# 2. Ingest jobs
jobmatch ingest-jobs \
  --input data/input/jobs.json \
  --db data/work/jobmatcher.db

# 3. Parse the resume locally
jobmatch parse-resume \
  --resume data/input/resume.docx \
  --output data/output/parsed-resume.json

# 4. Probe the selected AI agent
jobmatch probe-agent --adapter antigravity

# 5. Ingest the resume through the selected agent
jobmatch ingest-resume \
  --resume data/input/resume.docx \
  --candidate-id candidate-001 \
  --adapter antigravity \
  --overrides data/input/candidate-overrides.json \
  --db data/work/jobmatcher.db

# 6. Extract job requirements through the selected agent
jobmatch extract-jobs \
  --adapter antigravity \
  --db data/work/jobmatcher.db \
  --batch-size 5

# 7. Calculate matches
jobmatch match \
  --candidate-id candidate-001 \
  --db data/work/jobmatcher.db

# 8. Generate JSON and CSV reports
jobmatch report \
  --candidate-id candidate-001 \
  --db data/work/jobmatcher.db \
  --output data/output/results.json

jobmatch report \
  --candidate-id candidate-001 \
  --db data/work/jobmatcher.db \
  --output data/output/results.csv

# 9. Generate readable summary in JSON and CSV
jobmatch summarize \
  --candidate-id candidate-001 \
  --db data/work/jobmatcher.db \
  --output data/output/match-summary.json

jobmatch summarize \
  --candidate-id candidate-001 \
  --db data/work/jobmatcher.db \
  --output data/output/match-summary.csv
