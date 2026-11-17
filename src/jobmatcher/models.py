from __future__ import annotations
from datetime import date
from enum import StrEnum
from typing import Any, Literal
from pydantic import BaseModel, Field, ConfigDict

class EvidenceLevel(StrEnum):
    DEPLOYED_PROFESSIONAL="deployed_professional"
    DEPLOYED_PROJECT="deployed_project"
    SUBSTANTIAL_PROJECT="substantial_project"
    COURSEWORK="coursework"
    STATED_ONLY="stated_only"

class Necessity(StrEnum):
    REQUIRED="required"
    PREFERRED="preferred"

class Importance(StrEnum):
    CORE="core"
    SUPPORTING="supporting"

class EligibilityStatus(StrEnum):
    ELIGIBLE="ELIGIBLE"
    CONDITIONALLY_ELIGIBLE="CONDITIONALLY_ELIGIBLE"
    INSUFFICIENT_INFORMATION="INSUFFICIENT_INFORMATION"
    INELIGIBLE_WORK_AUTHORIZATION="INELIGIBLE_WORK_AUTHORIZATION"
    INELIGIBLE_EXPERIENCE="INELIGIBLE_EXPERIENCE"
    INELIGIBLE_SENIORITY="INELIGIBLE_SENIORITY"
    INELIGIBLE_CITIZENSHIP="INELIGIBLE_CITIZENSHIP"

class SkillEvidence(BaseModel):
    skill_id: str
    category: str="technical_skills"
    level: EvidenceLevel
    evidence: list[str]=Field(default_factory=list)

class CandidateProfile(BaseModel):
    model_config=ConfigDict(extra="forbid")
    schema_version: Literal["candidate-profile.v1"]="candidate-profile.v1"
    candidate_id: str
    citizenship_country_code: str|None=None
    residence_country_code: str|None=None
    has_target_country_work_rights: bool=False
    target_employment_types: list[str]=Field(default_factory=lambda:["full_time"])
    career_level: str="fresh_graduate"
    professional_experience_years: float=0
    degree_fields: list[str]=Field(default_factory=list)
    graduation_date: date|None=None
    skills: list[SkillEvidence]=Field(default_factory=list)
    responsibilities: list[SkillEvidence]=Field(default_factory=list)
    domains: list[SkillEvidence]=Field(default_factory=list)
    soft_skills: list[SkillEvidence]=Field(default_factory=list)
    metadata: dict[str,Any]=Field(default_factory=dict)

class Requirement(BaseModel):
    requirement_id: str
    canonical_value: str
    category: Literal["technical_skills","responsibility_alignment","education","domain","tools_deployment","soft_skills"]
    necessity: Necessity
    importance: Importance=Importance.SUPPORTING
    critical: bool=False
    minimum_years: float|None=None
    original_text: str
    alternatives: list[str]=Field(default_factory=list)

class Salary(BaseModel):
    disclosed: bool=False
    currency: str|None=None
    period: str|None=None
    minimum: float|None=None
    maximum: float|None=None

class JobRecord(BaseModel):
    model_config=ConfigDict(extra="forbid")
    schema_version: Literal["normalized-job.v1"]="normalized-job.v1"
    job_id: str|None=None
    source: str
    source_job_id: str|None=None
    source_url: str|None=None
    title: str
    company: str
    location_country_code: str
    location_text: str|None=None
    employment_type: str="full_time"
    description: str
    salary: Salary=Field(default_factory=Salary)
    minimum_experience_years: float|None=None
    experience_requirement_type: Literal["required","preferred","not_stated"]="not_stated"
    career_level: str="unspecified"
    required_citizenship_country_code: str|None=None
    sponsorship: Literal["available","not_available","unknown"]="unknown"
    degree_fields: list[str]=Field(default_factory=list)
    requirements: list[Requirement]=Field(default_factory=list)
    data_quality_flags: list[str]=Field(default_factory=list)
    content_hash: str|None=None

class EvidenceMatch(BaseModel):
    requirement_id: str
    requirement: str
    candidate_skill: str|None
    evidence_score: float=Field(ge=0,le=1)
    relation: str
    candidate_evidence: list[str]=Field(default_factory=list)

class MatchScores(BaseModel):
    technical_skills: float
    responsibility_alignment: float
    education: float
    career_level: float
    domain: float
    tools_deployment: float
    soft_skills: float
    pre_penalty_total: float
    penalty: float
    final_match_score: float
    assessment_confidence: float

class MatchResult(BaseModel):
    schema_version: Literal["match-result.v1"]="match-result.v1"
    candidate_id: str
    job_id: str
    eligibility_status: EligibilityStatus
    eligibility_reasons: list[str]
    work_authorization_risk: str
    scores: MatchScores|None
    evidence_matches: list[EvidenceMatch]=Field(default_factory=list)
    critical_gaps: list[str]=Field(default_factory=list)
    policy_versions: dict[str,str]
    # Evidence volume: how many requirements the score rests on.
    # thin_evidence (fewer than 5) means the score is a weak signal
    # even when it is high; see scoring-policy.v2 confidence.
    requirement_count: int=0
    thin_evidence: bool=False
