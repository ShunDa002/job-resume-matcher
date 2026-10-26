# Repository instructions

This repository implements Phase 1 of a universal job-to-resume matcher.

- Keep eligibility and score arithmetic deterministic.
- Do not introduce model calls into Phase 1.
- Never infer missing candidate skills, citizenship, work rights, or experience.
- Preserve provenance and evidence.
- Update schemas, tests, and policy versions when contracts change.
- Run `pytest -q` after modifications.
