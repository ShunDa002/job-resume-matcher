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

# Degree requirements: a requirement such as "degree",
# "bachelors_degree", or "computer_science" (education category) is
# about the candidate's degree, not a skill, so it is matched against
# candidate.degree_fields instead of the skill taxonomy. The profile
# stores degree fields but no degree level, so a requirement that only
# a higher degree satisfies (masters / PhD) is reported absent rather
# than guessed. A "currently pursuing" marker is treated as satisfied
# by holding the degree in that field.
_DEGREE_MARKERS={"degree","diploma","bachelor","bachelors","undergraduate","bsc","bs","beng","ba","master","masters","msc","ms","meng","mba","phd","doctorate","doctoral","postgraduate","advanced","matriculated","studying","pursuing"}
_BACHELOR_TOKENS={"bachelor","bachelors","undergraduate","bsc","bs","beng","ba"}
_HIGHER_TOKENS={"master","masters","msc","ms","meng","mba","phd","doctorate","doctoral","postgraduate","advanced"}
_DEGREE_FIELDS={"computer_science","software_engineering","information_systems","artificial_intelligence","data_science","computer_engineering","information_technology","electrical_engineering","electronics_engineering","mechanical_engineering","chemical_engineering","civil_engineering","mathematics","applied_mathematics","engineering","network_engineering","information_security","architecture"}
_COMPUTING_FIELDS={"computer_science","software_engineering","information_systems","artificial_intelligence","data_science"}

def _match_degree_requirement(req,candidate,job_degree_fields):
    key=normalize_key(req.canonical_value); tokens=set(key.split("_"))
    # A bare field name ("software_engineering", "computer_science") is
    # only a degree requirement in the education category. Outside it
    # the same words mean the practice ("build ... using software
    # engineering"), which a degree alone does not evidence at 1.0.
    # A generic degree value ("degree", "bachelors_degree") is a degree
    # requirement in any category.
    if req.category=="education":
        if not (tokens&_DEGREE_MARKERS or key in _DEGREE_FIELDS): return None
    elif not tokens&_DEGREE_MARKERS:
        return None
    def absent(): return EvidenceMatch(requirement_id=req.requirement_id,requirement=req.canonical_value,candidate_skill=None,evidence_score=0.0,relation="absent",candidate_evidence=[])
    if tokens&_HIGHER_TOKENS and not tokens&_BACHELOR_TOKENS: return absent()
    fields={f for f in [key]+list(req.alternatives) if f in _DEGREE_FIELDS}
    fields|={f for f in _DEGREE_FIELDS if f in key}
    fields|={normalize_key(f) for f in (job_degree_fields or []) if normalize_key(f) in _DEGREE_FIELDS}
    c={normalize_key(x) for x in candidate.degree_fields}
    if not c: return absent()
    hit=c&fields
    if hit:
        field=sorted(hit)[0]
        return EvidenceMatch(requirement_id=req.requirement_id,requirement=req.canonical_value,candidate_skill=field,evidence_score=1.0,relation="exact_or_alias",candidate_evidence=[f"Degree in {field}"])
    if not fields:
        field=sorted(c)[0]
        return EvidenceMatch(requirement_id=req.requirement_id,requirement=req.canonical_value,candidate_skill=field,evidence_score=1.0,relation="exact_or_alias",candidate_evidence=[f"Degree in {field}"])
    if c&_COMPUTING_FIELDS and fields&_COMPUTING_FIELDS:
        field=sorted(c&_COMPUTING_FIELDS)[0]
        return EvidenceMatch(requirement_id=req.requirement_id,requirement=req.canonical_value,candidate_skill=field,evidence_score=0.9,relation="transferable",candidate_evidence=[f"Degree in {field}"])
    field=sorted(c)[0]
    return EvidenceMatch(requirement_id=req.requirement_id,requirement=req.canonical_value,candidate_skill=field,evidence_score=0.5,relation="transferable",candidate_evidence=[f"Degree in {field}"])

def _match_requirement(req,candidate,policy,taxonomy,job_degree_fields=None):
    degree_match=_match_degree_requirement(req,candidate,job_degree_fields)
    if degree_match is not None: return degree_match
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
    matches=[_match_requirement(r,candidate,score_policy,taxonomy,job.degree_fields) for r in job.requirements]
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
