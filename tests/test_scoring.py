import json
from pathlib import Path
from jobmatcher.models import CandidateProfile,JobRecord,Requirement
from jobmatcher.normalize import normalize_job
from jobmatcher.config import load_yaml,default_config
from jobmatcher.eligibility import determine_eligibility
from jobmatcher.scoring import score_job

def _policies():
    ep=load_yaml(default_config("eligibility-policy.v1.yaml")); sp=load_yaml(default_config("scoring-policy.v2.yaml")); tx=load_yaml(default_config("skill-taxonomy.v1.yaml"))
    return ep,sp,tx

def test_score_is_repeatable():
    c=CandidateProfile.model_validate_json(Path("examples/candidate.json").read_text())
    j=normalize_job(json.loads(Path("examples/jobs.json").read_text())[0])
    ep,sp,tx=_policies()
    status,reasons,risk=determine_eligibility(c,j,ep)
    versions={"eligibility":ep["version"],"scoring":sp["version"],"taxonomy":tx["version"]}
    a=score_job(c,j,status,reasons,risk,sp,tx,versions); b=score_job(c,j,status,reasons,risk,sp,tx,versions)
    assert a.model_dump()==b.model_dump()
    assert a.scores.final_match_score>80

def _job_with_reqs(n):
    reqs=[Requirement(requirement_id=f"r{i}",canonical_value="python",category="technical_skills",necessity="required",importance="core",original_text="Python") for i in range(n)]
    return JobRecord(job_id=f"test-{n}",source="x",title="x",company="x",location_country_code="SG",description="x",requirements=reqs)

def test_confidence_scales_with_evidence():
    # Same candidate, same requirement content: fewer requirements
    # must mean lower confidence and a thin-evidence flag.
    c=CandidateProfile.model_validate_json(Path("examples/candidate.json").read_text())
    ep,sp,tx=_policies()
    versions={"eligibility":ep["version"],"scoring":sp["version"],"taxonomy":tx["version"]}
    out=[]
    for n in (3,10):
        j=_job_with_reqs(n)
        status,reasons,risk=determine_eligibility(c,j,ep)
        out.append(score_job(c,j,status,reasons,risk,sp,tx,versions))
    few,many=out
    assert few.requirement_count==3 and few.thin_evidence is True
    assert many.requirement_count==10 and many.thin_evidence is False
    assert few.scores.assessment_confidence<many.scores.assessment_confidence
    assert few.scores.assessment_confidence<50
    assert many.scores.assessment_confidence>80
