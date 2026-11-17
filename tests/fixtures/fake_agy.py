#!/usr/bin/env python3
import json,re,sys
if '--version' in sys.argv: print('Antigravity CLI 1.2.4'); raise SystemExit
if '--help' in sys.argv: print('--output-format --json-schema --print-timeout --add-dir --disable-slash-commands -p'); raise SystemExit
p=sys.argv[sys.argv.index('-p')+1]
if 'candidate-profile' in ' '.join(sys.argv) or 'RESUME_TEXT:' in p:
    cid_m = re.search(r'CANDIDATE_ID:\s*([^\n\r]+)', p)
    cid = cid_m.group(1).strip() if cid_m else 'candidate-001'
    cm = re.search(r"'citizenship_country_code':\s*'([^']+)'", p) or re.search(r'"citizenship_country_code":\s*"([^"]+)"', p)
    cit = cm.group(1) if cm else None
    out = {
        'schema_version': 'candidate-profile.v1',
        'candidate_id': cid,
        'citizenship_country_code': cit,
        'residence_country_code': None,
        'has_target_country_work_rights': False,
        'target_employment_types': ['full_time'],
        'career_level': 'fresh_graduate',
        'professional_experience_years': 0,
        'degree_fields': ['software_engineering'],
        'graduation_date': None,
        'skills': [{'skill_id': 'python', 'category': 'technical_skills', 'level': 'substantial_project', 'evidence': ['Python']}],
        'responsibilities': [],
        'domains': [],
        'soft_skills': [],
        'metadata': {}
    }
    print(json.dumps({'conversation_id': 'fake', 'status': 'SUCCESS', 'structured_output': out, 'response': json.dumps(out)}))
    raise SystemExit
m=re.search(r'INPUT_JSON:\s*(\{.*?\})\s*(?:INVALID_OUTPUT:|$)',p,re.S)
try: x=json.loads(m.group(1))
except Exception: x=json.loads(re.search(r'INPUT_JSON:\s*(\{.*\})',p,re.S).group(1))
out={'schema_version':'extraction-result.v1','jobs':[]}
for j in x['jobs']:
 d=j['description']; ce='Applicants must be Singaporean citizens.' if 'Singaporean citizens' in d else None; y=4.0 if '4+ years' in d else None
 out['jobs'].append({'job_id':j['job_id'],'normalized_title':j['title'],'normalized_company':j['company'],'minimum_experience_years':y,'experience_requirement_type':'required' if y else 'not_stated','career_level':'senior' if 'Senior' in j['title'] else 'entry_level','citizenship':{'requirement':'explicit' if ce else 'not_stated','country_code':'SG' if ce else None,'evidence_text':ce},'work_authorization':{'sponsorship':'unknown','evidence_text':None},'degree_fields':[],'requirements':[],'warnings':[]})
print(json.dumps({'conversation_id':'fake','status':'SUCCESS','structured_output':out,'response':json.dumps(out)}))
