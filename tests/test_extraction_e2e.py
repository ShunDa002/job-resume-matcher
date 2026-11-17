import json
from pathlib import Path
from jobmatcher.db import init_db,upsert_job,get_jobs
from jobmatcher.normalize import normalize_job
from jobmatcher.extraction import prepare_extraction, apply_extraction
from tests.test_muse_extraction import _extraction

def test_extraction_cache_and_update(tmp_path):
    root=Path.cwd(); db=tmp_path/'x.db'; init_db(db)
    job=normalize_job({'source':'x','source_job_id':'1','title':'Senior AI Engineer','company':'A','location_country_code':'SG','description':'Requires 4+ years in AI ML engineering.'})
    upsert_job(db,job)
    prep=prepare_extraction(str(db),root,5,False)
    assert prep['total']==1 and prep['cached']==0
    bundle=Path(prep['batches'][0]['bundle'])
    (bundle/'extraction.json').write_text(json.dumps(_extraction([job])),encoding='utf-8')
    one=apply_extraction(str(db),root,prep['run_id']); assert one['completed']==[job.job_id] and not one['failed']
    stored=get_jobs(db)[0]; assert stored.minimum_experience_years==4 and stored.career_level=='senior'
    two=prepare_extraction(str(db),root,5,False); assert two['cached']==1 and two['batches']==[]
