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
- Degree requirements ("degree", "bachelors_degree", a degree field such as "computer_science" in the education category) are matched against candidate.degree_fields, not the skill taxonomy (skill-taxonomy.v2, scoring.py `_match_degree_requirement`). A bare field name outside the education category is a skill requirement, not the degree, and must not be matched via the degree. A masters/PhD-only requirement is reported absent: the profile stores degree fields but no degree level, so the level must not be guessed.
- Eligibility gates (eligibility-policy.v2, eligibility.py): an explicit citizenship requirement mismatching the candidate is INELIGIBLE_CITIZENSHIP; a required experience minimum of 3+ years for a fresh graduate is INELIGIBLE_EXPERIENCE (1-2 years is conditional, not ineligible); a senior/lead/manager/director/head/executive career level is INELIGIBLE_SENIORITY; a job that requires current enrollment is INELIGIBLE_ENROLLMENT when the candidate is not currently enrolled (candidate-profile.v2 `currently_enrolled`, set from the resume or by operator override, never inferred). This enrollment check is what filters internships: "Pursuing a Bachelor's degree" with no graduate alternative is a requirement; "pursuing or recently completed" is not. A "preferred" experience minimum of 3+ years is not a hard gate, but the gap must be stated as an eligibility reason so a high skill score cannot hide it.
- Scoring weights (scoring-policy.v3): skills 0.40 (technical_skills 0.35, tools_deployment 0.05), experience 0.35 (responsibility_alignment 0.20, career_level 0.15), education 0.10, domain 0.10, soft_skills 0.05. The user confirmed 2026-11-19 that these weights stay: the tool's focus is skills + experience, with education/domain/soft_skills kept as the remaining 0.25.
- The skill taxonomy covers the database family (`databases` / `sql` and concrete databases sqlite, mysql, postgresql, mongodb, redis, vector_database incl. the `chroma` alias) and `api` (related to fastapi). A generic "databases"/"sql" requirement is satisfied by any concrete database in the profile.
- An 'or' list in a job description is ONE requirement with alternatives, never several requirements; `apply-jobs` records same-evidence requirements as warnings in `validation.json`, not errors.
- `scripts/demo.sh` uses candidate-demo, never candidate-001, so running the demo cannot overwrite a real candidate-001 resume bundle.
- Scraping (`src/jobmatcher/scraper.py`, `jobmatch scrape-jobs`) is an
  optional input step that runs in Muse's cloud browser: the tool builds
  the scrape brief (`build_scrape_brief`), the browser runs it, and the
  tool validates and imports the returned records
  (`validate_records` / `import_browser_records`) into the JSON format
  `ingest-jobs` accepts. There is no local browser automation — no
  Playwright, no Chromium — because this machine's proxy blocks
  JobStreet. Scraping never touches matching, scoring, eligibility, or
  extraction.
