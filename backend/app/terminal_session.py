"""Interactive agy transport. Only explicit browser input is sent to the PTY.

No prompt scraping, inferred permission choices, or automatic Enter responses.
The existing PreToolUse hook continues enforcing AgentGuard policy.
"""
import asyncio
from collections import deque
import os
from pathlib import Path
import socket
import uuid

from . import config


class AgyTerminalSession:
    def __init__(self, on_event):
        self.on_event = on_event
        self.proc = None
        self.terminal_id = uuid.uuid4().hex
        self.conversation_id = None
        self.cwd = None
        self.model = None
        self.sandbox = False
        self.started_at = None
        self.ended_at = None
        self.error = None
        self._reader = None
        self._ended = False
        self._stopping = False
        self._history = deque()
        self._history_size = 0
        self._truncated = False
        self._subscribers = set()
        self._attached = {}
        self._controller = None
        self._io_lock = asyncio.Lock()
        self._close_lock = asyncio.Lock()
        self.cols, self.rows = 100, 30

    @property
    def state(self):
        if self.proc is None:
            return "stopped"
        return "exited" if self._ended else "running"

    def status(self):
        return {
            "state": self.state, "provider": "agy", "interactive": True,
            "terminal_id": self.terminal_id, "conversation_id": None,
            "cwd": self.cwd, "model": self.model, "sandbox": self.sandbox,
            "permission_mode": "Interactive CLI with AgentGuard hook",
            "started_at": self.started_at, "ended_at": self.ended_at,
            "error": self.error, "exit_reason": "Terminal closed" if self._ended else None,
        }

    async def start(self, cwd, model=None, sandbox=True, mode=None, effort=None, **kwargs):
        if os.name != "nt":
            raise OSError("Interactive agy currently requires Windows ConPTY.")
        try:
            from winpty import PtyProcess, Backend
        except ImportError as exc:
            raise OSError("Install backend/requirements.txt to enable the interactive terminal.") from exc
        self.cwd = str(Path(cwd).resolve())
        self.model, self.sandbox = model, bool(sandbox)
        cmd = [config.AGY_BIN]
        for flag, value in (("--model", model), ("--mode", mode), ("--effort", effort)):
            if value:
                cmd.extend([flag, value])
        if sandbox:
            cmd.append("--sandbox")
        # A real interactive invocation: no --print, stream-json, or shell wrapper.
        env = {**os.environ, "TERM": "xterm-256color",
               "AGENTGUARD_URL": config.BACKEND_URL, "AGENTGUARD_SECRET": config.load_secret(),
               "AGENTGUARD_TERMINAL_ID": self.terminal_id}
        self.proc = await asyncio.to_thread(
            PtyProcess.spawn, cmd, cwd=self.cwd, env=env,
            dimensions=(self.rows, self.cols), backend=Backend.ConPTY,
        )
        self.started_at = config.utcnow()
        self._reader = asyncio.create_task(self._read())

    def attach(self, client):
        queue = asyncio.Queue(maxsize=256)
        self._subscribers.add(queue)
        self._attached[client] = queue
        if self._controller is None and not self._ended:
            self._controller = client
        return queue, {
            "type": "snapshot", "data": "".join(self._history),
            "cols": self.cols, "rows": self.rows, "truncated": self._truncated,
            "writable": self._controller is client, "ended": self._ended,
        }

    def detach(self, client, queue):
        self._subscribers.discard(queue)
        self._attached.pop(client, None)
        if self._controller is client:
            self._controller = None
            # React remounts/reconnects can overlap the closing socket. Promote
            # a remaining viewer instead of leaving every tab read-only.
            if not self._ended and not self._stopping:
                self._controller = next(iter(self._attached), None)
                self._notify_control()

    def claim(self, client):
        if client not in self._attached or self.state != "running" or self._stopping:
            raise RuntimeError("This terminal has ended or disconnected.")
        self._controller = client
        self._notify_control()

    def _notify_control(self):
        for client, queue in self._attached.items():
            self._enqueue(queue, {"type": "control", "writable": client is self._controller})

    def _enqueue(self, queue, message):
        try:
            queue.put_nowait(message)
        except asyncio.QueueFull:
            self._subscribers.discard(queue)
            while not queue.empty():
                queue.get_nowait()
            queue.put_nowait({"type": "overflow"})

    def _publish(self, message):
        for queue in list(self._subscribers):
            # Never silently drop terminal bytes: force a fresh snapshot.
            self._enqueue(queue, message)

    async def input(self, client, data):
        if self._controller is not client or self.state != "running" or self._stopping:
            raise RuntimeError("This terminal is read-only or has ended. Reconnect to take control.")
        if not isinstance(data, str) or not 0 < len(data) <= 8192:
            raise ValueError("Terminal input must contain 1–8192 characters.")
        async with self._io_lock:
            if self._controller is not client or self._stopping:
                raise RuntimeError("Terminal control moved to another browser.")
            await asyncio.to_thread(self.proc.write, data)

    async def resize(self, client, cols, rows):
        if self._controller is not client or self.state != "running" or self._stopping:
            raise RuntimeError("Terminal is not writable.")
        if type(cols) is not int or type(rows) is not int or not (20 <= cols <= 300 and 5 <= rows <= 120):
            raise ValueError("Invalid terminal dimensions.")
        async with self._io_lock:
            if self._controller is not client or self._stopping:
                raise RuntimeError("Terminal control moved to another browser.")
            await asyncio.to_thread(self.proc.setwinsize, rows, cols)
            self.cols, self.rows = cols, rows
            self._publish({"type": "resize", "cols": cols, "rows": rows})

    async def send(self, content):
        raise RuntimeError("Type in the interactive agy terminal; its current prompt determines what input means.")

    async def _read(self):
        try:
            while True:
                data = await asyncio.to_thread(self.proc.read, 16384)
                if not data:
                    await asyncio.sleep(0.01)
                    continue
                self._history.append(data)
                self._history_size += len(data)
                while self._history_size > 2_000_000:
                    self._history_size -= len(self._history.popleft())
                    self._truncated = True
                self._publish({"type": "output", "data": data})
        except (EOFError, OSError):
            pass
        except Exception as exc:
            self.error = f"Terminal transport failed: {exc}"
        finally:
            # A failed reader must not leave an invisible process accepting input.
            if not self._stopping:
                try:
                    await self._close_process()
                except Exception as exc:
                    self.error = f"Terminal cleanup failed: {exc}"
            self._ended = True
            self.ended_at = config.utcnow()
            self._publish({"type": "ended", "error": self.error})
            await self.on_event({"ws_type": "session_end", "conversation_id": None,
                                 "data": {"terminal_id": self.terminal_id,
                                          "exit_reason": self.error or "Interactive terminal closed",
                                          "ended_at": self.ended_at}})

    async def _close_process(self):
        async with self._close_lock:
            await self._close_process_once()

    async def _close_process_once(self):
        if self.proc is None:
            return
        # Kill the CLI and its children before releasing the pseudoconsole.
        if await asyncio.to_thread(self.proc.isalive):
            killer = await asyncio.create_subprocess_exec(
                "taskkill", "/PID", str(self.proc.pid), "/T", "/F",
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            )
            await killer.wait()
        try:
            self.proc.fileobj.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        await asyncio.to_thread(self.proc.close, True)

    async def stop(self, graceful=True):
        self._stopping = True
        async with self._io_lock:
            await self._close_process()
        if self._reader:
            await self._reader
        return None
