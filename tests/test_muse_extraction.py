"""Muse-native extraction: prepare -> Muse fills extraction.json -> apply."""
import json
from pathlib import Path

from jobmatcher.db import init_db, upsert_job, get_jobs
from jobmatcher.normalize import normalize_job
from jobmatcher.extraction import prepare_extraction, apply_extraction


def _job(source_job_id, title, description):
    return normalize_job({
        "source": "x", "source_job_id": source_job_id, "title": title,
        "company": "A", "location_country_code": "SG", "description": description,
    })


def _extraction(jobs):
    out = {"schema_version": "extraction-result.v1", "jobs": []}
    for j in jobs:
        desc = j.description
        ce = "Applicants must be Singaporean citizens." if "Singaporean citizens" in desc else None
        y = 4.0 if "4+ years" in desc else None
        out["jobs"].append({
            "job_id": j.job_id,
            "normalized_title": j.title,
            "normalized_company": j.company,
            "minimum_experience_years": y,
            "experience_requirement_type": "required" if y else "not_stated",
            "career_level": "senior" if "Senior" in j.title else "entry_level",
            "citizenship": {"requirement": "explicit" if ce else "not_stated",
                            "country_code": "SG" if ce else None, "evidence_text": ce},
            "work_authorization": {"sponsorship": "unknown", "evidence_text": None},
            "degree_fields": [], "requirements": [], "warnings": [],
        })
    return out


def test_prepare_apply_round_trip(tmp_path):
    root = Path.cwd()
    db = tmp_path / "x.db"
    init_db(db)
    jobs = [_job("1", "Senior AI Engineer", "Requires 4+ years in AI ML engineering."),
            _job("2", "Engineer", "Applicants must be Singaporean citizens.")]
    for j in jobs:
        upsert_job(db, j)

    prep = prepare_extraction(str(db), root, batch_size=5)
    assert prep["extractor"] == "muse"
    assert prep["total"] == 2 and prep["cached"] == 0
    assert len(prep["batches"]) == 1
    bundle = Path(prep["batches"][0]["bundle"])
    assert (bundle / "prompt.txt").exists()
    assert (bundle / "input.json").exists()
    assert (bundle / "schema.json").exists()

    # Muse fills in extraction.json.
    (bundle / "extraction.json").write_text(
        json.dumps(_extraction(jobs), indent=2), encoding="utf-8")

    result = apply_extraction(str(db), root, prep["run_id"])
    assert result["completed"] == [j.job_id for j in jobs]
    assert not result["needs_repair"] and not result["awaiting_muse"] and not result["failed"]

    stored = {j.job_id: j for j in get_jobs(db)}
    assert stored[jobs[0].job_id].minimum_experience_years == 4
    assert stored[jobs[0].job_id].career_level == "senior"
    assert stored[jobs[1].job_id].required_citizenship_country_code == "SG"

    # Second prepare: everything is cached, no new bundles.
    prep2 = prepare_extraction(str(db), root, batch_size=5)
    assert prep2["cached"] == 2 and prep2["batches"] == []


def test_apply_without_extraction_is_awaiting_not_failed(tmp_path):
    root = Path.cwd()
    db = tmp_path / "x.db"
    init_db(db)
    upsert_job(db, _job("1", "Engineer", "Requires 4+ years in AI ML engineering."))
    prep = prepare_extraction(str(db), root, batch_size=5)
    result = apply_extraction(str(db), root, prep["run_id"])
    assert result["completed"] == []
    assert result["awaiting_muse"] == ["batch-000000"]
    assert not result["needs_repair"] and not result["failed"]
    # The job was not changed by the empty apply.
    assert get_jobs(db)[0].minimum_experience_years is None


def test_bad_evidence_needs_repair_then_succeeds(tmp_path):
    root = Path.cwd()
    db = tmp_path / "x.db"
    init_db(db)
    job = _job("1", "Engineer", "Requires 4+ years in AI ML engineering.")
    upsert_job(db, job)
    prep = prepare_extraction(str(db), root, batch_size=5)
    bundle = Path(prep["batches"][0]["bundle"])

    bad = _extraction([job])
    bad["jobs"][0]["citizenship"] = {
        "requirement": "explicit", "country_code": "SG",
        "evidence_text": "Must be a citizen.",  # not a substring of the description
    }
    (bundle / "extraction.json").write_text(json.dumps(bad), encoding="utf-8")
    result = apply_extraction(str(db), root, prep["run_id"])
    assert result["completed"] == []
    assert len(result["needs_repair"]) == 1
    assert (bundle / "repair-prompt.txt").exists()
    assert get_jobs(db)[0].minimum_experience_years is None  # bad batch quarantined

    # Muse fixes the extraction and re-applies.
    (bundle / "extraction.json").write_text(
        json.dumps(_extraction([job]), indent=2), encoding="utf-8")
    result2 = apply_extraction(str(db), root, prep["run_id"])
    assert result2["completed"] == [job.job_id]
    assert get_jobs(db)[0].minimum_experience_years == 4


def test_duplicate_evidence_warnings():
    from jobmatcher.extraction_models import ExtractionResult
    from jobmatcher.worker import duplicate_evidence_warnings

    raw = {
        "schema_version": "extraction-result.v1",
        "jobs": [{
            "job_id": "x-1",
            "normalized_title": "Engineer",
            "normalized_company": "A",
            "minimum_experience_years": None,
            "experience_requirement_type": "not_stated",
            "career_level": "unspecified",
            "citizenship": {"requirement": "not_stated", "country_code": None, "evidence_text": None},
            "work_authorization": {"sponsorship": "unknown", "evidence_text": None},
            "degree_fields": [],
            "requirements": [
                {"requirement_id": "x-1-r1", "canonical_value": "sql", "category": "technical_skills",
                 "necessity": "preferred", "importance": "supporting", "critical": False,
                 "original_text": "Familiarity with SQL, Python, or other data tools is a plus", "alternatives": ["python"]},
                {"requirement_id": "x-1-r2", "canonical_value": "python", "category": "technical_skills",
                 "necessity": "preferred", "importance": "supporting", "critical": False,
                 "original_text": "Familiarity with SQL, Python, or other data tools is a plus", "alternatives": ["sql"]},
                {"requirement_id": "x-1-r3", "canonical_value": "docker", "category": "tools_deployment",
                 "necessity": "required", "importance": "supporting", "critical": False,
                 "original_text": "Docker experience required.", "alternatives": []},
            ],
            "warnings": [],
        }],
    }
    parsed = ExtractionResult.model_validate(raw)
    warnings = duplicate_evidence_warnings(parsed)
    assert len(warnings) == 1
    assert warnings[0]["job_id"] == "x-1"
    assert warnings[0]["canonical_values"] == ["sql", "python"]
    # A single requirement sharing no evidence with others warns nothing.
    raw["jobs"][0]["requirements"] = raw["jobs"][0]["requirements"][:1]
    assert duplicate_evidence_warnings(ExtractionResult.model_validate(raw)) == []
