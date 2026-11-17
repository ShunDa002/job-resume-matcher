#!/usr/bin/env bash
# End-to-end demo of the Muse-native extraction flow.
#
# The extractor is Muse, in the loop. This script runs the code side;
# the two Muse steps are marked below. In real use Muse reads the
# prepared bundles and writes extraction.json itself. Here the example
# files in examples/ stand in for Muse's output, so the demo runs
# unattended.
set -euo pipefail

# Ensure virtual environment binaries are accessible if .venv exists
if [[ -d ".venv/bin" ]]; then
  export PATH=".venv/bin:$PATH"
fi

mkdir -p data/work data/output

# 1. Initialize the database
rm -f data/work/jobmatcher.db
jobmatch init-db --db data/work/jobmatcher.db

# 2. Ingest raw jobs (unextracted: descriptions only)
jobmatch ingest-jobs \
  --input examples/raw-jobs.json \
  --db data/work/jobmatcher.db

# 3. Parse the resume locally (no AI)
jobmatch parse-resume \
  --resume examples/resume.txt \
  --output data/output/parsed-resume.json

# 4. Prepare the resume bundle for Muse
jobmatch prepare-resume \
  --resume examples/resume.txt \
  --candidate-id candidate-demo \
  --overrides examples/operator-overrides.json

# 5. MUSE STEP (resume): Muse reads
#      data/output/muse-extraction/resume/candidate-demo/prompt.txt
#    and writes extraction.json. The example file is that output.
cp examples/muse-resume-extraction.json \
  data/output/muse-extraction/resume/candidate-demo/extraction.json

# 6. Validate Muse's resume extraction and store the candidate
jobmatch ingest-resume \
  --resume examples/resume.txt \
  --candidate-id candidate-demo \
  --extraction data/output/muse-extraction/resume/candidate-demo/extraction.json \
  --overrides examples/operator-overrides.json \
  --db data/work/jobmatcher.db

# 7. Prepare the job bundles for Muse
RUN_ID=$(jobmatch prepare-jobs --db data/work/jobmatcher.db --batch-size 5 \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['run_id'])")
echo "Muse extraction run: $RUN_ID"

# 8. MUSE STEP (jobs): Muse reads
#      data/output/muse-extraction/$RUN_ID/batch-000000/prompt.txt
#    and writes extraction.json. The example file is that output.
cp examples/muse-jobs-extraction.json \
  "data/output/muse-extraction/$RUN_ID/batch-000000/extraction.json"

# 9. Validate Muse's job extraction and commit it
jobmatch apply-jobs --db data/work/jobmatcher.db --run "$RUN_ID"

# 10. Calculate matches (deterministic, no LLM calls)
jobmatch match \
  --candidate-id candidate-demo \
  --db data/work/jobmatcher.db

# 11. Generate JSON and CSV reports
jobmatch report \
  --candidate-id candidate-demo \
  --db data/work/jobmatcher.db \
  --output data/output/results.json

jobmatch report \
  --candidate-id candidate-demo \
  --db data/work/jobmatcher.db \
  --output data/output/results.csv

# 12. Generate readable summary in JSON and CSV
jobmatch summarize \
  --candidate-id candidate-demo \
  --db data/work/jobmatcher.db \
  --output data/output/match-summary.json

jobmatch summarize \
  --candidate-id candidate-demo \
  --db data/work/jobmatcher.db \
  --output data/output/match-summary.csv
