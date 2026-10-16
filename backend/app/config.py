import os
import shutil
import secrets
from datetime import datetime, timezone
from pathlib import Path


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

APP_ROOT = Path(os.environ.get("AGENTGUARD_ROOT", Path(__file__).resolve().parent.parent.parent))
DATA_DIR = Path(os.environ.get("AGENTGUARD_DATA", APP_ROOT / "data"))
WORKSPACE_DIR = Path(os.environ.get("AGENTGUARD_WORKSPACE", APP_ROOT / "workspace"))
AUDIT_DB = DATA_DIR / "audit.db"
POLICY_FILE = DATA_DIR / "policy.json"
STATE_FILE = DATA_DIR / "config.json"
SECRET_FILE = DATA_DIR / "secret.txt"

BACKEND_HOST = os.environ.get("AGENTGUARD_HOST", "127.0.0.1")
BACKEND_PORT = int(os.environ.get("AGENTGUARD_PORT", "8911"))
BACKEND_URL = os.environ.get("AGENTGUARD_URL", f"http://{BACKEND_HOST}:{BACKEND_PORT}")
APPROVAL_TIMEOUT = int(os.environ.get("AGENTGUARD_APPROVAL_TIMEOUT", "180"))
HOOK_TIMEOUT = int(os.environ.get("AGENTGUARD_HOOK_TIMEOUT", "240"))


def find_agy_binary() -> str:
    env = os.environ.get("AGY_BIN")
    if env and Path(env).exists():
        return env
    candidates = [
        Path.home() / "AppData" / "Local" / "agy" / "bin" / "agy.exe",
        Path.home() / ".local" / "bin" / "agy",
        Path.home() / ".agy" / "bin" / "agy",
        Path.home() / ".gemini" / "bin" / "agy",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    w = shutil.which("agy")
    if w:
        return w
    raise FileNotFoundError("agy binary not found. Set AGY_BIN or install the Antigravity CLI.")


AGY_BIN = find_agy_binary()

SUPPORTED_MODELS = [
    ("gemini-3.8-flash-high", "Gemini 3.8 Flash (High)"),
    ("gemini-3.8-flash-medium", "Gemini 3.8 Flash (Medium)"),
    ("gemini-3.8-flash-low", "Gemini 3.8 Flash (Low)"),
    ("gemini-3.7-flash-high", "Gemini 3.7 Flash (High)"),
    ("gemini-3.7-flash-medium", "Gemini 3.7 Flash (Medium)"),
    ("gemini-3.7-flash-low", "Gemini 3.7 Flash (Low)"),
    ("gemini-3.6-flash-high", "Gemini 3.6 Flash (High)"),
    ("gemini-3.1-pro-high", "Gemini 3.1 Pro (High)"),
    ("claude-sonnet-4-6", "Claude Sonnet 4.6 (Thinking)"),
    ("claude-opus-4-6-thinking", "Claude Opus 4.6 (Thinking)"),
    ("gpt-oss-120b-medium", "GPT-OSS 120B (Medium)"),
]


def ensure_dirs():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)


def load_secret() -> str:
    if SECRET_FILE.exists():
        return SECRET_FILE.read_text(encoding="utf-8").strip()
    token = secrets.token_urlsafe(32)
    SECRET_FILE.write_text(token, encoding="utf-8")
    return token


def load_state() -> dict:
    import json
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_state(state: dict):
    import json
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")