import asyncio
import hashlib
import hmac
import logging
import os
import subprocess
import sys
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config
from .audit import Audit
from .policy import PolicyEngine
from .approvals import ApprovalManager
from .session import AgySession
from .terminal_session import AgyTerminalSession
from .acp_session import GeminiAcpSession, find_gemini_entrypoint
from .hook_command import build_hook_command
from .workspace_files import checked_directory, list_workspace_files
from .windows_sandbox import WindowsSandbox
from .tool_gateway import ToolGateway, NetworkBroker
from .ollama_session import OllamaSession

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("agentguard")

LIFECYCLE_EVENTS = ("session_start", "session_stop", "user_message", "tool_call", "tool_error",
                    "approval_requested", "approval_decided", "session_end")

policy: PolicyEngine | None = None
audit: Audit | None = None
approvals: ApprovalManager | None = None
session: AgySession | None = None
clients: set[WebSocket] = set()
_agy_version: str | None = None
session_lock = asyncio.Lock()
sandbox_runner = WindowsSandbox(config.WORKSPACE_DIR)


def ensure_hook_installed():
    hook_dir = config.WORKSPACE_DIR / ".agents"
    hook_dir.mkdir(parents=True, exist_ok=True)
    hook_py = Path(__file__).resolve().parent.parent / "hook" / "agentguard_hook.py"
    py = sys.executable
    cmd = build_hook_command(py, hook_py)
    hooks_json = {
        "agentguard": {
            "PreToolUse": [
                {
                    "matcher": ".*",
                    "hooks": [
                        {
                            "type": "command",
                            "command": cmd,
                            "timeout": config.HOOK_TIMEOUT,
                        }
                    ],
                }
            ]
        }
    }
    target = hook_dir / "hooks.json"
    existing = json.loads(target.read_text(encoding="utf-8")) if target.exists() else {}
    existing.update(hooks_json)
    with open(target, "w", encoding="utf-8") as fh:
        json.dump(existing, fh, indent=2)
    log.info("installed policy hook -> %s", target)


async def handle_event(evt: dict):
    ws_type = evt.get("ws_type")
    conversation_id = evt.get("conversation_id")
    await broadcast({"type": "event", "data": evt})
    if ws_type == "session_end":
        audit.append("session_end", {"conversation_id": conversation_id, **evt.get("data", {})})
        await broadcast_status()
        return
    if evt.get("event") == "init":
        await broadcast_status()
        return
    if ws_type == "stderr":
        return
    payload = evt.get("payload") or {}
    etype = evt.get("event")
    if etype == "step_update":
        step = payload
        step_type = step.get("step_type")
        state = step.get("state")
        tool_name = step.get("tool_name")
        if step_type == "tool" and state == "ACTIVE":
            audit.append("tool_call", {
                "conversation_id": conversation_id,
                "step_index": step.get("step_index"),
                "tool": tool_name,
                "parameters": (step.get("tool_info") or {}).get("parameters", {}),
                "tool_summary": (step.get("tool_info") or {}).get("toolSummary"),
                "tool_action": (step.get("tool_info") or {}).get("toolAction"),
            })
        elif step_type == "tool" and state == "ERROR":
            err = (step.get("tool_info") or {}).get("error") or {}
            msg = err.get("message") or ""
            kind = "tool_denied" if ("denied" in msg.lower() or "permission" in msg.lower()) else "tool_error"
            record = audit.append(kind, {
                "conversation_id": conversation_id,
                "step_index": step.get("step_index"),
                "tool": tool_name,
                "parameters": (step.get("tool_info") or {}).get("parameters", {}),
                "error": err,
            })
            await broadcast({"type": "action_issue", "data": record})
        elif step_type == "agent_response" and state == "DONE":
            audit.append("agent_response", {
                "conversation_id": conversation_id,
                "step_index": step.get("step_index"),
                "usage": step.get("usage"),
                "duration_seconds": step.get("duration_seconds"),
            })
    elif etype == "result":
        audit.append("result", {
            "conversation_id": conversation_id,
            "status": payload.get("status"),
            "response": payload.get("response"),
            "denied_actions": payload.get("denied_actions"),
            "usage": payload.get("usage"),
        })
        await broadcast_status()


async def broadcast(message: dict):
    dead = []
    for ws in list(clients):
        try:
            await ws.send_json(message)
        except Exception:
            dead.append(ws)
    for ws in dead:
        clients.discard(ws)


