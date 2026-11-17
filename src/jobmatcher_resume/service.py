from __future__ import annotations
import json
from pathlib import Path
from pydantic import ValidationError
from .document_parser import ResumeDocumentParser
from .models import CandidateExtractionResult

def _render(path,values):
    text=Path(path).read_text(encoding='utf-8')
    for key,value in values.items(): text=text.replace('{{'+key+'}}',value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,indent=2,default=str))
    return text

def _verify(candidate,source_text,overrides):
    errors=[]
    for field in ('skills','responsibilities','domains','soft_skills'):
        for item in getattr(candidate,field):
            for ev in item.evidence:
                if ev not in source_text: errors.append({'field':field,'skill_id':item.skill_id,'error':'evidence_not_exact_substring','evidence':ev})
    if not overrides.get('citizenship_country_code') and candidate.citizenship_country_code:
        code=candidate.citizenship_country_code
        if code not in source_text: errors.append({'field':'citizenship_country_code','error':'unsupported_without_override'})
    return errors

def _unpack(res):
    if isinstance(res, tuple) and len(res) == 2:
        return res[0], list(res[1] or [])
    return getattr(res, 'data', None), list(getattr(res, 'errors', []) or [])

def extract_candidate_from_resume(*,resume_path,candidate_id,adapter,schema_path,prompt_path,repair_prompt_path,audit_dir,overrides=None,parser=None):
    overrides=overrides or {}; parser=parser or ResumeDocumentParser(); parsed_doc=parser.parse(resume_path)
    audit=Path(audit_dir); audit.mkdir(parents=True,exist_ok=True)
    (audit/'parsed-resume.json').write_text(json.dumps(parsed_doc.to_dict(),ensure_ascii=False,indent=2),encoding='utf-8')
    (audit/'resume-text.txt').write_text(parsed_doc.text,encoding='utf-8')
    values={'CANDIDATE_ID':candidate_id,'OPERATOR_OVERRIDES':overrides,'RESUME_TEXT':parsed_doc.text,'VALIDATION_ERRORS':[],'INVALID_OUTPUT':None}
    prompt=_render(prompt_path,values)
    result=adapter.invoke(prompt,Path(schema_path),audit/'attempt-1')
    raw, errors = _unpack(result); candidate=None
    if raw is not None:
        try: candidate=CandidateExtractionResult.model_validate(raw); errors=_verify(candidate,parsed_doc.text,overrides)
        except ValidationError as e: errors=e.errors(include_url=False)
    if errors:
        values['VALIDATION_ERRORS']=errors; values['INVALID_OUTPUT']=raw
        repair=_render(repair_prompt_path,values); result=adapter.invoke(repair,Path(schema_path),audit/'attempt-2')
        raw, errors = _unpack(result)
        if raw is not None:
            try: candidate=CandidateExtractionResult.model_validate(raw); errors=_verify(candidate,parsed_doc.text,overrides)
            except ValidationError as e: errors=e.errors(include_url=False)
    if candidate and not errors:
        data=candidate.model_dump(mode='json')
        for k,v in overrides.items():
            if k in data: data[k]=v
        data['metadata']={**data.get('metadata',{}),'resume_source_format':parsed_doc.source_format,'resume_content_hash':parsed_doc.content_hash,'resume_extraction_method':parsed_doc.extraction_method}
        candidate=CandidateExtractionResult.model_validate(data)
        (audit/'candidate-profile.json').write_text(json.dumps(candidate.model_dump(mode='json'),ensure_ascii=False,indent=2),encoding='utf-8')
    (audit/'validation.json').write_text(json.dumps({'valid':bool(candidate and not errors),'errors':errors},ensure_ascii=False,indent=2),encoding='utf-8')
    if errors or not candidate: raise RuntimeError(f'Resume AI extraction failed after repair: {errors}')
    return candidate,parsed_doc
