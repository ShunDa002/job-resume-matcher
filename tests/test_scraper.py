"""Scraper: pure helpers, CLI wiring, and the scrape -> ingest contract.

No test here needs a real browser: Playwright is stubbed out, and the
live scrape is exercised by hand (see README), not by the suite.
Importing the scraper module must not require Playwright.
"""
import json
import sys
from pathlib import Path

import jobmatcher.scraper as scraper_mod
from jobmatcher.db import get_jobs, init_db, upsert_job
from jobmatcher.normalize import normalize_job

assert "playwright" not in sys.modules


# --- stubs ---------------------------------------------------------------

class _El:
    def __init__(self, text=None, visible=True, href=None, enabled=True,
                 aria_disabled=None, click_raises=None):
        self._text = text
        self._visible = visible
        self._href = href
        self._enabled = enabled
        self._aria_disabled = aria_disabled
        self._click_raises = click_raises
        self.clicked = False

    def is_visible(self):
        return self._visible

    def inner_text(self):
        if self._text is None:
            raise RuntimeError("no text")
        return self._text

    def get_attribute(self, name):
        if name == "href":
            return self._href
        if name == "aria-disabled":
            return self._aria_disabled
        return None

    def is_enabled(self):
        return self._enabled

    def click(self):
        if self._click_raises:
            raise self._click_raises
        self.clicked = True

    def scroll_into_view_if_needed(self):
        pass


class _Locator:
    def __init__(self, elements=None):
        self._els = list(elements or [])

    def count(self):
        return len(self._els)

    @property
    def first(self):
        return _Locator(self._els[:1])

    def is_visible(self):
        return bool(self._els) and self._els[0].is_visible()

    def inner_text(self):
        return self._els[0].inner_text()

    def get_attribute(self, name):
        return self._els[0].get_attribute(name) if self._els else None

    def is_enabled(self):
        return bool(self._els) and self._els[0].is_enabled()

    def click(self):
        self._els[0].click()

    def scroll_into_view_if_needed(self):
        pass

    def wait_for(self, **kwargs):
        pass


class _Page:
    def __init__(self, by_selector=None):
        self.by_selector = by_selector or {}
        self.goto_urls = []
        self.title_text = "x"
        self.url = "https://sg.jobstreet.com/AI-jobs"

    def locator(self, selector):
        return self.by_selector.get(selector, _Locator([]))

    def wait_for_timeout(self, ms):
        pass

    def wait_for_load_state(self, *args, **kwargs):
        pass

    def wait_for_selector(self, *args, **kwargs):
        pass

    def goto(self, url, **kwargs):
        self.goto_urls.append(url)


# --- convert_jsonl_to_json ------------------------------------------------

def test_convert_jsonl_to_json(tmp_path):
    src = tmp_path / "jobs.jsonl"
    src.write_text('{"a": 1}\n\n{"a": 2}\n', encoding="utf-8")
    out = scraper_mod.convert_jsonl_to_json(str(src))
    assert out == str(tmp_path / "jobs.json")
    assert json.loads(Path(out).read_text(encoding="utf-8")) == [{"a": 1}, {"a": 2}]


def test_convert_jsonl_to_json_bad_line_names_the_line(tmp_path):
    src = tmp_path / "jobs.jsonl"
    src.write_text('{"a": 1}\nnot json\n', encoding="utf-8")
    try:
        scraper_mod.convert_jsonl_to_json(str(src))
    except ValueError as e:
        assert "line 2" in str(e)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError")


def test_convert_jsonl_to_json_empty_file(tmp_path):
    src = tmp_path / "jobs.jsonl"
    src.write_text("", encoding="utf-8")
    out = scraper_mod.convert_jsonl_to_json(str(src))
    assert json.loads(Path(out).read_text(encoding="utf-8")) == []


# --- safe_extract_text / cookie consent -----------------------------------

def test_safe_extract_text():
    assert scraper_mod.safe_extract_text(_Locator([_El(text="  Hello  ")])) == "Hello"
    assert scraper_mod.safe_extract_text(_Locator([_El(text="   ")])) is None
    assert scraper_mod.safe_extract_text(_Locator([_El(text="x", visible=False)])) is None
    assert scraper_mod.safe_extract_text(_Locator([])) is None
    assert scraper_mod.safe_extract_text(_Locator([_El(text=None)])) is None


def test_dismiss_cookie_consent_clicks_visible_button():
    btn = _El(text="Accept")
    page = _Page({"button:has-text(\"Accept\"), button:has-text(\"Agree\"), button:has-text(\"OK\")": _Locator([btn])})
    scraper_mod.dismiss_cookie_consent(page)
    assert btn.clicked


def test_dismiss_cookie_consent_no_button_is_fine():
    scraper_mod.dismiss_cookie_consent(_Page({}))


# --- pagination -----------------------------------------------------------

def test_find_next_page_link_prefers_first_matching_selector():
    el = _El(href="/AI-jobs?page=2")
    page = _Page({'a[aria-label="Next"]': _Locator([el])})
    btn, href = scraper_mod.find_next_page_link(page)
    assert href == "/AI-jobs?page=2"
    assert btn is not None


