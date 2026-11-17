# Repository instructions

This repository implements Phase 1 of a universal job-to-resume matcher.

- The canonical SQLite database is 'data/work/jobmatcher.db'. Never query or create databases directly under 'data/'.
- Keep eligibility and score arithmetic deterministic.
- Do not introduce model calls into Phase 1. There are no model API calls
  anywhere in this codebase, and no external agent CLIs: the extractor
  is Muse, working in the loop. Code prepares a prompt bundle
  (`jobmatch prepare-jobs` / `prepare-resume`), Muse writes
  `extraction.json` into it, and code validates (`jobmatch apply-jobs` /
  `ingest-resume --extraction ...`) and commits it. Never reintroduce
  subprocess adapters (Antigravity / Claude / Codex / Copilot) or API keys.
- Never infer missing candidate skills, citizenship, work rights, or experience.
- Preserve provenance and evidence. Every extraction must pass the
  Pydantic schema check and the exact-substring evidence check; a batch
  with no extraction.json yet is `awaiting_muse`, never a failure, and
  an invalid batch gets `repair-prompt.txt` and status `needs_repair`
  instead of being committed.
- Update schemas, tests, and policy versions when contracts change.
- Run `pytest -q` after modifications.
- Jobs with nothing extractable (no requirements, no degree, no experience minimum) are `INSUFFICIENT_INFORMATION` and unscored, never a vacuous 100.
- `assessment_confidence` scales with the requirement count (full at 8+); fewer than 5 requirements is flagged `thin_evidence` in reports.
- An 'or' list in a job description is ONE requirement with alternatives, never several requirements; `apply-jobs` records same-evidence requirements as warnings in `validation.json`, not errors.
- `scripts/demo.sh` uses candidate-demo, never candidate-001, so running the demo cannot overwrite a real candidate-001 resume bundle.
- Scraping (`src/jobmatcher/scraper.py`, `jobmatch scrape-jobs`) is an
  optional input step: it fetches public JobStreet listings into the
  JSON format `ingest-jobs` accepts. Playwright is an optional extra
  (`.[scrape]`); importing the scraper must not require it. Scraping
  never touches matching, scoring, eligibility, or extraction.