async def broadcast_status():
    await broadcast({"type": "status", "data": build_status()})


def get_agy_version() -> str:
    global _agy_version
    if _agy_version:
        return _agy_version
    try:
        out = subprocess.run(
            [config.AGY_BIN, "--version"], capture_output=True, text=True, timeout=10
        )
        _agy_version = (out.stdout or out.stderr).strip().splitlines()[0][:200]
    except Exception as exc:
        _agy_version = f"unavailable ({exc})"
    return _agy_version


def build_status() -> dict:
    return {
        "agy": {
            "path": config.AGY_BIN,
            "version": get_agy_version(),
            "sandbox_supported": True,
        },
        "session": session.status() if session else AgySession(None).status(),
        "workspace": str(config.WORKSPACE_DIR),
        "backend": {"host": config.BACKEND_HOST, "port": config.BACKEND_PORT, "url": config.BACKEND_URL},
        "policy_default": policy.get_policy().get("default_action") if policy else None,
        "ultra_security": policy.get_policy().get("ultra_security", False) if policy else False,
        "approvals_pending": len(approvals.pending_list()) if approvals else 0,
        "agents_hooks": str(config.WORKSPACE_DIR / ".agents" / "hooks.json"),
        "clients": len(clients),
        "enforcement": sandbox_runner.status(),
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    global policy, audit, approvals, session
    config.ensure_dirs()
    policy = PolicyEngine(config.DATA_DIR, config.WORKSPACE_DIR)
    audit = Audit(config.AUDIT_DB)
    approvals = ApprovalManager()
    session = AgySession(handle_event)
    ensure_hook_installed()
    log.info("AgentGuard backend ready (agy=%s)", config.AGY_BIN)
    yield
    if session:
        try:
            await session.stop(graceful=False)
        except Exception:
            pass


app = FastAPI(title="AgentGuard", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173", config.BACKEND_URL],
    allow_methods=["*"],
    allow_headers=["*"],
)


def trusted_origin(origin: str | None) -> bool:
    return origin is None or origin in {"http://127.0.0.1:5173", "http://localhost:5173", config.BACKEND_URL}


@app.middleware("http")
async def local_origin_guard(request: Request, call_next):
    from starlette.responses import JSONResponse
    if not trusted_origin(request.headers.get("origin")):
        return JSONResponse({"detail": "Untrusted origin"}, status_code=403)
    return await call_next(request)


# ---------- DTOs ----------

class SessionStart(BaseModel):
    cwd: str | None = None
    model: str | None = None
    sandbox: bool = True
    mode: str | None = None
    effort: str | None = None
    interactive: bool = False
    provider: str = "agy"


class SessionMessage(BaseModel):
    content: str = Field(min_length=1)


class FileListingRequest(BaseModel):
    directory: str | None = None


class ApprovalDecision(BaseModel):
    decision: str  # allow | block


class PolicyPayload(BaseModel):
    data: dict


class UltraSecurityPayload(BaseModel):
    enabled: bool


class HookEvaluate(BaseModel):
    secret: str
    toolCall: dict
    terminal_id: str | None = None


# ---------- Internal: hook endpoint (blocking) ----------

@app.post("/internal/hook/evaluate")
async def internal_hook_evaluate(body: HookEvaluate | None = None, request: Request = None):
    secret = config.load_secret()
    if body is None:
        return {"decision": "block", "reason": "AgentGuard: empty hook payload"}
    supplied = (body.secret or "") if isinstance(body, HookEvaluate) else ""
    if not secret or not _const_eq(supplied, secret):
        return {"decision": "block", "reason": "AgentGuard: unauthorized hook call (fail closed)"}
    tool_call = body.toolCall or {}
    tool = tool_call.get("name") or ""
    args = tool_call.get("args") or {}
    decision, reason, rule_id = policy.evaluate(tool, args)
    record = audit.append("policy_eval", {
        "tool": tool, "args": args, "decision": decision, "reason": reason, "rule_id": rule_id,
    }, decision=decision)
    # agy 1.3.3 executed a live command without prompting after force_ask.
    # Keep every policy Ask in our own queue; never delegate this gate to CLI.
    if decision == "ask":
        async def pending(rec):
            audit.append("approval_requested", rec)
            await broadcast({"type": "approval", "data": rec})
            await broadcast_status()
        rec = await approvals.request(tool, args, reason, on_pending=pending)
        if rec["decision"] == "block":
            source = "Approval timed out" if rec.get("decided_by") == "timeout" else "The user selected Block in AgentGuard"
            rec["reason"] = f"{source}. Policy reason: {rec['reason']}"
        await broadcast({"type": "approval", "data": {
            "id": rec["id"], "ts": rec["ts"], "tool": rec["tool"], "args": rec["args"],
            "reason": rec["reason"], "decision": rec["decision"], "decided_by": rec.get("decided_by"),
        }})
        record = audit.append("approval_decided", {
            "id": rec["id"], "tool": rec["tool"], "args": rec["args"],
            "reason": rec["reason"], "decision": rec["decision"], "decided_by": rec.get("decided_by"),
        }, decision=rec["decision"])
        decision = rec["decision"]
        reason = rec["reason"]
        await broadcast_status()
        if decision == "allow":
            # Approval is not a bypass: a changed policy/path may now block
            # the operation while the request was waiting for the user.
            current_decision, current_reason, current_rule = policy.evaluate(tool, args)
            if current_decision == "block":
                decision, reason, rule_id = current_decision, current_reason, current_rule
                record = audit.append("approval_recheck_blocked", {
                    "tool": tool, "args": args, "reason": reason, "rule_id": rule_id,
                    "approval_id": rec["id"],
                }, decision="block")
    if decision == "block":
        await broadcast({"type": "action_issue", "data": record})
    return {"decision": decision, "reason": reason, "rule_id": rule_id}


def _const_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


# ---------- REST ----------

@app.get("/api/health")
async def health():
    return {"ok": True}


@app.get('/api/security/results')
async def security_results():
    # Reviewed, fake-fixture evidence artifact. Never enumerate runtime directories
    # or serve arbitrary filesystem paths through this endpoint.
    path = Path(__file__).resolve().parent.parent.parent / 'docs/security-evidence.json'
    if not path.is_file():
        return {'recorded': None, 'replay': [], 'limitations': ['No retained test evidence']}
    return json.loads(path.read_text(encoding='utf-8'))


@app.get("/api/status")
async def status_endpoint():
    return build_status()


@app.get("/api/config")
async def config_endpoint():
    return {
        "models": [{"id": mid, "label": label} for mid, label in config.SUPPORTED_MODELS],
        "workspace": str(config.WORKSPACE_DIR),
        "agy": {"path": config.AGY_BIN, "version": get_agy_version()},
        "gemini_acp_available": find_gemini_entrypoint() is not None,
        "host": config.BACKEND_HOST,
        "port": config.BACKEND_PORT,
        "ollama_models": ["qwen3:4b", "qwen3:8b"],
    }


@app.post("/api/session/start")
async def session_start(body: SessionStart):
    async with session_lock:
        if session and session.state == "running":
            raise HTTPException(status_code=409, detail="Stop the current session before starting another.")
        return await _session_start(body)


async def _session_start(body: SessionStart):
    global session
    cwd = Path(body.cwd or config.WORKSPACE_DIR).resolve()
    ws_root = Path(config.WORKSPACE_DIR).resolve()
    try:
        cwd.relative_to(ws_root)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"cwd must be inside workspace: {ws_root}")
    try:
        if body.provider == "ollama":
            if cwd != ws_root:
                raise HTTPException(status_code=400, detail="Custom agent uses the configured workspace root")
            destinations = json.loads(os.environ.get('AGENTGUARD_HTTP_DESTINATIONS', '{}'))
            if not isinstance(destinations, dict):
                raise HTTPException(status_code=400, detail="HTTP destinations must be an origin-to-IP object")
            gateway = ToolGateway(policy, approvals, audit, sandbox_runner, broadcast, NetworkBroker(destinations))
            session = OllamaSession(handle_event, gateway)
            await session.start(str(cwd), model=body.model)
        elif body.provider == "gemini-acp":
            session = GeminiAcpSession(handle_event, handle_acp_permission)
            await session.start(str(cwd), sandbox=body.sandbox)
        elif body.provider == "agy":
            session = AgyTerminalSession(handle_event) if body.interactive else AgySession(handle_event)
            await session.start(str(cwd), model=body.model, sandbox=body.sandbox, mode=body.mode,
                                effort=body.effort, run_interactive=body.interactive)
        else:
            raise HTTPException(status_code=400, detail="provider must be ollama, agy or gemini-acp")
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except OSError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    audit.append("session_start", {
        "cwd": str(cwd), "model": body.model, "sandbox": body.sandbox, "provider": body.provider,
        "mode": body.mode, "effort": body.effort, "interactive": body.interactive,
    })
    await broadcast_status()
    return session.status()


