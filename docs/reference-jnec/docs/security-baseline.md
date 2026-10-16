# Security baseline — 2026-10-12

Inspected the existing FastAPI/React application before editing. This directory has no
Git metadata (`git status --short` reports not a repository). No runtime database,
credentials, CLI configuration or existing service was changed during inspection.

Baseline: `python -m unittest discover -s backend -p 'test_*.py'`: 48 tests,
OK, 10.174 seconds. `npm.cmd run build`: passed (Vite 6.4.1).
These are regression results, not evidence of provider or OS containment.

Reusable: `policy.py`, `command_boundary.py`, `approvals.py`, SQLite audit API,
FastAPI lifecycle/WebSocket plumbing, React conversation and Markdown renderer.

Execution paths: `session.py` launches agy stream-json; `terminal_session.py`
launches agy through ConPTY and accepts browser keystrokes; `acp_session.py`
launches Gemini and handles selected ACP permission requests. All execute with
the backend account. Hook cooperation is not an OS boundary. Terminal input,
missing hooks, additional CLI tools, and native permission handling cannot be
treated as universally mediated execution. `workspace_files.py` performs a
separate backend-native metadata listing. `configure_cli_listing.py` is an
explicit user setup utility. None supplies verified process token, filesystem,
network or resource isolation. Keep these adapters as development features.

Audit v1 hashes previous digest and payload only, leaving timestamp, event type
and decision mutable. It cannot detect tail truncation. DELETE /api/audit has
no authentication; origin checks do not authenticate local processes.

Ordered implementation: (1) versioned complete-record audit and deletion guard;
(2) strict tool gateway and bounded Ollama loop; (3) Windows AppContainer and Job
Object runner with no unrestricted fallback; (4) network-denied worker plus
trusted HTTP mediation; (5) dashboard enforcement telemetry; (6) deterministic
and live-agent evidence harness, regression checks and compliance report.

Windows design: AppContainer capability/ACL boundary, no network capabilities,
Job Object CPU/memory/process limits, suspended launch then token/job verification
before resume. Explicit user setup grants only workspace write and runtime read.
No Linux, Docker, global firewall changes or silent elevation. OS-dependent
results remain UNVERIFIED until tested against the actual worker token.
