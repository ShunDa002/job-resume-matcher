from jobmatcher.normalize import parse_salary, normalize_job


def test_salary():
    s = parse_salary("$4,400 - $6,000 per month")
    assert (s.currency, s.minimum, s.maximum, s.period) == ("SGD", 4400, 6000, "month")


def test_url_and_id():
    job = normalize_job({
        "source": "JobStreet SG",
        "joburl": '<a href="https://sg.jobstreet.com/job/123?x=1#y">x</a>',
        "title": " Test  Job ",
        "company": "Acme",
        "location_country_code": "SG",
        "description": "hello",
    })
    assert job.job_id == "jobstreet_sg-123"
    assert job.source_url == "https://sg.jobstreet.com/job/123"


def test_scraped_job_normalization():
    job = normalize_job({
        "title": "AI Engineer",
        "company": "Tech Corp",
        "location": "Tuas, West Region",
        "job_url": "https://sg.jobstreet.com/job/95455412?type=standard#sol=123",
        "work_type": "Full time",
        "salary": "$3,000 – $4,500 per month",
        "description": "Develop models.",
    })
    assert job.job_id == "jobstreet_sg-95455412"
    assert job.source == "jobstreet_sg"
    assert job.source_url == "https://sg.jobstreet.com/job/95455412"
    assert job.location_country_code == "SG"
    assert job.location_text == "Tuas, West Region"
    assert job.employment_type == "full_time"
    assert job.salary.disclosed is True
    assert job.salary.minimum == 3000.0
    assert job.salary.maximum == 4500.0


def test_input_jobs_json_normalization():
    import json
    from pathlib import Path
    p = Path("data/input/jobs.json")
    if p.exists():
        raw = json.loads(p.read_text(encoding="utf-8"))
        items = raw if isinstance(raw, list) else raw["jobs"]
        assert len(items) == 30
        for item in items:
            j = normalize_job(item)
            assert j.location_country_code == "SG"
            assert j.source == "jobstreet_sg"
            assert j.job_id.startswith("jobstreet_sg-")

