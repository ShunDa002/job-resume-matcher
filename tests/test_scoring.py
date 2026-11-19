import json
from pathlib import Path
from jobmatcher.models import CandidateProfile,JobRecord,Requirement
from jobmatcher.normalize import normalize_job
from jobmatcher.config import load_yaml,default_config
from jobmatcher.eligibility import determine_eligibility
from jobmatcher.scoring import score_job

def _policies():
    ep=load_yaml(default_config("eligibility-policy.v2.yaml")); sp=load_yaml(default_config("scoring-policy.v3.yaml")); tx=load_yaml(default_config("skill-taxonomy.v2.yaml"))
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

def _candidate(skills=(),degree_fields=()):
    return CandidateProfile(candidate_id="test-cand",citizenship_country_code="SG",degree_fields=list(degree_fields),skills=[{"skill_id":s,"level":lv,"evidence":[f"{s} evidence"]} for s,lv in skills])

def _req(rid,value,category="technical_skills",alternatives=()):
    return Requirement(requirement_id=rid,canonical_value=value,category=category,necessity="required",importance="core",original_text=value,alternatives=list(alternatives))

def _match_one(candidate,req,job_degree_fields=()):
    j=JobRecord(job_id="test-job",source="x",title="x",company="x",location_country_code="SG",description="x",degree_fields=list(job_degree_fields),requirements=[req])
    ep,sp,tx=_policies()
    versions={"eligibility":ep["version"],"scoring":sp["version"],"taxonomy":tx["version"]}
    status,reasons,risk=determine_eligibility(candidate,j,ep)
    return score_job(candidate,j,status,reasons,risk,sp,tx,versions).evidence_matches[0]

def test_degree_requirement_matches_candidate_degree():
    # Demo candidate holds a software_engineering degree.
    c=CandidateProfile.model_validate_json(Path("examples/candidate.json").read_text())
    m=_match_one(c,_req("r1","degree","education",["computer_science","software_engineering"]),["computer_science","software_engineering"])
    assert m.evidence_score==1.0 and m.candidate_skill=="software_engineering" and m.relation=="exact_or_alias"

def test_bachelors_degree_requirement_matches():
    c=CandidateProfile.model_validate_json(Path("examples/candidate.json").read_text())
    m=_match_one(c,_req("r1","bachelors_degree","education",["software_engineering"]))
    assert m.evidence_score==1.0

def test_computer_science_field_requirement_matches_degree():
    # Demo candidate holds software_engineering, not computer_science:
    # a closely related computing field, so 0.9, not a full 1.0.
    c=CandidateProfile.model_validate_json(Path("examples/candidate.json").read_text())
    m=_match_one(c,_req("r1","computer_science","education",["computer_science","engineering"]))
    assert m.evidence_score==0.9 and m.candidate_skill=="software_engineering" and m.relation=="transferable"

def test_software_engineering_skill_not_matched_via_degree():
    # "Build ... using software engineering" is a skill requirement,
    # not the degree: the degree must not evidence it at 1.0.
    c=_candidate([("python","deployed_project")],degree_fields=["software_engineering"])
    m=_match_one(c,_req("r1","software_engineering","technical_skills"))
    assert m.evidence_score==0.0 and m.relation=="absent"

def test_software_engineering_degree_requirement_matches():
    c=_candidate([("python","deployed_project")],degree_fields=["software_engineering"])
    m=_match_one(c,_req("r1","software_engineering","education",["software_engineering"]))
    assert m.evidence_score==1.0 and m.candidate_skill=="software_engineering"

def test_masters_degree_not_matched_without_degree_level():
    # The profile stores degree fields, not the degree level, so a
    # masters-only requirement must not be guessed as satisfied.
    c=CandidateProfile.model_validate_json(Path("examples/candidate.json").read_text())
    m=_match_one(c,_req("r1","masters_degree","education",["computer_science","software_engineering"]))
    assert m.evidence_score==0.0 and m.relation=="absent"

def test_databases_requirement_matches_sqlite():
    c=_candidate([("sqlite","deployed_project"),("chroma","deployed_project")])
    m=_match_one(c,_req("r1","databases","technical_skills",["mysql","postgresql","redis","mongodb"]))
    assert m.evidence_score==0.81 and m.candidate_skill=="sqlite" and m.relation=="transferable"

def test_sql_requirement_matches_sqlite():
    c=_candidate([("sqlite","deployed_project")])
    m=_match_one(c,_req("r1","sql","technical_skills"))
    assert m.evidence_score==0.81 and m.candidate_skill=="sqlite"

def test_api_requirement_matches_fastapi():
    c=_candidate([("fastapi","deployed_project")])
    m=_match_one(c,_req("r1","api","technical_skills"))
    assert m.evidence_score==0.72 and m.candidate_skill=="fastapi" and m.relation=="transferable"

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
