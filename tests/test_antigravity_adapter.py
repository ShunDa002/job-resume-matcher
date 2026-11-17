import json
from pathlib import Path
from jobmatcher.adapters import AntigravityAdapter
from jobmatcher.config import load_yaml

def test_probe_and_structured_output(tmp_path):
 root=Path.cwd(); exe=root/'tests/fixtures/fake_agy.py'; cfg=load_yaml(root/'config/agent-antigravity.v1.yaml')
 a=AntigravityAdapter(cfg,root,str(exe)); assert a.probe()['ok']
 prompt='INPUT_JSON:\n'+json.dumps({'jobs':[]}); data,errors=a.invoke(prompt,root/'schemas/extraction-result.schema.json',tmp_path/'audit')
 assert not errors and data['schema_version']=='extraction-result.v1'
 assert (tmp_path/'audit/invocation.json').exists()
