# AGENTS.md

AgentGuard is a local web GUI bridge to the Google Antigravity CLI (`agy` v1.3.3). Both frontend and backend are implemented: FastAPI + Python 3.13, Vite 6 + React 19 + TypeScript, plain CSS, and Lucide icons. Do not scaffold another frontend or introduce Tailwind based on older plans.

## Run and rebuild

- Recommended Windows entry point: open `start-agentguard.cmd` from File Explorer under the user's normal account. It starts the app at **http://127.0.0.1:8912** and sets the hook callback URL accordingly. Keep its terminal open.
- The launcher builds only when `dist/index.html` is missing. After frontend edits, explicitly run `npm.cmd run build`, then refresh the browser. An existing `dist/` may be stale.
- Direct backend: `python backend/run.py`; defaults to `127.0.0.1:8911`. It mounts `dist/` if present at startup. If the first build happens after startup, restart to mount the frontend.
- Backend dependencies: `python -m pip install -r backend/requirements.txt` (user site-packages; no venv). Frontend: `npm.cmd install`. Maintain `package-lock.json`.
- Development: `npm.cmd run dev` serves port 5173 and proxies `/api` and `/ws` to 8911. For the launcher backend, first set `$env:AGENTGUARD_PROXY='http://127.0.0.1:8912'`.
- Restart after editing `backend/app/*` (no `--reload`); restart the CLI session after hook configuration changes. Preserve the user's normal execution context rather than replacing a working backend with a restricted agent-launched process.
- Launcher logs appear in its terminal. Redirected runs may use `backend/server.out.log*`; CLI stderr is in `data/agy_*.log`.
- Ignore runtime/build artifacts: `data/`, `backend/server.out.log*`, `dist/`, `node_modules/`, `.npm-cache/`, `.qa/`, Python caches, TypeScript build metadata, and `workspace/.agents/`. Never commit secrets.

## Verify

- `npm.cmd run build`: TypeScript checks and production build. No lint script is configured.
- `python -m unittest discover -s backend -p 'test_*.py'`: approvals, timeouts, policy validation/containment, audit tampering, and Windows hook invocation. Windows-specific tests skip on other systems.
- Browser tests use `playwright-core` and installed Chrome; `CHROME_PATH` overrides the executable. REST/WebSocket traffic is mocked, so they do not affect real CLI sessions.
- Serve a test build with `python -m http.server 5174 --bind 127.0.0.1 --directory dist`. In another terminal set `$env:AGENTGUARD_CHECK_URL='http://127.0.0.1:5174'`, then run `npm.cmd run test:browser` and `npm.cmd run test:responses`. Screenshots go to `.qa/`. Without overrides, session tests default to 8912 and response tests to 5174.
- Live CLI smoke test: install `backend/requirements-dev.txt`, ensure no active session, then run `python backend/check_live.py`. It reads only `workspace/test.txt`, approves that read, and stops its own session. Set `AGENTGUARD_CHECK_URL` for an alternate port (default 8911). Requires working CLI authentication and provider access.
- REST checks: `/api/health`, `/api/status`, `POST /api/session/start` with `{"cwd":"<workspace>"}`, `POST /api/session/message`, `/api/approvals`, `/api/audit?limit=50`, and `/api/audit/verify`.
- Distinguish mocked browser tests, direct hook tests, and actual provider-backed agent turns. A passing build or mocked response does not establish live CLI success.

## Windows and execution-context gotchas

