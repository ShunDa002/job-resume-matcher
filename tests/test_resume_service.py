import json
from pathlib import Path
from jobmatcher_resume.service import prepare_resume_extraction, validate_resume_extraction, ingest_resume_extraction

RAW = {'schema_version':'candidate-profile.v2','candidate_id':'candidate-001','citizenship_country_code':None,'residence_country_code':None,'has_target_country_work_rights':False,'target_employment_types':['full_time'],'career_level':'fresh_graduate','professional_experience_years':0,'degree_fields':['software_engineering'],'graduation_date':None,'skills':[{'skill_id':'python','category':'technical_skills','level':'substantial_project','evidence':['Python']}],'responsibilities':[],'domains':[],'soft_skills':[],'metadata':{}}

def _paths(root):
    return {
        'schema_path': root/'schemas/candidate-profile.schema.json',
        'prompt_path': root/'prompts/extract-resume.v2.md',
        'repair_prompt_path': root/'prompts/repair-resume.v1.md',
    }

def test_service(tmp_path):
    resume=tmp_path/'resume.txt'; resume.write_text('Python student in software engineering')
    root=Path.cwd()
    cand,doc=ingest_resume_extraction(resume_path=resume,candidate_id='candidate-001',extraction=RAW,audit_dir=tmp_path/'audit',overrides={'citizenship_country_code':'MY'},**_paths(root))
    assert cand.citizenship_country_code=='MY' and cand.metadata['resume_source_format']=='txt'; assert (tmp_path/'audit/candidate-profile.json').exists()

def test_currently_enrolled_defaults_false_and_override_sets_it(tmp_path):
    resume=tmp_path/'resume.txt'; resume.write_text('Python student in software engineering')
    root=Path.cwd()
    cand,doc=ingest_resume_extraction(resume_path=resume,candidate_id='candidate-001',extraction=RAW,audit_dir=tmp_path/'audit',overrides={'currently_enrolled':True},**_paths(root))
    assert cand.currently_enrolled is True
    cand2,doc2=ingest_resume_extraction(resume_path=resume,candidate_id='candidate-001',extraction=RAW,audit_dir=tmp_path/'audit2',overrides={},**_paths(root))
    assert cand2.currently_enrolled is False

def test_prepare_then_validate_with_repair(tmp_path):
    resume=tmp_path/'resume.txt'; resume.write_text('Python student in software engineering')
    root=Path.cwd()
    doc, prompt, audit = prepare_resume_extraction(resume_path=resume,candidate_id='candidate-001',audit_dir=tmp_path/'audit',overrides={},**_paths(root))
    assert (audit/'prompt.txt').exists() and (audit/'resume-text.txt').exists()
    assert (audit/'extraction.json').exists()
    # Bad evidence: 'Java' is not in the resume text.
    bad = json.loads(json.dumps(RAW)); bad['skills'][0]['evidence'] = ['Java']
    cand, errors = validate_resume_extraction(raw=bad,parsed_doc=doc,candidate_id='candidate-001',audit_dir=audit,repair_prompt_path=root/'prompts/repair-resume.v1.md')
    assert cand is None and errors
    assert (audit/'repair-prompt.txt').exists()
    # Muse fixes it; validation now passes.
    cand, errors = validate_resume_extraction(raw=RAW,parsed_doc=doc,candidate_id='candidate-001',audit_dir=audit,repair_prompt_path=root/'prompts/repair-resume.v1.md')
    assert cand is not None and not errors
    assert (audit/'candidate-profile.json').exists()
