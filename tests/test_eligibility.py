from jobmatcher.models import CandidateProfile,JobRecord
from jobmatcher.eligibility import determine_eligibility
from jobmatcher.config import load_yaml,default_config

def c(): return CandidateProfile(candidate_id="c",citizenship_country_code="MY",career_level="fresh_graduate")
def test_citizenship_precedes_skills():
    j=JobRecord(source="x",title="x",company="x",location_country_code="SG",description="x",required_citizenship_country_code="SG")
    s,_,_=determine_eligibility(c(),j,load_yaml(default_config("eligibility-policy.v1.yaml")))
    assert s.value=="INELIGIBLE_CITIZENSHIP"
def test_experience():
    j=JobRecord(source="x",title="x",company="x",location_country_code="SG",description="x",minimum_experience_years=3,experience_requirement_type="required")
    s,_,_=determine_eligibility(c(),j,load_yaml(default_config("eligibility-policy.v1.yaml")))
    assert s.value=="INELIGIBLE_EXPERIENCE"
def test_insufficient_information_when_nothing_extracted():
    # No requirements, no degree, no experience minimum: there is
    # nothing to score, so this must not become a vacuous 100.
    j=JobRecord(source="x",title="x",company="x",location_country_code="SG",description="x")
    s,_,_=determine_eligibility(c(),j,load_yaml(default_config("eligibility-policy.v1.yaml")))
    assert s.value=="INSUFFICIENT_INFORMATION"
def test_degree_only_is_not_insufficient():
    j=JobRecord(source="x",title="x",company="x",location_country_code="SG",description="x",degree_fields=["computer_science"])
    s,_,_=determine_eligibility(c(),j,load_yaml(default_config("eligibility-policy.v1.yaml")))
    assert s.value in ("ELIGIBLE","CONDITIONALLY_ELIGIBLE")
