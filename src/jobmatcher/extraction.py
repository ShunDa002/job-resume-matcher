import json
from pathlib import Path
from pydantic import ValidationError
from .adapters import AntigravityAdapter
from .config import load_yaml
from .db import connect,get_jobs,upsert_job
from .models import Requirement
from .extraction_models import ExtractionResult
from .util import sha256_data
DDL='CREATE TABLE IF NOT EXISTS extraction_cache(task_key TEXT PRIMARY KEY,job_id TEXT,payload TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP)'
def render(path,inp,errors=None,invalid=None): return Path(path).read_text().replace('{{INPUT_JSON}}',json.dumps(inp,indent=2)).replace('{{VALIDATION_ERRORS}}',json.dumps(errors or [])).replace('{{INVALID_OUTPUT}}',json.dumps(invalid))
def verify(x,inputs):
 exp={j['job_id']:j for j in inputs}; errs=[]
 if sorted(exp)!=sorted(j.job_id for j in x.jobs): errs.append('job_id_set_mismatch')
 for j in x.jobs:
  d=exp.get(j.job_id,{}).get('description','')
  if j.citizenship.evidence_text and j.citizenship.evidence_text not in d: errs.append(f'{j.job_id}:bad_citizenship_evidence')
  for r in j.requirements:
   if r.original_text not in d: errs.append(f'{j.job_id}:{r.requirement_id}:bad_evidence')
 return errs
def extract(db,workspace,batch_size=5,force=False,executable=None,adapter='antigravity'):
 w=Path(workspace)
 from .adapters import get_adapter
 a=get_adapter(adapter,w,executable)
 probe=a.probe()
 if not probe['ok']: raise RuntimeError(f'{adapter} probe failed: {probe}')
 schema=w/'schemas/extraction-result.schema.json'; ph=sha256_data((w/'prompts/extract-requirements.v1.md').read_text()); sh=sha256_data(json.loads(schema.read_text())); ch=sha256_data(a.c)
 with connect(db) as c: c.execute(DDL)
 pending=[]; cached=0
 for j in get_jobs(db):
  key=sha256_data({'job':j.content_hash,'prompt':ph,'schema':sh,'config':ch})
  with connect(db) as c: row=c.execute('SELECT 1 FROM extraction_cache WHERE task_key=?',(key,)).fetchone()
  if row and not force: cached+=1
  else: pending.append((j,key))
 completed=0; failed=[]
 for n in range(0,len(pending),batch_size):
  chunk=pending[n:n+batch_size]; inp={'schema_version':'extraction-input.v1','jobs':[{'job_id':j.job_id,'title':j.title,'company':j.company,'description':j.description} for j,_ in chunk]}; base=w/'data/output/extraction-audit'/f'batch-{n//batch_size:06d}'; base.mkdir(parents=True,exist_ok=True); (base/'input.json').write_text(json.dumps(inp,indent=2))
  raw,errs=a.invoke(render(w/'prompts/extract-requirements.v1.md',inp),schema,base/'attempt-1'); parsed=None
  if raw:
   try: parsed=ExtractionResult.model_validate(raw); errs=verify(parsed,inp['jobs'])
   except ValidationError as e: errs=e.errors(include_url=False)
  if errs:
   raw,errs2=a.invoke(render(w/'prompts/repair-extraction.v1.md',inp,errs,raw),schema,base/'attempt-2'); errs=errs2
   if raw:
    try: parsed=ExtractionResult.model_validate(raw); errs=verify(parsed,inp['jobs'])
    except ValidationError as e: errs=e.errors(include_url=False)
  (base/'validation.json').write_text(json.dumps({'valid':not errs,'errors':errs},indent=2))
  if errs or not parsed: failed += [j.job_id for j,_ in chunk]; continue
  facts={x.job_id:x for x in parsed.jobs}
  for j,key in chunk:
   f=facts[j.job_id]; j.title=f.normalized_title or j.title; j.company=f.normalized_company or j.company; j.minimum_experience_years=f.minimum_experience_years; j.experience_requirement_type=f.experience_requirement_type; j.career_level=f.career_level; j.required_citizenship_country_code=f.citizenship.country_code if f.citizenship.requirement=='explicit' else None; j.sponsorship=f.work_authorization.sponsorship; j.degree_fields=f.degree_fields; j.requirements=[Requirement.model_validate(r.model_dump()) for r in f.requirements]; upsert_job(db,j)
   with connect(db) as c: c.execute('INSERT OR REPLACE INTO extraction_cache(task_key,job_id,payload) VALUES(?,?,?)',(key,j.job_id,json.dumps(f.model_dump(mode='json'))))
   completed+=1
 return {'probe':probe,'total':len(get_jobs(db)),'cached':cached,'completed':completed,'failed':failed}
