# AgentGuard

A local React dashboard for the Antigravity CLI with policy checks, human approvals, streamed conversations and a SHA-256 payload audit chain.

Agent responses support rich Markdown, highlighted/copyable code, tables, task lists, math, light/dark themes, and streaming that preserves your reading position. See [response rendering](docs/response-rendering.md) for the component map, structured content format, safety boundaries, and browser tests.

## Run

On this Windows machine, double-click **start-agentguard.cmd** in File Explorer, keep its terminal open, and visit **http://127.0.0.1:8912**. This uses your normal Windows account and network access so the CLI can use its existing login. Launching the backend inside an agent's restricted execution environment can produce authentication prompts even with valid saved credentials, because outbound access is blocked.

Requires Python 3.13, Node.js 20.19+ and an installed CLI. When Gemini CLI
with ACP is detected, the session selector defaults to Gemini CLI (ACP); its
authentication is managed by Gemini CLI. Antigravity CLI (`agy`) remains
available as the alternate provider.

```powershell
python -m pip install -r backend/requirements.txt
npm.cmd install
npm.cmd run build
python backend/run.py
```

Open **http://127.0.0.1:8911**. The backend serves the production dashboard and API from the same address. Rebuild and restart after changes.

If port 8911 is already occupied, use `$env:AGENTGUARD_PORT='8912'` before starting the backend, then open http://127.0.0.1:8912. For frontend development against this port, also set `$env:AGENTGUARD_PROXY='http://127.0.0.1:8912'` before running Vite. Node 22.18+ or Node 24 is recommended for the native config loader.

For frontend development, keep the backend running and run `npm.cmd run dev`. Open http://127.0.0.1:5173. Vite proxies `/api` and `/ws` to port 8911.

## Use

1. Choose a model and working directory inside the approved workspace, then start a session.
2. Send a task. Responses stream into the conversation.
3. Review tool arguments in the permission queue and choose Allow once or Block. Requests time out to block after 180 seconds.
4. Edit policy JSON in Policy, or test an action against the saved policy without executing it.
5. Inspect, export, and verify the latest audit records in Audit trail. Chain verification covers all stored payloads; timestamps and event labels are not covered by the legacy hash format.

For a directory listing, use **List files** in the Conversation header. This is
an explicit dashboard action, independent of the agy shell. It checks the
selected working directory against the workspace, evaluates the `list_dir`
policy, and uses the existing approval queue when needed. It displays immediate
regular-file names and byte sizes in chat, skipping links/reparse points and
limiting traversal to 1,000 directory entries. Decisions and results are audited.
It does not read file contents or run a shell, and it does not automatically
retry a denied CLI command. This bounded metadata feature is not container
isolation and is not proof that an agy agent turn has succeeded.

The CLI has its own permission checks in addition to AgentGuard's hook. Live Windows agy 1.3.3 tests denied `Get-ChildItem` and `ls` after dashboard approval, with sandbox both enabled and disabled. The hook's command permission override did not resolve these failures. The Gemini ACP provider handles `session/request_permission` requests directly: AgentGuard evaluates the tool and arguments, routes `ask` through the existing approval queue, and replies with a one-shot allow or reject outcome. Explicit policy allow rules precede workspace containment. This is a local control interface: do not expose its port to the network.

## Project scope

For the narrowly scoped agy listing-permission setup, see
[CLI listing setup](docs/cli-listing-setup.md). Run `enable-cli-listing.cmd` under
your normal account, restart AgentGuard, and start a new CLI session. Setup was
confirmed applied on this machine on 2026-10-11. It grants only the fixed helper,
not `ls` or `Get-ChildItem`; a prompt requiring either command still lacks that
CLI permission. A successful agent turn using the helper remains unverified.

The intended frontend experience is normal chat, necessary approvals, and the
agent's real answer. The **List files** button is an explicit fallback, not a
replacement for fixing the CLI integration. Do not present a fallback or a
manually obtained result as successful execution of the user's requested command.

The supplied challenge is recorded in [PS01 — Agent Sandbox Escape Gauntlet](PROBLEM_STATEMENT.md). The implementation uses FastAPI and the existing React dashboard with Gemini CLI ACP or agy as the agent provider; it does not use a local model. The challenge's own-agent/open-weight requirement is therefore an explicit deviation, not a completed requirement.

Listing file names and sizes inside the approved workspace is an intended normal task. A CLI permission failure on that task is an integration issue, not a policy requirement to prohibit metadata access. Do not count a manually obtained listing or mocked browser response as a successful agent run.

The current policy hook and CLI sandbox setting are not evidence of a project-controlled container runtime, network/DNS allowlisting, or CPU/memory/process limits. Those challenge requirements still need separate implementation and demonstration. Preserve existing policy checks while investigating CLI compatibility; do not enable blanket permission bypasses to make the demo pass.

Conversation display is live and resets on reload; completed responses and user messages remain in the audit log. Approval history lasts for the current backend process; decisions persist in the audit database.

## Configuration

- `AGENTGUARD_WORKSPACE`: approved root (default: `workspace/`).
- `AGY_BIN`: CLI executable path.
- `GEMINI_CLI_JS`: optional path to Gemini CLI's `bundle/gemini.js` when automatic discovery does not find it.
- `AGENTGUARD_HOST` / `AGENTGUARD_PORT`: default `127.0.0.1:8911`.
- `AGENTGUARD_APPROVAL_TIMEOUT` / `AGENTGUARD_HOOK_TIMEOUT`: seconds, default 180 / 240.

Runtime data and secrets in `data/` are ignored by Git. The hook is installed in the workspace's `.agents/hooks.json`; existing other hook entries are preserved. CLI authentication credentials are never sent to the frontend.

## Checks

```powershell
npm.cmd run build
python -m unittest discover -s backend -p 'test_*.py'
```

With the dashboard running and Chrome installed, `npm.cmd run test:browser` checks session controls against mocked API responses, including the browser scrolling regression. It defaults to port 8912; override with `AGENTGUARD_CHECK_URL`. Set `CHROME_PATH` if Chrome is installed at a custom location.

For a live CLI smoke test, install `backend/requirements-dev.txt` and run `python backend/check_live.py` with no active session. It reads only `workspace/test.txt`, approves that read, and stops its session. Set `AGENTGUARD_CHECK_URL` for an alternate port. CLI authentication and outbound access to its provider must be available in the shell running the backend.
# Windows security upgrade

The custom Ollama/AppContainer path is a **partial implementation with unverified
OS containment**, not a full PS01 compliance claim. See the
[compliance report](docs/security-report.md), [explicit Windows setup](docs/windows-security.md),
and [retained test evidence](docs/security-evidence.json). Existing Agy and Gemini
adapters remain available as legacy development paths.

