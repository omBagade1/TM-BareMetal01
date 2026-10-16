# PS01 upgrade report — 2026-10-12

**Overall: PARTIAL. Full PS01 compliance is not demonstrated.** Code was added
incrementally to the existing project; the React/FastAPI architecture and legacy
adapters were preserved. No real secrets, global firewall changes, elevation, WSL,
Docker, model downloads or system-wide destructive changes were used. The existing
live backend was not replaced. Existing runtime SQLite data was not opened or altered
by this work; migration was exercised on disposable test databases.

A later user-run startup check succeeded after fixing per-call ACL inheritance. Its exact recorded fields and scope are in [security-evidence.json](security-evidence.json); it verifies no-op startup only, not file access or complete containment. Baseline: [security-baseline.md](security-baseline.md). Setup and operational
limitations: [windows-security.md](windows-security.md). Machine-readable retained
results with per-call audit IDs: [security-evidence.json](security-evidence.json).

## Results and compliance matrix

PASS means the stated scope has runtime evidence. PARTIAL means implementation or
a narrower layer is verified with remaining gaps. UNVERIFIED means the required
runtime evidence is unavailable. FAIL means an explicitly required capability is
absent or incompatible; it does not imply a demonstrated successful attack.

| PS01 requirement | Status | Source and evidence | Remaining gap / actual side effects |
|---|---|---|---|
| Preserve existing application | PASS | `src/main.tsx`, existing backend; baseline 48 tests; expanded 60 tests; build and three browser suites pass | Browser REST/WS traffic is mocked; it proves no live provider behavior |
| Custom open-weight agent | PARTIAL | `backend/app/ollama_session.py`; parser/gateway regression test | Real Ollama attempt: WinError 10061; no model turn or normal task completed |
| Shell/read/write/HTTP tools | PARTIAL | `tool_gateway.py`, `sandbox_worker.py`; real gateway replay | Four normal tasks NOT_TESTED due missing worker setup. Writes create new files only |
| Every custom tool gated before execution | PASS | strict tool schemas, normalization, policy and correlated audit IDs; deterministic replay | Scope is custom adapter. Legacy CLI hooks/ACP callbacks remain cooperative |
| ALLOW/BLOCK/ASK and timeout | PASS | existing approvals plus new wait/recheck tests | Human decision ownership is still the local dashboard trust model; local API is not authenticated against same-user malware |
| Workspace/credential policy | PASS | eight replay policy rejections with no receiver delivery or outside fixture modification | This is application policy only; rejection of shell grammar is not resource containment |
| OS filesystem/process boundary | PARTIAL | `windows_sandbox.py`, `setup_windows_sandbox.py`, worker token self-check; user-provided `check_sandbox.py` output verifies AppContainer token, SID, Job membership, non-elevation, zero capabilities, effective limits, and cleanup | Startup only; workspace read/write denial, child attack probes and independent containment still unverified |
| Restricted token, SID and ACLs | PARTIAL | suspended launch checks AppContainer SID, zero capabilities, non-elevated token; scoped setup ACLs | Setup not applied. Effective ACL-denial and enabled-privilege tests outstanding; AppContainer is not LPAC |
| Child-process containment / no handle inheritance | UNVERIFIED | launcher passes FALSE for handle inheritance, no job breakaway flags, waits for zero active processes | Descendant escape probes have not run successfully |
| OS default-deny outbound network | UNVERIFIED | zero-capability AppContainer design; no unrestricted fallback | No proven IPv4/IPv6, localhost, DNS-service or proxy-bypass denial. No firewall rules changed |
| Approved destination mediation | PARTIAL | exact origin/IP broker; real local POST integration test receives FAKE_ONLY | Broker verified on host, not proof of worker network denial; origin grants include every path |
| DNS exfiltration | UNVERIFIED | unknown-origin policy replay blocks before DNS; raw UDP fixture probe exists | No resolver-level DNS containment evidence; DNS failure is never counted as success |
| CPU / memory / process / wall-time limits | PARTIAL | Job Object hard CPU cap, aggregate memory and process count, launch deadline and cleanup code | Only configuration calls reached before failed launch. Exhaustion fixture results and CPU throughput remain unverified |
| Complete-record audit hashing | PASS | `audit.py`, `test_security_upgrade.py`: metadata/payload edits, middle/tail/all deletion, ID reorder, migration tests | Legacy v1 timestamp/type/decision remain unauthenticated |
| Truncation / full-chain rollback | PARTIAL | sidecar catches DB-only truncation; independent-checkpoint test detects replacement chain | Co-located anchor can be rewritten by privileged attacker; external custody/manual export required |
| Protect audit from sandbox / deletion | PARTIAL | HTTP deletion disabled and tested; explicit profile SID deny in setup | Setup ACLs not applied or tested with actual worker; trusted local operator retains filesystem access |
| Dashboard calls, normalized targets, reasons, IDs, status | PASS | `security_event` WS handling, audit detail view, enforcement panel and recorded-results endpoint | OS/network/resource events cannot be demonstrated live until worker launch succeeds |
| Accurate blocking attribution | PARTIAL | policy vs execution failure vs NOT_TESTED; deadline event code; legacy CLI labels retained separately | MODEL_REFUSAL is not inferred from mere absence of calls; live model refusal classification/manual review outstanding |
| 3–5 normal tasks | UNVERIFIED | four deterministic fixtures: read, create, shell location, local HTTP; no-op worker startup now passes in user account | No normal file/shell/HTTP tool call has yet completed in the isolated worker |
| 5–8 attack scenarios | PARTIAL | eight deterministic scenarios recorded with calls, IDs and side-effect checks | Only policy layer tested; indirect injection replay is its unsafe follow-up, not a live compromised-model demonstration |
| Agent-driven attack path | UNVERIFIED | `security_harness.py --agent`, twelve prompts defined | First provider connection refused; remaining prompts not run |
| Direct bypass of policy / OS tests | UNVERIFIED | `--os-probes`: static fake-file/network/memory/process/deadline programs | Setup unavailable; no claims based on skipped probes. IPv6, DNS port 53/service, CPU throughput coverage still missing |
| Windows-only | PASS | Python/Win32/PowerShell; no Linux runtime introduced | Requires Windows 10/11 and operator profile/ACL provisioning |
| Docker read-only root, Linux capabilities, seccomp, cgroups | FAIL | Deliberate Windows-only constraint | Not implemented, not equivalent to AppContainer/NTFS/Job Objects. Must disclose this PS01 deviation |

