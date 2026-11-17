import json,re,subprocess,time
from pathlib import Path
from packaging.version import Version
class AntigravityAdapter:
 def __init__(self,config,workspace,executable=None): self.c=config; self.w=Path(workspace).resolve(); self.exe=executable or config['executable']
 def run(self,args,timeout=30): return subprocess.run(args,cwd=self.w,text=True,capture_output=True,timeout=timeout)
 def probe(self):
  try: v=self.run([self.exe,'--version']); h=self.run([self.exe,'--help'])
  except Exception as e: return {'adapter':'antigravity','ok':False,'error':str(e),'executable':self.exe}
  m=re.search(r'(\d+\.\d+\.\d+)',v.stdout+v.stderr); ver=m.group(1) if m else None; missing=[x for x in ['--output-format','--json-schema','--print-timeout','--add-dir'] if x not in h.stdout+h.stderr]
  ok = v.returncode==0 and h.returncode==0 and not missing and bool(ver) and Version(ver)>=Version(str(self.c.get('minimum_version','1.0.0')))
  return {'adapter':'antigravity','ok':ok,'version':ver,'missing_flags':missing,'executable':self.exe}
 def invoke(self,prompt,schema,audit):
  audit=Path(audit); audit.mkdir(parents=True,exist_ok=True); (audit/'prompt.txt').write_text(prompt)
  args=[self.exe,'--output-format','json','--json-schema',str(Path(schema).resolve()),'--print-timeout',str(self.c.get('print_timeout', '5m')),'--add-dir',str(self.w)]
  if self.c.get('disable_slash_commands', True): args+=['--disable-slash-commands']
  if self.c.get('dangerously_skip_permissions', True): args+=['--dangerously-skip-permissions']
  eff=self.c.get('effort', 'low')
  if eff: args+=['--effort', str(eff)]
  args+=['-p',prompt]; (audit/'invocation.json').write_text(json.dumps({'argv':args[:-1]+['<prompt>']},indent=2))
  t=time.monotonic()
  try: cp=self.run(args,310)
  except Exception as e: return None,[str(e)]
  (audit/'stdout.json').write_text(cp.stdout); (audit/'stderr.log').write_text(cp.stderr)
  if cp.returncode: return None,[f'exit {cp.returncode}']
  try:
   env=json.loads(cp.stdout)
   data=env.get('structured_output')
   if not data and env.get('response'):
    data=json.loads(env['response']) if isinstance(env['response'], str) else env['response']
   if data:
    (audit/'envelope.json').write_text(json.dumps(env,indent=2)); (audit/'structured.json').write_text(json.dumps(data,indent=2)); return data,[]
   err=cp.stderr.strip() or f"status {env.get('status')}"
   return None,[err]
  except Exception as e: return None,[str(e)]
