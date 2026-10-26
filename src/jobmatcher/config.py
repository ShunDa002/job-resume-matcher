from pathlib import Path
import yaml
BASE=Path(__file__).resolve().parents[2]
def load_yaml(path):
    with open(path,"r",encoding="utf-8") as f: return yaml.safe_load(f)
def default_config(name): return BASE/"config"/name