- Shell is PowerShell 5.1: use separate commands or `;`/`if ($?)`, never `&&` in that shell. Use `npm.cmd` because execution policy blocks `npm.ps1`. Use `python` (3.13.7); `py` selects 3.14 here.
- Vite scripts use `--configLoader native` and `vite.config.js`: bundled config loading hit restricted parent-directory access. Installed Node is 24.
- Use `config.utcnow()` for timestamps. `time.strftime("%f")` fails on Windows. Watch imports when removing `time` usage.
- **Authentication context:** a backend launched as `codexsandboxoffline` inherited blocked outbound networking (`CODEX_SANDBOX_NETWORK_DISABLED`). Despite a readable user credential file, the CLI requested authentication and logged network permission errors. Run `start-agentguard.cmd` under the user's normal account. Do not copy tokens, alter credential permissions, or bypass execution restrictions.
- **Hook quoting:** a directly quoted `C:\Program Files\Python313\python.exe` command failed through the CLI's Windows shell invocation; adding `call` also failed in reproduction. Use `backend/app/hook_command.py:build_hook_command`. Its quote-free outer PowerShell `-EncodedCommand` invocation safely quotes paths inside, forwards stdin as UTF-8, and propagates Python's exit code. Tests cover spaces, apostrophes, Unicode, endpoint delivery, and fail-closed behavior. Secrets remain in inherited environment variables, not encoded commands.
- **React effect cleanup:** Chrome may return a Promise from `scrollIntoView()`. Never implicitly return that call from an effect; use a block body and discard the result. React tried to invoke the Promise as cleanup, causing the Start session blank-screen bug. Chat now uses container `scrollTop` and `ResizeObserver`.

## agy protocol

- Interactive browser mode uses `backend/app/terminal_session.py` (Windows ConPTY) and `src/components/InteractiveTerminal.tsx`. It invokes plain `agy`, not stream-json. Native CLI options appear in the browser terminal and receive explicit keystrokes. All policy Ask decisions must wait in AgentGuard's own queue. A live 2026-10-11 test recorded `force_ask` delegation (#537) but the listing completed without the user's expected prompt. Delegation is removed and the hook rejects `force_ask`, including from stale backends. Do not restore native-only Ask handling based on docs or mocked tests. Duplicate review remains possible; see `docs/interactive-terminal.md`.

- Binary: `C:\Users\Akhilesh\AppData\Local\agy\bin\agy.exe`, overridable with `AGY_BIN`. OAuth credentials live in `~/.gemini/oauth_creds.json`; never print, commit, or expose them to the frontend.
- Persistent invocation: `agy --input-format stream-json --output-format stream-json --print=`. Keep the explicit empty value: bare `--print` consumes the next flag as its prompt or reports a missing argument when placed last.
- Feed one NDJSON line per turn: `{"event":"user","message":{"content":"..."}}`. The process persists until stdin closes. Events: `init`, `step_update` (`agent_response` has `text_delta`; `tool` has `tool_info.parameters`), and `result` (`status`, `denied_actions`, `usage`).
- `agy models` lists models; `--model <id>` selects. The UI catalog lives in `backend/app/config.py`. Verify availability with the installed CLI when updating it.
- CLI `--sandbox` does not grant command permission. Live Windows agy 1.3.3 tests have denied `Get-ChildItem` and `ls` after AgentGuard approval, both with and without sandbox enabled. The CLI reports that headless mode cannot prompt for its separate command permission. Its "user denied" text does not prove the dashboard user clicked Block. Do not weaken policy enforcement to work around CLI denials or claim that the sandbox flag establishes PS01 container/network containment.
- File reads such as `view_file` are not independently gated by the CLI; the AgentGuard hook is essential to block them.

## Verified listing status and project direction