async def handle_acp_permission(params: dict) -> str:
    """Apply AgentGuard policy and approval queue to a Gemini ACP permission request."""
    call = params.get("toolCall") or {}
    title = str(call.get("title") or "ACP tool request")
    kind = str(call.get("kind") or "").lower()
    raw = call.get("rawInput")
    args = raw.copy() if isinstance(raw, dict) else ({"CommandLine": raw} if isinstance(raw, str) else {})
    lowered = title.lower()
    if kind == "execute" or any(word in lowered for word in ("shell", "command", "terminal")):
        tool = "run_command"
        if "CommandLine" not in args and isinstance(args.get("command"), str):
            args["CommandLine"] = args["command"]
    elif kind in ("edit", "delete"):
        tool = "write_to_file" if kind == "edit" else "delete_file"
    elif kind == "read":
        tool = "view_file"
    elif kind == "search":
        tool = "grep_search"
    else:
        # Preserve workspace containment for filesystem-like ACP calls even
        # when a Gemini CLI release introduces a new tool title/kind.
        path_fields = {"AbsolutePath", "FilePath", "TargetFile", "File", "Path", "Root",
                       "WorkingDirectory", "file_path", "dir_path", "path", "cwd"}
        tool = "view_file" if any(key in args for key in path_fields) else title
    args.setdefault("toolSummary", title)
    decision, reason, rule_id = policy.evaluate(tool, args)
    record = audit.append("policy_eval", {"source": "gemini_acp", "tool": tool, "args": args,
                                             "decision": decision, "reason": reason, "rule_id": rule_id},
                          decision=decision)
    if decision == "ask":
        async def pending(rec):
            audit.append("approval_requested", {**rec, "source": "gemini_acp"})
            await broadcast({"type": "approval", "data": rec})
            await broadcast_status()
        rec = await approvals.request(tool, args, reason, on_pending=pending)
        record = audit.append("approval_decided", {"source": "gemini_acp", "id": rec["id"], "tool": tool,
                                                    "args": args, "reason": reason,
                                                    "decision": rec["decision"], "decided_by": rec.get("decided_by")},
                              decision=rec["decision"])
        await broadcast_status()
        decision = rec["decision"]
    if decision == "block":
        await broadcast({"type": "action_issue", "data": record})
    return decision


