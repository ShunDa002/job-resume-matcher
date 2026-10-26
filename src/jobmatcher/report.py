import csv,json
from pathlib import Path

def write_report(results,output):
    p=Path(output); p.parent.mkdir(parents=True,exist_ok=True)
    if p.suffix.lower()==".csv":
        with p.open("w",newline="",encoding="utf-8") as f:
            w=csv.DictWriter(f,fieldnames=["rank","job_id","eligibility_status","final_match_score","assessment_confidence","critical_gaps","eligibility_reasons"]); w.writeheader()
            for i,r in enumerate(results,1): w.writerow({"rank":i,"job_id":r.job_id,"eligibility_status":r.eligibility_status.value,"final_match_score":r.scores.final_match_score if r.scores else "","assessment_confidence":r.scores.assessment_confidence if r.scores else "","critical_gaps":"; ".join(r.critical_gaps),"eligibility_reasons":"; ".join(r.eligibility_reasons)})
    else:
        p.write_text(json.dumps([r.model_dump(mode="json") for r in results],ensure_ascii=False,indent=2),encoding="utf-8")