- Preserve the agy + FastAPI + React approach. The user explicitly does not want a local-model migration or major redesign. The original challenge is in `PROBLEM_STATEMENT.md`; the open-weight-agent requirement remains a documented deviation.
- Normal workspace metadata listing is an intended allowed task. General CLI command approval integration remains unresolved; do not report it fixed based on unit tests, mocked browser tests, or a native dashboard listing.
- On 2026-10-11 the installed CLI settings contained only `command(C:/Users/Akhilesh/Downloads/jnec/list-workspace.cmd)` in `permissions.allow`. Setup was applied, but this grants neither `ls` nor `Get-ChildItem`. Audit #429 recorded human allow for `ls`; #430 recorded the subsequent CLI denial. IDs are historical references and may disappear when the log is cleared.
- The hook emits CLI `deny` for backend `block`, omits internal `rule_id`, and adds `permissionOverrides` for approved commands. Live tests still failed with that override; do not describe it as a verified command-approval solution.
- `enable-cli-listing.cmd` runs `backend/configure_cli_listing.py --apply` under the normal user account. It backs up changed CLI settings and grants only the fixed helper. `data/listing-access.json` activates exact-command/workspace checks and first-message helper guidance in `session.py`. See `docs/cli-listing-setup.md` for scope and rollback. End-to-end agent use of the helper remains unverified.
- The Conversation **List files** button calls `POST /api/workspace/files` through the policy/approval gate. It lists immediate regular-file metadata, skips links/reparse points, caps enumeration at 1,000 entries, and audits the result. This explicit dashboard action is distinct from an agy tool call. The desired UX is ordinary chat with approvals and agent answers, not dependence on task-specific workaround buttons.
- The built-in skill exception is limited to resolved, existing file reads in the backend account's installed skill directory. It does not grant shell commands, writes, credentials, or general external-file access. See `docs/skill-access.md`.

## Policy gate and backend conventions

- `main.ensure_hook_installed` writes the AgentGuard `PreToolUse` hook to `<workspace>/.agents/hooks.json` on startup, preserving other top-level hook entries. Matcher is `.*`; execution reaches `backend/hook/agentguard_hook.py`. Workspace discovery is verified. Do not modify global `~/.gemini/config/hooks.json`.
- The backend sets `AGENTGUARD_URL` and `AGENTGUARD_SECRET` for agy; hooks inherit them and call `POST /internal/hook/evaluate`. Secret comparison uses `hmac.compare_digest`. Unauthorized calls and unreachable backends fail closed.
- Policy order: hard command eligibility and all-target file/credential boundaries first, then explicit rules and default_action. Allow rules and human Allow cannot override hard blocks. Shell grammar is limited to literal Get-ChildItem/Get-Content workspace operations; opaque/compound/script/network commands block. Existing fixed metadata helper and installed-skill read exceptions remain narrow. Approved requests are rechecked before hook release. See docs/command-policy.md; these filters are not OS isolation. Invalid actions/rules/regexes are rejected on save.
- Approval requests broadcast **before** waiting on their `asyncio.Future`. `POST /api/approvals/{id}` resolves the request; timeout (default 180 seconds) blocks it. Never return Futures in JSON history. Pending/history records are process-local; decisions persist in the audit database.
- Audit: SQLite with SHA-256 over `prev_hash + canonical payload`; `/api/audit/verify` recomputes the chain. The legacy format does **not** authenticate timestamps or event labels. Do not claim protection for every database field.
- **Clear log** confirms before `DELETE /api/audit`; it deletes saved events, restarts the chain from genesis, and preserves increasing IDs. `audit_cleared` removes cached links/notices through the cleared ID. New events continue recording. Clearing is not evidence that historical events were never modified.
- Keep plain asyncio + FastAPI. `session.py` handles process transport/parsing and transport errors; policy decisions belong in `policy.py`.
- CLI events flow through `handle_event` to WebSocket broadcasts (`{"type":"event","data":{...}}`) and applicable audit records. Approval/status messages use `type:"approval"` and `type:"status"`. Lifecycle/policy endpoints also audit directly.
- This is a local control interface, not a publicly authenticated service. Preserve local HTTP/WebSocket origin checks and the separate hook-secret check.

## Frontend and response rendering

