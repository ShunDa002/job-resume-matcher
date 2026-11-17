"""Scrape job listings from JobStreet (Singapore) into the JSON format
that ``jobmatch ingest-jobs`` accepts.

This is a first-class *input* step for the matcher: it only fetches
public listings and writes them to disk. It never touches matching,
scoring, eligibility, or the database (unless the caller passes
``--ingest`` to the CLI, which then runs the normal ingest path).
The deterministic matching engine is untouched by this module.

Playwright is an *optional* dependency (``pip install -e '.[scrape]'``
plus ``playwright install chromium``). Importing this module must not
require Playwright: the browser import happens lazily inside
:func:`scrape_jobstreet`, and the pure helpers
(:func:`convert_jsonl_to_json`, :func:`safe_extract_text`,
:func:`find_next_page_link`, :func:`go_to_next_page`) work without it,
so the rest of the tool and its tests run on a plain install.

The record shape matches the job-list JSON the matcher already
ingests (see ``normalize_job``): ``page``, ``page_job_index``,
``total_job_index``, ``title``, ``company``, ``location``, ``salary``,
``work_type``, ``role_classification``, ``job_url``, ``description``.
``normalize_job`` derives the source and job id from ``job_url`` and
ignores the page/index bookkeeping fields, so scraped files feed
``ingest-jobs`` directly.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    from playwright.sync_api import Browser, BrowserContext, Page, Playwright
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

DEFAULT_URL = (
    "https://sg.jobstreet.com/AI-jobs/full-time?pos=1&source=RECENT"
)


def _require_playwright():
    """Import Playwright lazily; explain the optional install if missing."""
    try:
        from playwright.sync_api import sync_playwright
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    except ImportError as e:  # pragma: no cover - depends on the environment
        raise RuntimeError(
            "Playwright is not installed. Scraping needs the optional "
            "dependency: run `pip install -e '.[scrape]'` and then "
            "`playwright install chromium`."
        ) from e
    return sync_playwright, PlaywrightTimeoutError


def safe_extract_text(locator) -> Optional[str]:
    try:
        if locator.count() > 0:
            first_elem = locator.first
            if first_elem.is_visible():
                text = first_elem.inner_text().strip()
                return text if text else None
    except Exception:
        pass
    return None


def dismiss_cookie_consent(page: "Page") -> None:
    try:
        consent_btn = page.locator(
            'button:has-text("Accept"), button:has-text("Agree"), button:has-text("OK")'
        )
        if consent_btn.count() > 0 and consent_btn.first.is_visible():
            consent_btn.first.click()
            page.wait_for_timeout(1000)
    except Exception:
        pass


def create_browser_context(browser: "Browser") -> "BrowserContext":
    context = browser.new_context(
        viewport={"width": 1440, "height": 900},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        ignore_https_errors=True,
    )

    def route_filter(route):
        if route.request.resource_type in ["image", "media", "font"]:
            route.abort()
        else:
            route.continue_()

    context.route("**/*", route_filter)
    return context


def find_next_page_link(page: "Page") -> Tuple[Optional[Any], Optional[str]]:
    next_selectors = [
        '[data-automation="page-next"]',
        'a[aria-label="Next"]',
        'a[rel="next"]',
        'nav[aria-label="Pagination"] a:has-text("Next")',
        'a:has-text("Next")',
    ]

    for selector in next_selectors:
        candidate = page.locator(selector).first
        if candidate.count() > 0 and candidate.is_visible():
            next_href = candidate.get_attribute("href")
            return candidate, next_href

    return None, None


def go_to_next_page(page: "Page") -> bool:
    next_btn, next_href = find_next_page_link(page)

    if not next_btn:
        logger.info("Next page button not found. Reached the last page.")
        return False

    aria_disabled = next_btn.get_attribute("aria-disabled")
    if aria_disabled == "true" or not next_btn.is_enabled():
        logger.info("Next page button is disabled. Reached the last page.")
        return False

    try:
        next_btn.scroll_into_view_if_needed()
        page.wait_for_timeout(500)
        next_btn.click()

        page.wait_for_load_state("domcontentloaded", timeout=15000)
        page.wait_for_timeout(3000)
        return True
    except Exception as e:
        logger.warning(
            f"Click on Next button failed ({e}), attempting direct href navigation fallback..."
        )
        if next_href:
            full_next_url = (
                f"https://sg.jobstreet.com{next_href}"
                if next_href.startswith("/")
                else next_href
            )
            page.goto(full_next_url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)
            return True
        return False


def convert_jsonl_to_json(jsonl_file: str, json_file: Optional[str] = None) -> str:
    input_path = os.path.abspath(jsonl_file)
    output_path = (
        os.path.abspath(json_file)
        if json_file
        else os.path.splitext(input_path)[0] + ".json"
    )

    records: List[Any] = []
    with open(input_path, "r", encoding="utf-8") as in_f:
        for line_number, line in enumerate(in_f, start=1):
            stripped_line = line.strip()
            if not stripped_line:
                continue
            try:
                records.append(json.loads(stripped_line))
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid JSON in {jsonl_file} at line {line_number}: {exc.msg}"
                ) from exc

    with open(output_path, "w", encoding="utf-8") as out_f:
        json.dump(records, out_f, ensure_ascii=False, indent=2)
        out_f.write("\n")

    logger.info(f"Converted {len(records)} records from {jsonl_file} to {output_path}.")
    return output_path


def scrape_jobstreet(
    target_url: str = DEFAULT_URL,
    max_pages: Optional[int] = 2,
    headless: bool = True,
    output_file: str = "jobstreet_ai_jobs.jsonl",
    recycle_interval: int = 50,
    append: bool = False,
) -> int:
    """Scrape JobStreet search results to JSONL, then convert to JSON.

    Returns the number of jobs actually saved. ``total_job_index`` counts
    only saved jobs: unlike the original script, a card that fails to
    scrape does not consume an index.
    """
    sync_playwright, PlaywrightTimeoutError = _require_playwright()

    has_display = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    if not headless and not has_display:
        logger.warning(
            "No graphical display ($DISPLAY) detected in this environment. "
            "Automatically falling back to headless=True to prevent browser launch failure."
        )
        headless = True

    total_scraped_count = 0
    current_page = 1
    file_mode = "a" if append else "w"

    output_file = os.path.abspath(os.path.expanduser(output_file))
    output_directory = os.path.dirname(output_file)
    if output_directory:
        os.makedirs(output_directory, exist_ok=True)

    with (
        open(output_file, file_mode, encoding="utf-8") as out_f,
        sync_playwright() as playwright,
    ):
        try:
            browser = playwright.chromium.launch(
                headless=headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
        except Exception as e:
            if not headless:
                logger.warning(
                    f"Headed browser launch failed ({e}). "
                    "An X server or display is not available. Falling back to headless=True..."
                )
                browser = playwright.chromium.launch(
                    headless=True,
                    args=["--disable-blink-features=AutomationControlled"],
                )
            else:
                raise e

        context = create_browser_context(browser)
        page = context.new_page()

        logger.info(f"Navigating to initial search page: {target_url}...")
        try:
            response = page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            logger.error(f"Failed to load {target_url}: {e}")
            context.close()
            browser.close()
            convert_jsonl_to_json(output_file)
            return 0

        content = page.content()
        if "Approval required" in content and "sbx policy approval" in content:
            logger.error(
                "\n" + "=" * 70 + "\n"
                "[NETWORK PROXY BLOCKED] Egress approval required for sg.jobstreet.com:443.\n"
                "Your sandbox environment proxy blocked outbound access to JobStreet.\n"
                "To fix this, run the following on your host machine:\n\n"
                "  sbx policy approval ls\n"
                "  (approve the pending request for sg.jobstreet.com)\n" + "=" * 70
            )
            context.close()
            browser.close()
            convert_jsonl_to_json(output_file)
            return 0

        if response and response.status >= 400:
            logger.error(
                f"HTTP Error {response.status} when loading {target_url}. Page title: '{page.title()}'"
            )
            context.close()
            browser.close()
            convert_jsonl_to_json(output_file)
            return 0

        page.wait_for_timeout(2000)
        dismiss_cookie_consent(page)

        while True:
            logger.info(
                f"==================== Scraping Page {current_page} ===================="
            )

            try:
                page.wait_for_selector(
                    'article[data-automation="jobListing"], article',
                    state="attached",
                    timeout=15000,
                )
            except PlaywrightTimeoutError:
                logger.warning(
                    f"Timed out waiting for job articles on page {current_page}. "
                    f"Page Title: '{page.title()}', URL: '{page.url}'"
                )

            article_locator = page.locator(
                'article[data-automation="jobListing"], article'
            )
            article_count = article_locator.count()
            logger.info(f"Found {article_count} job articles on Page {current_page}.")

            if article_count == 0:
                logger.warning(
                    f"No job articles found on page {current_page}. Ending scrape."
                )
                break

            page_jobs: List[Dict[str, Any]] = []

            for idx in range(article_count):
                card = article_locator.nth(idx)
                try:
                    card.scroll_into_view_if_needed()
                    page.wait_for_timeout(400)

                    card_title = safe_extract_text(
                        card.locator('[data-automation="jobTitle"], h3, h1')
                    )
                    card_company = safe_extract_text(
                        card.locator('[data-automation="jobCompany"]')
                    )
                    card_location = safe_extract_text(
                        card.locator('[data-automation="jobLocation"]')
                    )
                    card_salary = safe_extract_text(
                        card.locator('[data-automation="jobSalary"]')
                    )

                    overlay = card.get_by_test_id("job-list-item-link-overlay")
                    if overlay.count() == 0:
                        overlay = card.locator('a[data-automation="jobTitle"], a').first

                    job_href = (
                        overlay.get_attribute("href") if overlay.count() > 0 else None
                    )
                    job_url = (
                        f"https://sg.jobstreet.com{job_href}"
                        if job_href and job_href.startswith("/")
                        else job_href
                    )

                    logger.info(
                        f"[Page {current_page} | Job {idx + 1}/{article_count} | Total #{total_scraped_count + 1}] "
                        f"Scraping: {card_title or 'Job'}"
                    )

                    overlay.click()

                    desc_locator = page.locator(
                        '[data-automation="jobDescription"], [data-automation="jobAdDetails"], [data-testid="job-description"]'
                    ).first
                    try:
                        desc_locator.wait_for(state="visible", timeout=4000)
                    except PlaywrightTimeoutError:
                        pass

                    detail_title = (
                        safe_extract_text(
                            page.locator(
                                '[data-automation="job-detail-title"], [data-automation="jobDetailsTitle"], h1'
                            ).first
                        )
                        or card_title
                    )

                    detail_company = (
                        safe_extract_text(
                            page.locator(
                                '[data-automation="advertiser-name"], [data-automation="jobCompany"]'
                            ).first
                        )
                        or card_company
                    )

                    detail_location = (
                        safe_extract_text(
                            page.locator(
                                '[data-automation="job-detail-location"]'
                            ).first
                        )
                        or card_location
                    )

                    detail_salary = (
                        safe_extract_text(
                            page.locator('[data-automation="job-detail-salary"]').first
                        )
                        or card_salary
                    )

                    work_type = safe_extract_text(
                        page.locator('[data-automation="job-detail-work-type"]').first
                    )

                    classification = safe_extract_text(
                        page.locator(
                            '[data-automation="job-detail-classifications"]'
                        ).first
                    )

                    job_description = safe_extract_text(desc_locator)
                    if not job_description:
                        fallback_desc = page.locator(
                            'div[class*="description"], div[class*="Description"]'
                        )
                        if fallback_desc.count() > 0:
                            job_description = safe_extract_text(fallback_desc.first)

                    total_scraped_count += 1
                    job_item = {
                        "page": current_page,
                        "page_job_index": idx + 1,
                        "total_job_index": total_scraped_count,
                        "title": detail_title,
                        "company": detail_company,
                        "location": detail_location,
                        "salary": detail_salary if detail_salary else "Not Disclosed",
                        "work_type": work_type,
                        "role_classification": classification,
                        "job_url": job_url,
                        "description": job_description,
                    }

                    page_jobs.append(job_item)

                except Exception as e:
                    logger.error(
                        f"Error scraping job index {idx + 1} on page {current_page}: {e}"
                    )

            if page_jobs:
                for job in page_jobs:
                    out_f.write(json.dumps(job, ensure_ascii=False) + "\n")
                out_f.flush()
                logger.info(
                    f"Flushed {len(page_jobs)} jobs from Page {current_page} to {output_file} "
                    f"(Total saved: {total_scraped_count})"
                )
                page_jobs.clear()

            if max_pages is not None and current_page >= max_pages:
                logger.info(f"Reached max_pages limit ({max_pages}). Stopping scrape.")
                break

            next_btn, next_href = find_next_page_link(page)
            if not next_btn:
                logger.info("No further pages available (Next button not found).")
                break

            aria_disabled = next_btn.get_attribute("aria-disabled")
            if aria_disabled == "true" or not next_btn.is_enabled():
                logger.info("Next page button is disabled. Reached the last page.")
                break

            logger.info(f"Finished Page {current_page}. Moving to next page...")

            if current_page % recycle_interval == 0:
                logger.info(
                    f"Reached page milestone ({current_page}). "
                    f"Recycling browser context to clear Chromium memory..."
                )
                if next_href:
                    next_url = (
                        f"https://sg.jobstreet.com{next_href}"
                        if next_href.startswith("/")
                        else next_href
                    )
                else:
                    # No href to navigate to directly: click through, and
                    # stop instead of re-scraping the current page.
                    if not go_to_next_page(page):
                        logger.info("No further pages available.")
                        break
                    next_url = page.url

                try:
                    page.close()
                except Exception:
                    pass
                try:
                    context.close()
                except Exception:
                    pass

                context = create_browser_context(browser)
                page = context.new_page()

                logger.info(
                    f"Navigating recycled context to page {current_page + 1}: {next_url}"
                )
                page.goto(next_url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(2000)
                dismiss_cookie_consent(page)
            else:
                has_next = go_to_next_page(page)
                if not has_next:
                    logger.info("No further pages available.")
                    break

            current_page += 1

        try:
            page.close()
        except Exception:
            pass
        try:
            context.close()
        except Exception:
            pass
        browser.close()

    logger.info(
        f"Scraping completed. Total jobs extracted: {total_scraped_count} across {current_page} page(s)."
    )
    json_output_file = convert_jsonl_to_json(output_file)
    logger.info(f"JSON output saved to: {json_output_file}")
    return total_scraped_count
