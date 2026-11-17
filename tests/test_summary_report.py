from enum import Enum
from types import SimpleNamespace

from jobmatcher.summary_report import build_summary


class Value(str, Enum):
    REQUIRED = "required"
    CORE = "core"
    ELIGIBLE = "ELIGIBLE"


def test_build_summary_contains_only_requested_fields():
    requirement = SimpleNamespace(
        original_text="Python",
        canonical_value="python",
        necessity=Value.REQUIRED,
        importance=Value.CORE,
        critical=True,
        alternatives=[],
    )
    job = SimpleNamespace(
        job_id="jobstreet_sg-1",
        requirements=[requirement],
        source_url="https://sg.jobstreet.com/job/1",
    )
    result = SimpleNamespace(
        job_id="jobstreet_sg-1",
        eligibility_status=Value.ELIGIBLE,
        scores=SimpleNamespace(final_match_score=88.5),
    )

    rows = build_summary([result], [job])

    assert list(rows[0]) == [
        "rank",
        "job_id",
        "eligibility",
        "final_match_score",
        "assessment_confidence",
        "requirement_count",
        "thin_evidence",
        "requirements",
        "jobstreet_url",
    ]
    assert rows[0]["rank"] == 1
    assert rows[0]["final_match_score"] == 88.5
    assert rows[0]["requirements"] == ["Python [required, core, critical]"]
