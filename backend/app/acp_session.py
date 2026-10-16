"""Gemini CLI Agent Client Protocol (ACP) session transport.

ACP is newline-delimited JSON-RPC over stdio. Permission requests are held open
until AgentGuard's policy and, when needed, its existing approval queue decide.
"""
import asyncio
import json
import logging
import os
from pathlib import Path
import shutil

from . import config

log = logging.getLogger("agentguard.acp")


def startup_error_message(message: str) -> str:
    if "this client is no longer supported for gemini code assist for individuals" in message.lower():
        return (
            "Google rejected Gemini CLI's individual-account login. This is a provider access restriction, "
            "not a sandbox or permission-queue error. For your current login, select Antigravity CLI in "
            "Session controls. To keep using Gemini ACP, configure Gemini CLI with a supported authentication "
            "method (Gemini API key or Vertex AI), then restart AgentGuard under the same Windows account. "
            "Setup: https://geminicli.com/docs/get-started/authentication/"
        )
    return message


def find_gemini_entrypoint() -> Path | None:
    override = os.environ.get("GEMINI_CLI_JS")
    if override and Path(override).is_file():
        return Path(override)
    candidates = [
        Path.home() / "AppData" / "Roaming" / "npm" / "node_modules" / "@google" / "gemini-cli" / "bundle" / "gemini.js",
        Path.home() / ".npm-global" / "node_modules" / "@google" / "gemini-cli" / "bundle" / "gemini.js",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


class GeminiAcpSession:
    def __init__(self, on_event, on_permission):
        self.on_event = on_event
        self.on_permission = on_permission
        self.proc = None
        self.conversation_id = None
        self.cwd = None
        self.permission_mode = "AgentGuard policy via ACP"
        self.started_at = None
        self.ended_at = None
        self.model = None
        self.sandbox = False
        self.error = None
        self._reader = None
        self._stderr_reader = None
        self._stderr_log = None
        self._next_id = 1
        self._responses = {}
        self._write_lock = asyncio.Lock()
        self._turn_active = False
        self._entrypoint = find_gemini_entrypoint()

    @property
    def state(self):
        if self.proc is None:
            return "stopped"
        return "exited" if self.proc.returncode is not None else "running"

    def status(self):
        return {
            "state": self.state, "conversation_id": self.conversation_id,
            "cwd": self.cwd, "permission_mode": self.permission_mode,
            "model": self.model, "sandbox": self.sandbox,
            "started_at": self.started_at, "ended_at": self.ended_at,
            "exit_reason": None, "error": self.error, "provider": "gemini-acp",
        }

    async def _write(self, message):
        if not self.proc or self.proc.returncode is not None:
            raise RuntimeError("Gemini ACP process is not running")
        data = (json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        async with self._write_lock:
            self.proc.stdin.write(data)
            await self.proc.stdin.drain()

    async def _request(self, method, params, timeout=45):
        request_id = self._next_id
        self._next_id += 1
        future = asyncio.get_running_loop().create_future()
        self._responses[request_id] = future
        await self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        try:
            return await asyncio.wait_for(future, timeout)
        finally:
            self._responses.pop(request_id, None)

    async def start(self, cwd: str, model=None, sandbox=False, mode=None, effort=None, run_interactive=False):
        if self.proc is not None and self.proc.returncode is None:
            raise RuntimeError("a session is already running; stop it first")
        if not self._entrypoint:
            raise OSError("Gemini CLI ACP entrypoint not found. Set GEMINI_CLI_JS to bundle/gemini.js.")
        if shutil.which("node") is None:
            raise OSError("Node.js is required to launch Gemini CLI ACP.")
        cwd_path = Path(cwd).resolve()
        cwd_path.mkdir(parents=True, exist_ok=True)
        self.cwd = str(cwd_path)
        self.started_at = config.utcnow()
        self.ended_at = None
        self.error = None
        self.sandbox = bool(sandbox)
        cmd = [shutil.which("node"), str(self._entrypoint), "--acp"]
        if sandbox:
            cmd.append("--sandbox")
        else:
            cmd.append("--sandbox=false")
        env = {**os.environ, "GEMINI_CLI_NO_RELAUNCH": "1", "AGENTGUARD_URL": config.BACKEND_URL,
               "AGENTGUARD_SECRET": config.load_secret()}
        if not sandbox:
            # Gemini gives this environment variable precedence over CLI/settings.
            # Honor the explicit app selection only in this child process.
            env["GEMINI_SANDBOX"] = "false"
        self.proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=self.cwd, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            creationflags=0x00000200 if os.name == "nt" else 0, env=env,
        )
        self._stderr_log = (config.DATA_DIR / f"gemini_acp_{config.utcnow().replace(':','-').replace('.','-')}.log").open("ab")
        self._reader = asyncio.create_task(self._read_stdout())
        self._stderr_reader = asyncio.create_task(self._read_stderr())
        try:
            await self._request("initialize", {
                "protocolVersion": 1,
                "clientInfo": {"name": "AgentGuard", "version": "1.0"},
                "clientCapabilities": {"fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False},
            })
            await self._write({"jsonrpc": "2.0", "method": "initialized", "params": {}})
            result = await self._request("session/new", {"cwd": self.cwd, "mcpServers": []})
            self.conversation_id = result.get("sessionId")
        except Exception as exc:
            self.error = f"Gemini CLI ACP startup failed: {startup_error_message(str(self.error or exc))}"
            await self.stop(graceful=False)
            raise RuntimeError(self.error) from exc

    async def send(self, content: str):
        if self.error:
            raise RuntimeError(self.error)
        if self.state != "running" or not self.conversation_id:
            raise RuntimeError("no running Gemini ACP session")
        self._turn_active = True
        task = asyncio.create_task(self._request("session/prompt", {
            "sessionId": self.conversation_id,
            "prompt": [{"type": "text", "text": content}],
        }, timeout=24 * 60 * 60))
        task.add_done_callback(lambda done: log.error("ACP prompt failed: %s", done.exception())
                               if not done.cancelled() and done.exception() else None)
        return self.conversation_id

    async def stop(self, graceful=True):
        if self.proc is None:
            return None
        if self.proc.returncode is None:
            if graceful:
                try:
                    self.proc.stdin.close()
                    await asyncio.wait_for(self.proc.wait(), 8)
                except Exception:
                    await self._kill_tree()
            else:
                await self._kill_tree()
        self.ended_at = config.utcnow()
        if self._stderr_log:
            self._stderr_log.close()
            self._stderr_log = None
        return self.proc.returncode

    async def _kill_tree(self):
        if not self.proc or self.proc.returncode is not None:
            return
        pid = self.proc.pid
        self.proc.kill()
        if os.name == "nt":
            try:
                taskkill = await asyncio.create_subprocess_exec(
                    "taskkill", "/PID", str(pid), "/T", "/F",
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
                await taskkill.communicate()
            except Exception:
                pass
        try:
            await asyncio.wait_for(self.proc.wait(), 5)
        except Exception:
            pass

    async def _read_stderr(self):
        try:
            while True:
                raw = await self.proc.stderr.readline()
                if not raw:
                    break
                if self._stderr_log:
                    self._stderr_log.write(raw)
                    self._stderr_log.flush()
                message = raw.decode("utf-8", "replace").strip()
                if "this client is no longer supported for gemini code assist for individuals" in message.lower():
                    self.error = startup_error_message(message)
                if "failed to determine command for sandbox" in message.lower():
                    self.error = "Gemini sandbox is unavailable. Install Docker or Podman, or turn off Request Gemini CLI sandbox in Session controls."
                if "authentication required" in message.lower() or "please set an auth method" in message.lower():
                    self.error = "Gemini CLI is not authenticated for ACP. Sign in with Gemini CLI under the same Windows account, then restart the session."
                if message:
                    await self.on_event({"ws_type": "stderr", "conversation_id": self.conversation_id, "data": message})
        except Exception as exc:
            log.debug("ACP stderr reader stopped: %s", exc)

    async def _read_stdout(self):
        try:
            while True:
                raw = await self.proc.stdout.readline()
                if not raw:
                    break
                try:
                    message = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    log.warning("Ignoring non-JSON stdout from Gemini ACP")
                    continue
                if "id" in message and "method" not in message:
                    future = self._responses.get(message["id"])
                    if future and not future.done():
                        if "error" in message:
                            future.set_exception(RuntimeError(message["error"].get("message", "ACP request failed")))
                        else:
                            future.set_result(message.get("result") or {})
                elif message.get("method") == "session/request_permission":
                    asyncio.create_task(self._handle_permission(message))
                elif message.get("method") == "session/update":
                    await self._handle_update(message.get("params") or {})
        except Exception as exc:
            log.exception("ACP stdout reader stopped: %s", exc)
        finally:
            if self.proc:
                await self.proc.wait()
            self.ended_at = config.utcnow()
            if self._stderr_reader and self._stderr_reader is not asyncio.current_task():
                await self._stderr_reader
            for future in list(self._responses.values()):
                if not future.done():
                    future.set_exception(RuntimeError(self.error or f"Gemini CLI ACP process exited (code {self.proc.returncode})"))
            await self.on_event({"ws_type": "session_end", "conversation_id": self.conversation_id,
                                 "data": {"exit_reason": f"Gemini ACP exited rc={self.proc.returncode}", "ended_at": self.ended_at}})

    async def _handle_permission(self, message):
        params = message.get("params") or {}
        try:
            decision = await self.on_permission(params)
            options = params.get("options") or []
            wanted_kind = "allow_once" if decision == "allow" else "reject_once"
            option = next((o for o in options if o.get("kind") == wanted_kind), None)
            result = {"outcome": {"outcome": "selected", "optionId": option["optionId"]}} if option else {"outcome": {"outcome": "cancelled"}}
            await self._write({"jsonrpc": "2.0", "id": message.get("id"), "result": result})
        except Exception:
            log.exception("ACP permission request failed closed")
            await self._write({"jsonrpc": "2.0", "id": message.get("id"), "result": {"outcome": {"outcome": "cancelled"}}})

    async def _handle_update(self, params):
        update = params.get("update") or {}
        kind = update.get("sessionUpdate")
        if kind == "agent_message_chunk":
            content = update.get("content") or {}
            text = content.get("text") if content.get("type") == "text" else ""
            if text:
                await self.on_event({"ws_type": "event", "event": "step_update", "conversation_id": self.conversation_id,
                                     "payload": {"step_type": "agent_response", "state": "ACTIVE", "text_delta": text}})
        elif kind in ("tool_call", "tool_call_update"):
            tool = update.get("toolCall") or update
            await self.on_event({"ws_type": "event", "event": "step_update", "conversation_id": self.conversation_id,
                                 "payload": {"step_type": "tool", "state": "ACTIVE", "tool_name": tool.get("title", "tool"),
                                             "tool_info": {"parameters": tool.get("rawInput") or {}, "toolAction": tool.get("title")}}})
        elif kind == "prompt_complete":
            self._turn_active = False
            await self.on_event({"ws_type": "event", "event": "result", "conversation_id": self.conversation_id,
                                 "payload": {"status": "success"}})
        elif kind == "current_mode_update":
            self.permission_mode = update.get("currentModeId") or self.permission_mode

