from __future__ import annotations
from datetime import date
from typing import Literal, Any
from pydantic import BaseModel, ConfigDict, Field, model_validator

EvidenceLevel=Literal['deployed_professional','deployed_project','substantial_project','coursework','stated_only']
Category=Literal['technical_skills','responsibility_alignment','education','domain','tools_deployment','soft_skills']

class SkillEvidence(BaseModel):
    model_config=ConfigDict(extra='forbid')
    skill_id:str
    category:Category
    level:EvidenceLevel
    evidence:list[str]=Field(min_length=1)

class CandidateExtractionResult(BaseModel):
    model_config=ConfigDict(extra='forbid')
    schema_version:Literal['candidate-profile.v2']='candidate-profile.v2'
    candidate_id:str
    citizenship_country_code:str|None=None
    residence_country_code:str|None=None
    has_target_country_work_rights:bool=False
    target_employment_types:list[str]=Field(default_factory=lambda:['full_time'])
    career_level:Literal['student','fresh_graduate','junior','mid','senior','manager','unknown']='unknown'
    professional_experience_years:float=Field(default=0,ge=0)
    # True only when the resume explicitly states current enrollment or
    # a future expected graduation; false when graduated. May also be
    # set by operator override.
    currently_enrolled:bool=False
    degree_fields:list[str]=Field(default_factory=list)
    graduation_date:date|None=None
    skills:list[SkillEvidence]=Field(default_factory=list)
    responsibilities:list[SkillEvidence]=Field(default_factory=list)
    domains:list[SkillEvidence]=Field(default_factory=list)
    soft_skills:list[SkillEvidence]=Field(default_factory=list)
    metadata:dict[str,Any]=Field(default_factory=dict)

    @model_validator(mode='after')
    def no_duplicate_skill_entries(self):
        for field in ('skills','responsibilities','domains','soft_skills'):
            vals=getattr(self,field); keys=[(x.skill_id,x.category) for x in vals]
            if len(keys)!=len(set(keys)): raise ValueError(f'duplicate skill/category entries in {field}')
        return self
