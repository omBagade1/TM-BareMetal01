import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from app.hook_command import build_hook_command
from hook.agentguard_hook import denial_reason


@unittest.skipUnless(os.name == "nt", "Windows command-shell regression")
class HookCommandTests(unittest.TestCase):
    def run_hook(self, hook, payload, **env):
        command = build_hook_command(sys.executable, hook)
        return subprocess.run(
            [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", command],
            input=payload.encode("utf-8"), capture_output=True,
            env={**os.environ, **env}, timeout=15,
        )

    def test_space_and_apostrophe_paths_preserve_stdin_and_exit_code(self):
        with tempfile.TemporaryDirectory(prefix="hook path ' ") as tmp:
            hook = Path(tmp) / "hook script.py"
            hook.write_text("import sys\nsys.stdout.write(sys.stdin.read())\nsys.exit(7)\n", encoding="utf-8")
            payload = json.dumps({"name": "list_dir", "args": {"Directory": "C:\\workspace\\café 日本語"}}, ensure_ascii=False)
            result = self.run_hook(hook, payload)
            self.assertEqual(result.returncode, 7, result.stderr.decode(errors="replace"))
            self.assertEqual(json.loads(result.stdout), json.loads(payload))

    def test_real_hook_reaches_policy_endpoint(self):
        received = []
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                received.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"decision":"block","reason":"test policy","rule_id":"__workspace_containment"}')

            def log_message(self, *_):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        hook = Path(__file__).parent / "hook" / "agentguard_hook.py"
        call = {"name": "list_dir", "args": {"Directory": "café 日本語"}}
        try:
            result = self.run_hook(hook.resolve(), json.dumps({"toolCall": call}, ensure_ascii=False),
                                   AGENTGUARD_URL=f"http://127.0.0.1:{server.server_port}",
                                   AGENTGUARD_SECRET="test-only-secret")
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
            self.assertEqual(json.loads(result.stdout), {"decision": "deny", "reason": denial_reason("test policy")})
            self.assertEqual(received, [("/internal/hook/evaluate", {"secret": "test-only-secret", "toolCall": call})])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_real_hook_fails_closed_without_backend(self):
        hook = Path(__file__).parent / "hook" / "agentguard_hook.py"
        result = self.run_hook(hook.resolve(), '{"name":"list_dir","args":{}}',
                               AGENTGUARD_URL="http://127.0.0.1:1", AGENTGUARD_HOOK_HTTP_TIMEOUT="1")
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        self.assertEqual(json.loads(result.stdout)["decision"], "deny")


if __name__ == "__main__":
    unittest.main()
