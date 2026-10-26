#!/usr/bin/env bash
set -euo pipefail
rm -f data/work/jobmatcher.db
mkdir -p data/work data/output
jobmatch init-db --db data/work/jobmatcher.db
jobmatch ingest-jobs --input examples/jobs.json --db data/work/jobmatcher.db
jobmatch ingest-candidate --input examples/candidate.json --db data/work/jobmatcher.db
jobmatch match --candidate-id candidate-001 --db data/work/jobmatcher.db
jobmatch report --candidate-id candidate-001 --db data/work/jobmatcher.db --output data/output/results.json
jobmatch report --candidate-id candidate-001 --db data/work/jobmatcher.db --output data/output/results.csv
