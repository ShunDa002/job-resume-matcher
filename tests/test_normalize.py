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
