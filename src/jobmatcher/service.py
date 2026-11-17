from __future__ import annotations
from .config import load_yaml,default_config
from .db import get_candidate,get_jobs,save_match
from .eligibility import determine_eligibility
from .scoring import score_job
from .util import sha256_data

def run_match(db_path,candidate_id,eligibility_path=None,scoring_path=None,taxonomy_path=None):
    eligibility_path=eligibility_path or default_config("eligibility-policy.v1.yaml")
    scoring_path=scoring_path or default_config("scoring-policy.v1.yaml")
    taxonomy_path=taxonomy_path or default_config("skill-taxonomy.v1.yaml")
    ep,sp,tax=load_yaml(eligibility_path),load_yaml(scoring_path),load_yaml(taxonomy_path)
    versions={"eligibility":ep["version"],"scoring":sp["version"],"taxonomy":tax["version"]}
    run_key=sha256_data({"candidate_id":candidate_id,"versions":versions})
    candidate=get_candidate(db_path,candidate_id); results=[]
    for job in get_jobs(db_path):
        status,reasons,risk=determine_eligibility(candidate,job,ep)
        result=score_job(candidate,job,status,reasons,risk,sp,tax,versions)
        save_match(db_path,result,run_key); results.append(result)
    rank=sp["eligibility_rank"]
    results.sort(key=lambda r:(rank[r.eligibility_status.value],-(r.scores.final_match_score if r.scores else -1),len(r.critical_gaps),-(r.scores.assessment_confidence if r.scores else 0),r.job_id))
    return run_key,results
