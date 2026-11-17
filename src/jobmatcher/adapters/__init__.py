from pathlib import Path
from .antigravity import AntigravityAdapter
from .claude import ClaudeAdapter
from .codex import CodexAdapter
from .copilot import CopilotAdapter

ADAPTERS = {
    'antigravity': AntigravityAdapter,
    'claude': ClaudeAdapter,
    'codex': CodexAdapter,
    'copilot': CopilotAdapter,
}

def create_adapter(name: str, config: dict, workspace: Path | str, executable: str | None = None):
    cls = ADAPTERS.get(name)
    if not cls:
        raise ValueError(f"Unknown adapter '{name}'. Supported adapters: {list(ADAPTERS.keys())}")
    return cls(config, workspace, executable)

def get_adapter(name: str, workspace: Path | str, executable: str | None = None):
    from ..config import load_yaml, default_config
    agents_cfg_path = default_config("agents.v1.yaml")
    if agents_cfg_path.exists():
        all_cfg = load_yaml(agents_cfg_path).get("adapters", {})
        cfg = all_cfg.get(name, {})
    elif name == "antigravity" and default_config("agent-antigravity.v1.yaml").exists():
        cfg = load_yaml(default_config("agent-antigravity.v1.yaml"))
    else:
        cfg = {"executable": name}
    return create_adapter(name, cfg, workspace, executable)

def probe_all_adapters(workspace: Path | str):
    from ..config import load_yaml, default_config
    agents_cfg_path = default_config("agents.v1.yaml")
    if agents_cfg_path.exists():
        all_cfg = load_yaml(agents_cfg_path).get("adapters", {})
        adapter_names = list(all_cfg.keys())
    else:
        adapter_names = list(ADAPTERS.keys())

    results = {}
    for name in adapter_names:
        try:
            adapter = get_adapter(name, workspace)
            results[name] = adapter.probe()
        except Exception as e:
            results[name] = {"adapter": name, "ok": False, "error": str(e)}
    return results

__all__ = [
    "AntigravityAdapter",
    "ClaudeAdapter",
    "CodexAdapter",
    "CopilotAdapter",
    "ADAPTERS",
    "create_adapter",
    "get_adapter",
    "probe_all_adapters",
]
