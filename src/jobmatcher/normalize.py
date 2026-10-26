from __future__ import annotations
import re
from .models import JobRecord, Salary
from .util import normalize_text,extract_url,sha256_data,normalize_key

def parse_salary(value:str|None)->Salary:
    if not value or normalize_text(value).lower() in {"not disclosed","","n/a"}: return Salary()
    text=normalize_text(value)
    nums=[float(x.replace(",","")) for x in re.findall(r"(?:\$|sgd\s*)?([0-9][0-9,]*(?:\.[0-9]+)?)",text,re.I)]
    currency="SGD" if "$" in text or "sgd" in text.lower() else None
    period="month" if "month" in text.lower() else "year" if "year" in text.lower() else None
    return Salary(disclosed=bool(nums),currency=currency,period=period,minimum=nums[0] if nums else None,maximum=nums[1] if len(nums)>1 else (nums[0] if nums else None))

def normalize_job(raw:dict)->JobRecord:
    source=normalize_key(raw.get("source","unknown"))
    source_job_id=str(raw.get("source_job_id") or "").strip() or None
    url=extract_url(raw.get("source_url") or raw.get("joburl"))
    if not source_job_id and url:
        m=re.search(r"/job/(\d+)",url); source_job_id=m.group(1) if m else None
    title=normalize_text(raw.get("normalized_title") or raw.get("title") or "Untitled job")
    company=normalize_text(raw.get("normalized_company") or raw.get("company") or "Unknown company")
    description=normalize_text(raw.get("description") or "")
    job_id=f"{source}-{source_job_id}" if source_job_id else None
    payload={"source":source,"source_job_id":source_job_id,"title":title,"company":company,"description":description,"location":raw.get("location")}
    content_hash=sha256_data(payload)
    if not job_id: job_id="job-"+content_hash.split(":",1)[1][:20]
    data=dict(raw)
    allowed=set(JobRecord.model_fields)
    data={k:v for k,v in data.items() if k in allowed}
    data.update({"job_id":job_id,"source":source,"source_job_id":source_job_id,"source_url":url,"title":title,"company":company,"description":description,"content_hash":content_hash})
    if "salary" not in data or isinstance(data.get("salary"),str): data["salary"]=parse_salary(raw.get("salary"))
    return JobRecord.model_validate(data)
