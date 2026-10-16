import asyncio
import json
import logging
import os
from pathlib import Path

from . import config
from .listing_access import listing_guidance

log = logging.getLogger("agentguard.session")

CREATE_NEW_PROCESS_GROUP = 0x00000200


class AgySession:
    def __init__(self, on_event):
        self.on_event = on_event
        self.proc = None
        self.conversation_id = None
        self.cwd = None
        self.permission_mode = None
        self.started_at = None
        self.ended_at = None
        self._reader = None
        self._stderr_reader = None
        self._stderr_log = None
        self._exit_reason = None
        self.model = None
        self.sandbox = False
        self.error = None
        self._listing_guidance_sent = False

    @property
    def state(self) -> str:
        if self.proc is None:
            return "stopped"
        if self.proc.returncode is not None:
            return "exited"
        return "running"

    def status(self) -> dict:
        return {
            "state": self.state,
            "conversation_id": self.conversation_id,
            "cwd": self.cwd,
            "permission_mode": self.permission_mode,
            "model": self.model,
            "sandbox": self.sandbox,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "exit_reason": self._exit_reason,
            "error": self.error,
            "provider": "agy",
        }

    async def start(self, cwd: str, model=None, sandbox=True, mode=None, effort=None, run_interactive=False):
        if self.proc is not None and self.proc.returncode is None:
            raise RuntimeError("a session is already running; stop it first")
        for task in (self._reader, self._stderr_reader):
            if task:
                await task
        self.ended_at = None
        self._exit_reason = None
        self.conversation_id = None
        self.error = None
        self.started_at = config.utcnow()
        self._listing_guidance_sent = False
        self.model = model
        self.sandbox = bool(sandbox)
        cwd_path = Path(cwd).resolve()
        cwd_path.mkdir(parents=True, exist_ok=True)

        cmd = [config.AGY_BIN]
        if run_interactive:
            cmd.append("--prompt-interactive")
        else:
            cmd += ["--input-format", "stream-json", "--output-format", "stream-json"]
        if model:
            cmd += ["--model", model]
        if sandbox:
            cmd += ["--sandbox"]
        if mode:
            cmd += ["--mode", mode]
        if effort:
            cmd += ["--effort", effort]
        if not run_interactive:
            # --print consumes the next token as an optional prompt in agy 1.3.3.
            cmd.append("--print=")
        log.info("spawning %s (cwd=%s)", " ".join(cmd), cwd_path)

        self.proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(cwd_path),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            env={**os.environ, "AGENTGUARD_URL": config.BACKEND_URL, "AGENTGUARD_SECRET": config.load_secret()},
        )
        self.cwd = str(cwd_path)
        self._stderr_log = (config.DATA_DIR / f"agy_{config.utcnow().replace(':','-').replace('.','-')}.log").open("ab")
        self._stderr_reader = asyncio.create_task(self._read_stderr())
        self._reader = asyncio.create_task(self._read_stdout())

    async def send(self, content: str):
        if self.error:
            raise RuntimeError(self.error)
        if self.proc is None or self.proc.returncode is not None:
            raise RuntimeError("no running session")
        guidance = '' if self._listing_guidance_sent else listing_guidance(config.DATA_DIR, config.WORKSPACE_DIR, self.cwd)
        msg = {"event": "user", "message": {"content": guidance + content}}
        line = json.dumps(msg) + "\n"
        self.proc.stdin.write(line.encode("utf-8"))
        await self.proc.stdin.drain()
        self._listing_guidance_sent = True
        return self.conversation_id

    async def stop(self, graceful: bool = True):
        if self.proc is None:
            return
        if self.proc.returncode is None:
            if graceful:
                try:
                    self.proc.stdin.close()
                    try:
                        await asyncio.wait_for(self.proc.wait(), 8)
                    except asyncio.TimeoutError:
                        await self._kill_tree()
                except Exception:
                    await self._kill_tree()
            else:
                await self._kill_tree()
        self.ended_at = config.utcnow()
        return self.exit_code()

    async def _kill_tree(self):
        pid = self.proc.pid
        try:
            self.proc.kill()
        except Exception:
            pass
        if os.name == "nt":
            try:
                proc = await asyncio.create_subprocess_exec(
                    "taskkill", "/PID", str(pid), "/T", "/F",
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                )
                await proc.communicate()
            except Exception:
                pass
        try:
            await asyncio.wait_for(self.proc.wait(), 5)
        except Exception:
            pass

    def exit_code(self):
        return self.proc.returncode if self.proc else None

    async def _read_stderr(self):
        try:
            while True:
                raw = await self.proc.stderr.readline()
                if not raw:
                    break
                text = raw.decode("utf-8", "replace")
                self._stderr_log.write(raw)
                self._stderr_log.flush()
                stripped = text.strip()
                if "Authentication required" in stripped:
                    if os.environ.get("CODEX_SANDBOX_NETWORK_DISABLED", "").lower() in ("1", "true"):
                        self.error = "This backend runs in a network-restricted environment. Stop it and open start-agentguard.cmd from Windows to use your existing CLI login."
                    else:
                        self.error = "The CLI could not authenticate in this backend process. Check that agy works in the same Windows account and terminal used to start AgentGuard, then restart the session."
                if stripped:
                    await self.on_event(
                        {
                            "ws_type": "stderr",
                            "conversation_id": self.conversation_id,
                            "data": stripped,
                        }
                    )
        except Exception as exc:
            log.debug("stderr reader stopped: %s", exc)

    async def _read_stdout(self):
        try:
            while True:
                raw = await self.proc.stdout.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                try:
                    evt = json.loads(line)
                except json.JSONDecodeError:
                    await self.on_event({"ws_type": "stderr", "conversation_id": self.conversation_id, "data": line})
                    continue
                await self._dispatch(evt)
        except Exception as exc:
            log.debug("stdout reader stopped: %s", exc)
        finally:
            await self.proc.wait()
            if self._stderr_reader:
                await self._stderr_reader
            self.ended_at = config.utcnow()
            if self._stderr_log:
                self._stderr_log.close()
            if self.proc and self.proc.returncode is not None and self._exit_reason is None:
                self._exit_reason = f"process exited rc={self.proc.returncode}"
            await self.on_event(
                {
                    "ws_type": "session_end",
                    "conversation_id": self.conversation_id,
                    "data": {"exit_reason": self._exit_reason, "ended_at": self.ended_at},
                }
            )

    async def _dispatch(self, evt: dict):
        event_type = evt.get("event")
        if event_type == "init":
            init = evt.get("init") or {}
            self.conversation_id = evt.get("conversation_id") or self.conversation_id
            self.permission_mode = init.get("permission_mode")
            if not self.cwd:
                self.cwd = init.get("cwd")
            payload = {
                "cwd": init.get("cwd"),
                "tools": init.get("tools", []),
                "permission_mode": init.get("permission_mode"),
            }
        elif event_type == "step_update":
            payload = evt.get("step_update") or {}
        elif event_type == "result":
            payload = evt.get("result") or {}
        else:
            payload = {k: v for k, v in evt.items() if k != "event"}
        await self.on_event(
            {
                "ws_type": "event",
                "event": event_type,
                "conversation_id": self.conversation_id,
                "payload": payload,
            }
        )
