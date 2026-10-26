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
