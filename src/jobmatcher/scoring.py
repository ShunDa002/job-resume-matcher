from __future__ import annotations
from .models import *
from .util import decimal_round,normalize_key

CATS=["technical_skills","responsibility_alignment","education","domain","tools_deployment","soft_skills"]

def _taxonomy_maps(taxonomy):
    aliases={}; related={}
    for sid,info in taxonomy.get("skills",{}).items():
        aliases[normalize_key(sid)]=sid
        for a in info.get("aliases",[]): aliases[normalize_key(a)]=sid
        for other,strength in info.get("related",{}).items(): related[(sid,other)]=float(strength); related[(other,sid)]=float(strength)
    return aliases,related

def _candidate_evidence(candidate):
    out=[]
    for attr in ("skills","responsibilities","domains","soft_skills"):
        out.extend(getattr(candidate,attr))
    return out

def _match_requirement(req,candidate,policy,taxonomy):
    aliases,related=_taxonomy_maps(taxonomy); evidence=_candidate_evidence(candidate)
    targets=[req.canonical_value]+req.alternatives
    target_ids=[aliases.get(normalize_key(x),normalize_key(x)) for x in targets]
    best=None; best_score=0.; relation="absent"
    base=policy["evidence_scores"]
    for ev in evidence:
        eid=aliases.get(normalize_key(ev.skill_id),normalize_key(ev.skill_id))
        level_score=float(base[ev.level.value])
        if eid in target_ids: score=level_score; rel="exact_or_alias"
        else:
            strengths=[related.get((eid,t),0) for t in target_ids]
            strength=max(strengths or [0]); score=level_score*strength; rel="transferable" if strength else "absent"
        if score>best_score: best,best_score,relation=ev,score,rel
    return EvidenceMatch(requirement_id=req.requirement_id,requirement=req.canonical_value,candidate_skill=best.skill_id if best else None,evidence_score=decimal_round(best_score),relation=relation,candidate_evidence=best.evidence if best else [])

def _category_score(reqs,matches,policy,cat):
    selected=[r for r in reqs if r.category==cat]
    if not selected: return 100.0
    num=den=0.
    for r in selected:
        key="preferred" if r.necessity==Necessity.PREFERRED else ("required_core" if r.importance==Importance.CORE else "required_supporting")
        w=float(policy["requirement_weights"][key]); m=next(x for x in matches if x.requirement_id==r.requirement_id)
        num+=w*m.evidence_score; den+=w
    return decimal_round(100*num/den if den else 100)

def _education_score(candidate,job):
    if not job.degree_fields: return 100.0
    c={normalize_key(x) for x in candidate.degree_fields}; j={normalize_key(x) for x in job.degree_fields}
    if c&j: return 100.0
    computing={"computer_science","software_engineering","information_systems","artificial_intelligence","data_science"}
    return 90.0 if c&computing and j&computing else 50.0

def _career_score(candidate,job):
    if job.career_level in {"entry","entry_level","fresh_graduate","unspecified"}: return 100.0 if not job.minimum_experience_years else max(0.,100-25*job.minimum_experience_years)
    return 20.0

def score_job(candidate,job,eligibility,reasons,risk,score_policy,taxonomy,versions):
    n_req=len(job.requirements)
    thin=n_req<5
    hard={EligibilityStatus.INELIGIBLE_CITIZENSHIP,EligibilityStatus.INELIGIBLE_EXPERIENCE,EligibilityStatus.INELIGIBLE_SENIORITY,EligibilityStatus.INELIGIBLE_WORK_AUTHORIZATION,EligibilityStatus.INSUFFICIENT_INFORMATION}
    if eligibility in hard:
        return MatchResult(candidate_id=candidate.candidate_id,job_id=job.job_id,eligibility_status=eligibility,eligibility_reasons=reasons,work_authorization_risk=risk,scores=None,policy_versions=versions,requirement_count=n_req,thin_evidence=thin)
    matches=[_match_requirement(r,candidate,score_policy,taxonomy) for r in job.requirements]
    vals={c:_category_score(job.requirements,matches,score_policy,c) for c in CATS}
    vals["education"]=_education_score(candidate,job); vals["career_level"]=_career_score(candidate,job)
    weighted=sum(vals[k]*float(score_policy["category_weights"][k]) for k in score_policy["category_weights"])
    critical=[r.canonical_value for r in job.requirements if r.critical and next(m for m in matches if m.requirement_id==r.requirement_id).evidence_score<0.4]
    n=len(critical); p=score_policy["critical_gap_penalties"]
    penalty=float(p["one"] if n==1 else p["two"] if n==2 else 0)
    final=max(0,weighted-penalty)
    if n>=3: final=min(final,float(p["three_or_more_score_cap"]))
    # Confidence scales with evidence volume: a score averaged over 3
    # requirements is far less trustworthy than one over 8+. The
    # deductions below match scoring-policy.v2 `confidence`.
    conf=score_policy.get("confidence",{})
    base=float(conf.get("base",90.0)); full=int(conf.get("full_evidence_requirements",8))
    confidence=base*min(1.0,n_req/full) if full else base
    if job.data_quality_flags: confidence-=min(float(conf.get("data_quality_flag_cap",20)),float(conf.get("data_quality_flag_penalty",5))*len(job.data_quality_flags))
    if job.sponsorship=="unknown" and job.location_country_code!=candidate.citizenship_country_code: confidence-=float(conf.get("unknown_sponsorship_penalty",5))
    scores=MatchScores(**{k:decimal_round(vals[k]) for k in CATS},career_level=decimal_round(vals["career_level"]),pre_penalty_total=decimal_round(weighted),penalty=decimal_round(penalty),final_match_score=decimal_round(final),assessment_confidence=decimal_round(max(0,confidence)))
    return MatchResult(candidate_id=candidate.candidate_id,job_id=job.job_id,eligibility_status=eligibility,eligibility_reasons=reasons,work_authorization_risk=risk,scores=scores,evidence_matches=matches,critical_gaps=critical,policy_versions=versions,requirement_count=n_req,thin_evidence=thin)
