from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "output"
PROFILE_PATH = DATA / "profile.json"
BROWSER_DIR = DATA / "browser_profile"

DATA.mkdir(exist_ok=True)
OUT.mkdir(exist_ok=True)


def _merge(base, extra):
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


def load():
    cfg = yaml.safe_load((ROOT / "config.example.yaml").read_text()) or {}
    user = ROOT / "config.yaml"
    if user.exists():
        _merge(cfg, yaml.safe_load(user.read_text()))
    return cfg


CFG = load()
