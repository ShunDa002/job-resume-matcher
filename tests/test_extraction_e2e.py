from pathlib import Path
from jobmatcher.db import init_db,upsert_job,get_jobs
from jobmatcher.normalize import normalize_job
from jobmatcher.extraction import extract

def test_extraction_cache_and_update(tmp_path):
 root=Path.cwd(); db=tmp_path/'x.db'; init_db(db)
 upsert_job(db,normalize_job({'source':'x','source_job_id':'1','title':'Senior AI Engineer','company':'A','location_country_code':'SG','description':'Requires 4+ years in AI ML engineering.'}))
 exe=str(root/'tests/fixtures/fake_agy.py')
 one=extract(str(db),root,5,False,exe); assert one['completed']==1 and not one['failed']
 job=get_jobs(db)[0]; assert job.minimum_experience_years==4 and job.career_level=='senior'
 two=extract(str(db),root,5,False,exe); assert two['cached']==1 and two['completed']==0