- `src/main.tsx` owns tabs, REST/WebSocket integration, session controls, approvals, policy editing, audit UI, and live chat state. Chat resets on reload; audit history is not replayed into the conversation.
- `src/components/ChatMessage.tsx` memoizes messages and lazy-loads `ResponseRenderer.tsx`. User messages stay plain text. Reuse this path rather than adding another renderer.
- Stack: React Markdown + remark-gfm; Remend for incomplete streaming Markdown; remark-math/rehype-katex/KaTeX for math; lazy Shiki tokens and explicit grammars. Code/copy/theme controls are reusable components.
- `src/response.css` scopes response typography; `src/theme.css` supplies light/dark/system theme overrides. Preserve the navy/blue design. Avoid broad selectors such as `.message strong` that override Markdown formatting.
- Untrusted output must never execute HTML or JavaScript. Raw HTML is disabled; no `dangerouslySetInnerHTML` in response components. Links permit HTTP/HTTPS/mailto and simple fragments. Images become explicit links rather than automatic external requests. KaTeX uses `trust:false` and bounded expansion/size.
- Optional `agentguard-json` fences support validated notices and collapsible details through `src/rendering/rich-content.tsx`. Unknown/malformed structures remain code. Mermaid/charts are not interactive; unknown/unlabeled code stays plain. Highlighting is skipped above 30,000 characters per code block.
- Streaming preserves original text for copy/download and memoizes completed messages. Respect readers who scroll upward; retain near-bottom tracking and Jump to latest. Keep the Start session regression covered.
- See [docs/response-rendering.md](docs/response-rendering.md) for the component map, structured-data schema, safety constraints, supported languages/math delimiters, and browser coverage.

## Environment overrides

- `AGENTGUARD_HOST` / `AGENTGUARD_PORT`: defaults `127.0.0.1:8911`; Windows launcher uses 8912.
- `AGENTGUARD_URL`: hook callback address; keep it consistent with the backend port.
- `AGENTGUARD_WORKSPACE`: approved root; default `workspace/`.
- `AGENTGUARD_APPROVAL_TIMEOUT` / `AGENTGUARD_HOOK_TIMEOUT`: defaults 180 / 240 seconds. Hook HTTP wait: `AGENTGUARD_HOOK_HTTP_TIMEOUT`, default 300 seconds.
- `AGY_BIN`: CLI executable override.
- `AGENTGUARD_PROXY`: Vite target; default `http://127.0.0.1:8911`.
- `AGENTGUARD_CHECK_URL` / `CHROME_PATH`: test target and optional Chrome executable.

- Bounded metadata recursion is eligible with `Get-ChildItem -Directory -Depth 0..3` (optional `-Recurse`), after a link/reparse and enumeration-budget preflight. `Get-Location` and `pwd` without arguments are eligible. These still follow ordinary approval rules; do not describe all recursion as prohibited. See `docs/command-policy.md`.

- With default Ask and no matching explicit rule, fully validated `Get-ChildItem`, `Get-Location`, and `pwd` return metadata Allow (`__workspace_metadata`); explicit Ask/Block and default Block are preserved. Native agy permission is still independent. Do not claim general single-approval integration.

## Workspace navigation and directory surfing

- **Single command only**: Never explore directories or subfolders one-by-one using sequential `Get-ChildItem` commands. 9 sequential commands for browsing folders is completely sub-optimal when 1 single command suffices.
- **Supported recursive syntax**: Use `Get-ChildItem -Path <folder> -Directory -Depth 0..3 -Name` (e.g., `Get-ChildItem -Path ps01-tests -Directory -Depth 2 -Name` or piped to `Select-Object Name`).
- **Hard-blocked syntax**: `ls`, `dir`, `tree`, `find`, wildcards (`*`), command chaining (`;`, `&&`), and unbounded `-Recurse` without both `-Directory` and `-Depth 0..3` are hard-blocked by `command_boundary.py`.
- **Automatic approval**: Validated `Get-ChildItem` commands with `-Directory -Depth 0..3` pass preflight checks and are automatically granted under `__workspace_metadata` without prompt delays.

