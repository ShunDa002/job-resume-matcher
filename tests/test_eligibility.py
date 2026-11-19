from jobmatcher.models import CandidateProfile,JobRecord
from jobmatcher.eligibility import determine_eligibility
from jobmatcher.config import load_yaml,default_config

def c(): return CandidateProfile(candidate_id="c",citizenship_country_code="MY",career_level="fresh_graduate")
def test_citizenship_precedes_skills():
    j=JobRecord(source="x",title="x",company="x",location_country_code="SG",description="x",required_citizenship_country_code="SG")
    s,_,_=determine_eligibility(c(),j,load_yaml(default_config("eligibility-policy.v2.yaml")))
    assert s.value=="INELIGIBLE_CITIZENSHIP"
def test_experience():
    j=JobRecord(source="x",title="x",company="x",location_country_code="SG",description="x",minimum_experience_years=3,experience_requirement_type="required")
    s,_,_=determine_eligibility(c(),j,load_yaml(default_config("eligibility-policy.v2.yaml")))
    assert s.value=="INELIGIBLE_EXPERIENCE"
def test_insufficient_information_when_nothing_extracted():
    # No requirements, no degree, no experience minimum: there is
    # nothing to score, so this must not become a vacuous 100.
    j=JobRecord(source="x",title="x",company="x",location_country_code="SG",description="x")
    s,_,_=determine_eligibility(c(),j,load_yaml(default_config("eligibility-policy.v2.yaml")))
    assert s.value=="INSUFFICIENT_INFORMATION"
def test_enrollment_required_is_ineligible_for_graduate():
    # A job that requires current enrollment (the usual internship
    # condition) cannot be taken by a candidate who has graduated.
    j=JobRecord(source="x",title="Data Science Intern",company="x",location_country_code="SG",description="x",requires_current_enrollment=True)
    s,reasons,_=determine_eligibility(c(),j,load_yaml(default_config("eligibility-policy.v2.yaml")))
    assert s.value=="INELIGIBLE_ENROLLMENT"
    assert any("enrollment" in r for r in reasons)

def test_enrollment_required_passes_for_enrolled_candidate():
    cand=c(); cand.currently_enrolled=True
    j=JobRecord(source="x",title="Data Science Intern",company="x",location_country_code="SG",description="x",requires_current_enrollment=True,degree_fields=["computer_science"])
    s,_,_=determine_eligibility(cand,j,load_yaml(default_config("eligibility-policy.v2.yaml")))
    assert s.value in ("ELIGIBLE","CONDITIONALLY_ELIGIBLE")

def test_internship_without_enrollment_requirement_is_not_filtered():
    # "Pursuing or recently completed" is not a strict enrollment
    # requirement, so the enrollment gate must not fire on it.
    j=JobRecord(source="x",title="Data Science Intern",company="x",location_country_code="SG",description="x",requires_current_enrollment=False,degree_fields=["computer_science"])
    s,_,_=determine_eligibility(c(),j,load_yaml(default_config("eligibility-policy.v2.yaml")))
    assert s.value in ("ELIGIBLE","CONDITIONALLY_ELIGIBLE")

def test_preferred_experience_gap_is_visible():
    # "Preferred" 3+ years is not a hard gate, but the gap must be
    # stated: a high skill score must not hide it.
    j=JobRecord(source="x",title="x",company="x",location_country_code="SG",description="x",minimum_experience_years=8,experience_requirement_type="preferred")
    s,reasons,_=determine_eligibility(c(),j,load_yaml(default_config("eligibility-policy.v2.yaml")))
    assert s.value=="CONDITIONALLY_ELIGIBLE"
    assert any("Prefers 8+ years" in r for r in reasons)

def test_degree_only_is_not_insufficient():
    j=JobRecord(source="x",title="x",company="x",location_country_code="SG",description="x",degree_fields=["computer_science"])
    s,_,_=determine_eligibility(c(),j,load_yaml(default_config("eligibility-policy.v2.yaml")))
    assert s.value in ("ELIGIBLE","CONDITIONALLY_ELIGIBLE")
