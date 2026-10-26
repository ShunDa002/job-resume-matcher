import json
from dataclasses import dataclass
from pathlib import Path
from jobmatcher_resume.service import extract_candidate_from_resume
@dataclass
class Result: data:dict|None; errors:list
class FakeAdapter:
 def invoke(self,prompt,schema,audit):
  Path(audit).mkdir(parents=True,exist_ok=True)
  raw={'schema_version':'candidate-profile.v1','candidate_id':'candidate-001','citizenship_country_code':None,'residence_country_code':None,'has_target_country_work_rights':False,'target_employment_types':['full_time'],'career_level':'fresh_graduate','professional_experience_years':0,'degree_fields':['software_engineering'],'graduation_date':None,'skills':[{'skill_id':'python','category':'technical_skills','level':'substantial_project','evidence':['Python']}],'responsibilities':[],'domains':[],'soft_skills':[],'metadata':{}}
  return Result(raw,[])
def test_service(tmp_path):
 resume=tmp_path/'resume.txt'; resume.write_text('Python student in software engineering')
 root=Path.cwd(); cand,doc=extract_candidate_from_resume(resume_path=resume,candidate_id='candidate-001',adapter=FakeAdapter(),schema_path=root/'schemas/candidate-profile.schema.json',prompt_path=root/'prompts/extract-resume.v1.md',repair_prompt_path=root/'prompts/repair-resume.v1.md',audit_dir=tmp_path/'audit',overrides={'citizenship_country_code':'MY'})
 assert cand.citizenship_country_code=='MY' and cand.metadata['resume_source_format']=='txt'; assert (tmp_path/'audit/candidate-profile.json').exists()
