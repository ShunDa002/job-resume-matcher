"""Muse-native resume extraction.

Replaces the old adapter flow. There is no subprocess adapter, no API
key, and no model call in this code. The extractor is Muse, in the loop:

1. ``prepare_resume_extraction`` parses the resume locally and writes
   a bundle (``prompt.txt``, ``resume-text.txt``, ``parsed-resume.json``,
   ``schema.json``, empty ``extraction.json``) into the audit dir.
2. Muse reads the bundle, extracts a candidate profile using only the
   resume text, and writes one JSON object matching the
   candidate-profile schema into ``extraction.json``.
3. ``validate_resume_extraction`` checks it with Pydantic + exact
   substring evidence checks, applies operator overrides, and on
   success writes ``candidate-profile.json``. On failure it writes
   ``repair-prompt.txt`` and returns the errors, so Muse can fix
   ``extraction.json`` and the caller can validate again.

``ingest_resume_extraction`` is the one-call form used by the CLI and
tests when Muse has already supplied the extraction dict.
"""
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

def prepare_resume_extraction(*,resume_path,candidate_id,schema_path,prompt_path,repair_prompt_path,audit_dir,overrides=None,parser=None):
    """Parse locally and write the Muse prompt bundle. Returns (parsed_doc, prompt, audit_dir)."""
    overrides=overrides or {}; parser=parser or ResumeDocumentParser(); parsed_doc=parser.parse(resume_path)
    audit=Path(audit_dir); audit.mkdir(parents=True,exist_ok=True)
    (audit/'parsed-resume.json').write_text(json.dumps(parsed_doc.to_dict(),ensure_ascii=False,indent=2),encoding='utf-8')
    (audit/'resume-text.txt').write_text(parsed_doc.text,encoding='utf-8')
    (audit/'schema.json').write_text(Path(schema_path).read_text(encoding='utf-8'),encoding='utf-8')
    values={'CANDIDATE_ID':candidate_id,'OPERATOR_OVERRIDES':overrides,'RESUME_TEXT':parsed_doc.text,'VALIDATION_ERRORS':[],'INVALID_OUTPUT':None}
    prompt=_render(prompt_path,values)
    (audit/'prompt.txt').write_text(prompt,encoding='utf-8')
    # Placeholder for Muse to fill in.
    (audit/'extraction.json').write_text('',encoding='utf-8')
    (audit/'status.json').write_text(json.dumps({'status':'awaiting_muse','candidate_id':candidate_id},ensure_ascii=False,indent=2),encoding='utf-8')
    return parsed_doc, prompt, audit

def validate_resume_extraction(*,raw,parsed_doc,candidate_id,overrides=None,audit_dir,repair_prompt_path=None):
    """Validate Muse-supplied raw JSON. Returns (candidate_or_None, errors).

    On success the candidate (with overrides applied) is returned and
    ``candidate-profile.json`` / ``validation.json`` are written. On
    failure a repair prompt is written when ``repair_prompt_path`` is
    given, so Muse can correct ``extraction.json`` and retry.
    """
    overrides=overrides or {}; audit=Path(audit_dir); candidate=None; errors=[]
    if raw is not None:
        try:
            candidate=CandidateExtractionResult.model_validate(raw)
            errors=_verify(candidate,parsed_doc.text,overrides)
        except ValidationError as e:
            errors=e.errors(include_url=False)
    else:
        errors=['empty_response']
    if candidate and not errors:
        data=candidate.model_dump(mode='json')
        for k,v in overrides.items():
            if k in data: data[k]=v
        data['metadata']={**data.get('metadata',{}),'resume_source_format':parsed_doc.source_format,'resume_content_hash':parsed_doc.content_hash,'resume_extraction_method':parsed_doc.extraction_method}
        candidate=CandidateExtractionResult.model_validate(data)
        (audit/'candidate-profile.json').write_text(json.dumps(candidate.model_dump(mode='json'),ensure_ascii=False,indent=2),encoding='utf-8')
        (audit/'status.json').write_text(json.dumps({'status':'completed','candidate_id':candidate_id},ensure_ascii=False,indent=2),encoding='utf-8')
    else:
        if repair_prompt_path is not None:
            values={'CANDIDATE_ID':candidate_id,'OPERATOR_OVERRIDES':overrides,'RESUME_TEXT':parsed_doc.text,'VALIDATION_ERRORS':errors,'INVALID_OUTPUT':raw}
            (audit/'repair-prompt.txt').write_text(_render(repair_prompt_path,values),encoding='utf-8')
        (audit/'status.json').write_text(json.dumps({'status':'needs_repair','candidate_id':candidate_id,'errors':errors},ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    (audit/'validation.json').write_text(json.dumps({'valid':bool(candidate and not errors),'errors':errors},ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    return (candidate if not errors else None), errors

def ingest_resume_extraction(*,resume_path,candidate_id,extraction,schema_path,prompt_path,repair_prompt_path,audit_dir,overrides=None,parser=None):
    """Prepare the bundle, then validate Muse's supplied extraction dict.

    Raises RuntimeError with the validation errors when invalid, so the
    caller can read ``repair-prompt.txt``, have Muse fix the JSON, and
    call ``validate_resume_extraction`` again with the corrected dict.
    """
    parsed_doc, _prompt, audit = prepare_resume_extraction(
        resume_path=resume_path, candidate_id=candidate_id,
        schema_path=schema_path, prompt_path=prompt_path,
        repair_prompt_path=repair_prompt_path, audit_dir=audit_dir,
        overrides=overrides, parser=parser)
    candidate, errors = validate_resume_extraction(
        raw=extraction, parsed_doc=parsed_doc, candidate_id=candidate_id,
        overrides=overrides or {}, audit_dir=audit,
        repair_prompt_path=repair_prompt_path)
    if errors or not candidate:
        raise RuntimeError(f'Resume Muse extraction failed: {errors}')
    return candidate, parsed_doc

# Backwards-compatible alias: the old name took an adapter; it no
# longer does. Callers must now pass ``extraction=`` (Muse's JSON).
def extract_candidate_from_resume(*,resume_path,candidate_id,extraction,schema_path,prompt_path,repair_prompt_path,audit_dir,overrides=None,parser=None):
    return ingest_resume_extraction(
        resume_path=resume_path, candidate_id=candidate_id, extraction=extraction,
        schema_path=schema_path, prompt_path=prompt_path,
        repair_prompt_path=repair_prompt_path, audit_dir=audit_dir,
        overrides=overrides, parser=parser)
