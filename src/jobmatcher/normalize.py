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
    url=extract_url(raw.get("source_url") or raw.get("job_url") or raw.get("joburl"))
    raw_source=raw.get("source")
    if not raw_source:
        if url and "sg.jobstreet.com" in url:
            raw_source="jobstreet_sg"
        elif url and "jobstreet.com" in url:
            raw_source="jobstreet"
        else:
            raw_source="unknown"
    source=normalize_key(raw_source)
    source_job_id=str(raw.get("source_job_id") or "").strip() or None
    if not source_job_id and url:
        m=re.search(r"/job/(\d+)",url); source_job_id=m.group(1) if m else None
    title=normalize_text(raw.get("normalized_title") or raw.get("title") or "Untitled job")
    company=normalize_text(raw.get("normalized_company") or raw.get("company") or "Unknown company")
    description=normalize_text(raw.get("description") or "")
    job_id=f"{source}-{source_job_id}" if source_job_id else None
    location_text=normalize_text(raw.get("location_text") or raw.get("location") or "") or None
    country=raw.get("location_country_code")
    if country:
        country=normalize_text(country).upper()
    else:
        combined=f"{location_text or ''} {url or ''} {source}".lower()
        if any(k in combined for k in (
            "singapore","sg.jobstreet","_sg",".sg",
            "west region","central region","east region","north region","north-east region",
            "tuas","jurong","raffles place","bukit batok","pasir panjang",
            "rochor","marine parade","toa payoh","kaki bukit","chinatown","braddell"
        )):
            country="SG"
        elif any(k in combined for k in ("malaysia","my.jobstreet","_my",".my","kuala lumpur","johor","penang","selangor")):
            country="MY"
        else:
            country="SG"
    emp_type=normalize_key(raw.get("employment_type") or raw.get("work_type") or "full_time")
    payload={"source":source,"source_job_id":source_job_id,"title":title,"company":company,"description":description,"location":location_text or raw.get("location")}
    content_hash=sha256_data(payload)
    if not job_id: job_id="job-"+content_hash.split(":",1)[1][:20]
    data=dict(raw)
    allowed=set(JobRecord.model_fields)
    data={k:v for k,v in data.items() if k in allowed}
    data.update({
        "job_id":job_id,
        "source":source,
        "source_job_id":source_job_id,
        "source_url":url,
        "title":title,
        "company":company,
        "description":description,
        "location_country_code":country,
        "location_text":location_text,
        "employment_type":emp_type,
        "content_hash":content_hash,
    })
    if "salary" not in data or isinstance(data.get("salary"),(str,type(None))):
        data["salary"]=parse_salary(raw.get("salary"))
    elif isinstance(data.get("salary"),dict):
        data["salary"]=Salary.model_validate(data["salary"])
    return JobRecord.model_validate(data)