def test_find_next_page_link_none_when_absent():
    assert scraper_mod.find_next_page_link(_Page({})) == (None, None)


def test_go_to_next_page_clicks_and_returns_true():
    el = _El(href="/AI-jobs?page=2")
    page = _Page({'[data-automation="page-next"]': _Locator([el])})
    assert scraper_mod.go_to_next_page(page) is True
    assert el.clicked


def test_go_to_next_page_disabled_returns_false():
    el = _El(href="/AI-jobs?page=2", aria_disabled="true")
    page = _Page({'[data-automation="page-next"]': _Locator([el])})
    assert scraper_mod.go_to_next_page(page) is False
    assert not el.clicked


def test_go_to_next_page_click_failure_falls_back_to_href():
    el = _El(href="/AI-jobs?page=2", click_raises=RuntimeError("boom"))
    page = _Page({'[data-automation="page-next"]': _Locator([el])})
    assert scraper_mod.go_to_next_page(page) is True
    assert page.goto_urls == ["https://sg.jobstreet.com/AI-jobs?page=2"]


# --- CLI wiring (scraper itself is stubbed) --------------------------------

def _fake_records():
    return [
        {"page": 1, "page_job_index": 1, "total_job_index": 1,
         "title": "AI Engineer", "company": "Acme Pte Ltd",
         "location": "Singapore", "salary": "Not Disclosed",
         "work_type": "Full time", "role_classification": "Information Technology",
         "job_url": "https://sg.jobstreet.com/job/95562469",
         "description": "Build LLM features with Python."},
        {"page": 1, "page_job_index": 2, "total_job_index": 2,
         "title": "Data Analyst", "company": "Beta Pte Ltd",
         "location": "Singapore", "salary": "$5,000 - $7,000 per month",
         "work_type": "Full time", "role_classification": "Information Technology",
         "job_url": "https://sg.jobstreet.com/job/95562470",
         "description": None},
    ]


def test_scrape_jobs_command_writes_json_and_ingests(tmp_path, monkeypatch):
    from typer.testing import CliRunner
    from jobmatcher.cli import app

    out = tmp_path / "jobs.jsonl"

    def fake_scrape(**kwargs):
        records = _fake_records()
        out.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
        Path(str(out.with_suffix(".json"))).write_text(
            json.dumps(records), encoding="utf-8")
        return len(records)

    monkeypatch.setattr(scraper_mod, "scrape_jobstreet", fake_scrape)
    db = tmp_path / "x.db"
    r = CliRunner().invoke(app, ["scrape-jobs", "--url", "https://example.invalid/x",
                                 "--max-pages", "1", "--output", str(out),
                                 "--ingest", "--db", str(db)])
    assert r.exit_code == 0, r.output
    assert json.loads((tmp_path / "jobs.json").read_text(encoding="utf-8")) == _fake_records()
    stored = get_jobs(str(db))
    assert {j.job_id for j in stored} == {"jobstreet_sg-95562469", "jobstreet_sg-95562470"}


def test_scrape_jobs_command_without_playwright_exits_1(tmp_path, monkeypatch):
    from typer.testing import CliRunner
    from jobmatcher.cli import app

    def missing(**kwargs):
        raise RuntimeError("Playwright is not installed.")

    monkeypatch.setattr(scraper_mod, "scrape_jobstreet", missing)
    r = CliRunner().invoke(app, ["scrape-jobs", "--output", str(tmp_path / "jobs.jsonl")])
    assert r.exit_code == 1
    assert "Playwright is not installed" in r.output


def test_scrape_jobs_zero_results_does_not_crash_ingest(tmp_path, monkeypatch):
    """A scrape that finds nothing (e.g. a blocked page) must not crash
    --ingest: the CLI reports it instead of failing on a missing JSON."""
    from typer.testing import CliRunner
    from jobmatcher.cli import app

    def nothing_scraped(**kwargs):
        return 0  # writes no JSON, like an early-return scrape

    monkeypatch.setattr(scraper_mod, "scrape_jobstreet", nothing_scraped)
    out = tmp_path / "jobs.jsonl"
    r = CliRunner().invoke(app, ["scrape-jobs", "--output", str(out),
                                 "--ingest", "--db", str(tmp_path / "x.db")])
    assert r.exit_code == 0, r.output
    assert '"scraped": 0' in r.output
    assert "Nothing scraped" in r.output


# --- scrape -> ingest contract --------------------------------------------

def test_scraper_record_ingests(tmp_path):
    record = _fake_records()[0]
    record["description"] = None  # scraper may fail to extract a description
    job = normalize_job(record)
    assert job.job_id == "jobstreet_sg-95562469"
    assert job.source == "jobstreet_sg"
    assert job.description == ""
    assert job.salary.disclosed is False
    assert job.employment_type == "full_time"
    assert job.location_country_code == "SG"

    db = tmp_path / "x.db"
    init_db(db)
    upsert_job(db, job)
    assert len(get_jobs(str(db))) == 1


def test_scraper_record_with_salary_parses(tmp_path):
    job = normalize_job(_fake_records()[1])
    assert job.salary.disclosed is True
    assert job.salary.minimum == 5000
    assert job.salary.maximum == 7000
    assert job.salary.period == "month"
