import json, re, subprocess, time
from pathlib import Path
from packaging.version import Version

class CodexAdapter:
    def __init__(self, config, workspace, executable=None):
        self.c = config or {}
        self.w = Path(workspace).resolve()
        self.exe = executable or self.c.get('executable', 'codex')

    def run(self, args, timeout=30):
        return subprocess.run(args, cwd=self.w, text=True, capture_output=True, timeout=timeout)

    def probe(self):
        try:
            v = self.run([self.exe, '--version'])
            h = self.run([self.exe, '--help'])
        except Exception as e:
            return {'adapter': 'codex', 'ok': False, 'error': str(e), 'executable': self.exe}
        m = re.search(r'(\d+\.\d+\.\d+)', v.stdout + v.stderr)
        ver = m.group(1) if m else None
        min_ver = str(self.c.get('minimum_version', '0.1.0'))
        ok = v.returncode == 0 and bool(ver) and Version(ver) >= Version(min_ver)
        return {'adapter': 'codex', 'ok': ok, 'version': ver, 'missing_flags': [], 'executable': self.exe}

    def invoke(self, prompt, schema, audit):
        audit = Path(audit)
        audit.mkdir(parents=True, exist_ok=True)
        (audit / 'prompt.txt').write_text(prompt, encoding='utf-8')
        args = [self.exe, 'exec', '-p', prompt, '--json']
        (audit / 'invocation.json').write_text(json.dumps({'argv': args[:-1] + ['<prompt>']}, indent=2), encoding='utf-8')
        try:
            cp = self.run(args, timeout=int(self.c.get('timeout_seconds', 310)))
        except Exception as e:
            return None, [str(e)]
        (audit / 'stdout.json').write_text(cp.stdout, encoding='utf-8')
        (audit / 'stderr.log').write_text(cp.stderr, encoding='utf-8')
        if cp.returncode:
            return None, [f'exit {cp.returncode}']
        try:
            env = json.loads(cp.stdout)
            data = env.get('structured_output') or (json.loads(env['response']) if isinstance(env.get('response'), str) else env)
            return data, []
        except Exception as e:
            return None, [str(e)]
