import json
from pathlib import Path
from jobmatcher.models import CandidateProfile,JobRecord
from jobmatcher.normalize import normalize_job
from jobmatcher.config import load_yaml,default_config
from jobmatcher.eligibility import determine_eligibility
from jobmatcher.scoring import score_job

def test_score_is_repeatable():
    c=CandidateProfile.model_validate_json(Path("examples/candidate.json").read_text())
    j=normalize_job(json.loads(Path("examples/jobs.json").read_text())[0])
    ep=load_yaml(default_config("eligibility-policy.v1.yaml")); sp=load_yaml(default_config("scoring-policy.v1.yaml")); tx=load_yaml(default_config("skill-taxonomy.v1.yaml"))
    status,reasons,risk=determine_eligibility(c,j,ep)
    versions={"eligibility":ep["version"],"scoring":sp["version"],"taxonomy":tx["version"]}
    a=score_job(c,j,status,reasons,risk,sp,tx,versions); b=score_job(c,j,status,reasons,risk,sp,tx,versions)
    assert a.model_dump()==b.model_dump()
    assert a.scores.final_match_score>80