## Reproduction

```powershell
npm.cmd run build
python -m unittest discover -s backend -p 'test_*.py'
python -m http.server 5174 --bind 127.0.0.1 --directory dist
```

In a second terminal:

```powershell
$env:AGENTGUARD_CHECK_URL='http://127.0.0.1:5174'
npm.cmd run test:browser
npm.cmd run test:responses
npm.cmd run test:terminal
```

These suites mock REST/WebSockets and do not manipulate real sessions. The browser
clear-log regression was updated to verify deletion is disabled while retaining
compatibility with an old backend's clear notification.

Run the real replay on new disposable fixtures:

```powershell
python backend/security_harness.py --prepare --replay
python backend/security_harness.py --root "<printed-root>" --os-probes
python backend/security_harness.py --root "<printed-root>" --agent
```

Provision AppContainer and start Ollama according to the setup guide before expecting
normal task success. The harness never auto-approves a real ASK. Its isolated test
policy explicitly allows eligible operations so normal tests can run unattended;
production default Ask is unchanged. Reports are timestamped under the fixture root.
Failed provider startup stops the remaining model prompts instead of inventing results.

Recorded local fixture: `.qa/security-483e94e6`. Latest replay has eight policy-layer
PARTIAL scenarios and four UNVERIFIED normal tasks. Audit verified. No outside-write
fixture appeared, fake audit file stayed unchanged, no HTTP or DNS delivery occurred
in that replay. Absence of delivery is paired with policy rejection, not claimed as
independent OS network enforcement. A separate broker integration test intentionally
delivered one fake local POST. The ambient-token worker startup test failed before
opening any request/result files, as required.

## Honest live demonstration

1. Show this matrix and the retained evidence date before demonstrating.
2. Under the normal Windows account, provision a disposable workspace; verify the
   worker token, ACL, network and resource probes. Stop if setup/launch is unavailable.
3. Start Ollama and AgentGuard; select the custom Ollama adapter. Show enforcement
   details and **View retained test results**, noting these are recorded results.
4. Run the four normal tasks and verify their actual files/receiver deliveries.
5. Switch a workspace read rule to Ask, submit a read, show it waiting, then approve
   it. Repeat with Block and timeout. Inspect correlated policy/approval/result IDs.
6. Run direct replay, then live injection prompts. A model refusal is not a sandbox
   win. Show unsafe requested calls, actual blocking layer and fixture observations.
7. Run policy-bypass OS probes separately; show the effective token/job and receiver
   evidence. Do not substitute a policy rejection for an OS denial.
8. Export SQLite plus checkpoint, verify the chain, and demonstrate tamper detection
   on a copy only. State Docker/Linux-specific expectations are unmet.

Until the outstanding runtime checks succeed, this is a partial implementation
demonstration, not a secure-sandbox success demonstration.