@app.post("/api/session/stop")
async def session_stop():
    async with session_lock:
        return await _session_stop()


async def _session_stop():
    try:
        code = await session.stop(graceful=True)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    audit.append("session_stop", {"code": code})
    await broadcast_status()
    return {"stopped": True, "code": code}


@app.post("/api/session/message")
async def session_message(body: SessionMessage):
    if session.state != "running":
        raise HTTPException(status_code=409, detail="no running session")
    try:
        await session.send(body.content)
    except (RuntimeError, BrokenPipeError, ConnectionResetError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    audit.append("user_message", {"conversation_id": session.conversation_id, "content": body.content})
    return {"queued": True, "conversation_id": session.conversation_id}


@app.get("/api/approvals")
async def approvals_endpoint():
    return {"pending": approvals.pending_list(), "history": approvals.history()}


@app.post("/api/workspace/files")
async def workspace_files(body: FileListingRequest):
    try:
        directory = checked_directory(config.WORKSPACE_DIR, body.directory)
    except (OSError, ValueError, RuntimeError) as exc:
        audit.append("workspace_listing_blocked", {"directory": body.directory, "reason": str(exc)}, decision="block")
        raise HTTPException(status_code=400, detail=str(exc))
    args = {"Directory": str(directory), "toolSummary": "List immediate workspace files and sizes"}
    audit.append("tool_call", {"tool": "list_dir", "parameters": args, "source": "dashboard"})
    # Reuse the same policy evaluation, approval queue and decision audit.
    result = await internal_hook_evaluate(HookEvaluate(
        secret=config.load_secret(), toolCall={"name": "list_dir", "args": args}))
    if result["decision"] != "allow":
        raise HTTPException(status_code=403, detail="File listing was blocked by AgentGuard. See the audit for details.")
    try:
        listing = list_workspace_files(config.WORKSPACE_DIR, str(directory))
    except (OSError, ValueError, RuntimeError) as exc:
        record = audit.append("tool_error", {"tool": "list_dir", "source": "dashboard", "error": {"message": str(exc)}})
        await broadcast({"type": "action_issue", "data": record})
        raise HTTPException(status_code=400, detail=str(exc))
    record = audit.append("tool_result", {"tool": "list_dir", "source": "dashboard", **listing})
    return {**listing, "audit_id": record["id"]}


@app.post("/api/approvals/{aid}")
async def approvals_decide(aid: str, body: ApprovalDecision):
    if body.decision not in ("allow", "block"):
        raise HTTPException(status_code=400, detail="decision must be allow or block")
    if not approvals.decide(aid, body.decision):
        raise HTTPException(status_code=404, detail="approval not pending")
    return {"decided": True}


@app.get("/api/policy")
async def policy_endpoint():
    return policy.get_policy()


@app.put("/api/policy")
async def policy_update(body: PolicyPayload):
    try:
        policy.set_policy(body.data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    audit.append("policy_update", {"data": body.data})
    return policy.get_policy()


@app.post("/api/policy/ultra-security")
async def toggle_ultra_security(body: UltraSecurityPayload):
    current = policy.get_policy()
    current["ultra_security"] = body.enabled
    try:
        policy.set_policy(current)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    audit.append("policy_update", {"ultra_security": body.enabled})
    await broadcast_status()
    return {"ultra_security": body.enabled, "policy": policy.get_policy()}


@app.post("/api/policy/evaluate")
async def policy_evaluate(body: dict):
    tool = body.get("tool", "")
    args = body.get("args", {})
    return policy.dry_run(tool, args)


@app.get("/api/audit")
async def audit_endpoint(limit: int = 200):
    return {"events": audit.tail(max(1, min(limit, 1000)))}


@app.get("/api/audit/verify")
async def audit_verify():
    return audit.verify()


@app.delete("/api/audit")
async def audit_clear():
    raise HTTPException(status_code=403, detail="Audit deletion is disabled. Archive the database and checkpoint offline under the operator account.")


# ---------- WebSocket ----------

@app.websocket("/ws/terminal/{terminal_id}")
async def terminal_ws(ws: WebSocket, terminal_id: str):
    # Browser terminal access requires an explicit trusted Origin.
    if not ws.headers.get("origin") or not trusted_origin(ws.headers.get("origin")):
        await ws.close(code=1008)
        return
    current = session
    if not isinstance(current, AgyTerminalSession) or current.terminal_id != terminal_id:
        await ws.close(code=1008)
        return
    await ws.accept()
    owner = object()
    queue, snapshot = current.attach(owner)
    sender = None
    try:
        await ws.send_json(snapshot)

        async def output():
            while True:
                message = await queue.get()
                await ws.send_json(message)
                if message["type"] == "overflow":
                    await ws.close(code=1013)
                    return

        sender = asyncio.create_task(output())
        while True:
            raw = await ws.receive_text()
            if len(raw) > 65536:
                await ws.close(code=1009)
                break
            try:
                message = json.loads(raw)
                if not isinstance(message, dict):
                    raise ValueError("Invalid terminal message")
                if session is not current:
                    raise RuntimeError("This terminal session has been replaced.")
                if message.get("type") == "input":
                    await current.input(owner, message.get("data"))
                elif message.get("type") == "resize":
                    await current.resize(owner, message.get("cols"), message.get("rows"))
                elif message.get("type") == "claim":
                    current.claim(owner)
                else:
                    raise ValueError("Unknown terminal message")
            except (ValueError, RuntimeError, EOFError, OSError) as exc:
                queue.put_nowait({"type": "error", "message": str(exc)})
    except (WebSocketDisconnect, RuntimeError, asyncio.QueueFull):
        pass
    finally:
        current.detach(owner, queue)
        if sender:
            sender.cancel()
            await asyncio.gather(sender, return_exceptions=True)

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    if not trusted_origin(ws.headers.get("origin")):
        await ws.close(code=1008)
        return
    await ws.accept()
    clients.add(ws)
    try:
        await ws.send_json({"type": "status", "data": build_status()})
        while True:
            msg = await ws.receive_json()
            if msg.get("type") == "ping":
                await ws.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        clients.discard(ws)


frontend_dist = config.APP_ROOT / "dist"
if frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
