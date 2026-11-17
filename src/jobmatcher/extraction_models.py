from typing import Literal
from pydantic import BaseModel,ConfigDict,Field
from .models import Importance,Necessity
class XReq(BaseModel):
 model_config=ConfigDict(extra='forbid'); requirement_id:str; canonical_value:str; category:Literal['technical_skills','responsibility_alignment','education','domain','tools_deployment','soft_skills']; necessity:Necessity; importance:Importance; critical:bool=False; minimum_years:float|None=None; original_text:str; alternatives:list[str]=Field(default_factory=list)
class Citizenship(BaseModel):
 model_config=ConfigDict(extra='forbid'); requirement:Literal['explicit','not_stated']; country_code:str|None=None; evidence_text:str|None=None
class WorkAuth(BaseModel):
 model_config=ConfigDict(extra='forbid'); sponsorship:Literal['available','not_available','unknown']; evidence_text:str|None=None
class XJob(BaseModel):
 model_config=ConfigDict(extra='forbid'); job_id:str; normalized_title:str|None=None; normalized_company:str|None=None; minimum_experience_years:float|None=None; experience_requirement_type:Literal['required','preferred','not_stated']; career_level:Literal['entry_level','unspecified','senior','lead','manager','senior_manager','director','head','executive']; citizenship:Citizenship; work_authorization:WorkAuth; degree_fields:list[str]=Field(default_factory=list); requirements:list[XReq]=Field(default_factory=list); warnings:list[str]=Field(default_factory=list)
class ExtractionResult(BaseModel):
 model_config=ConfigDict(extra='forbid'); schema_version:Literal['extraction-result.v1']='extraction-result.v1'; jobs:list[XJob]
