# Windows security setup and execution contract

This upgrade is **PARTIAL, not a certified sandbox**. Read
[security-report.md](security-report.md) and [retained evidence](security-evidence.json).
The custom execution path fails closed without a working AppContainer. Existing
Agy/ConPTY/Gemini ACP adapters remain available for development and are **not**
covered by the new worker boundary. Never use them as PS01 isolation evidence.

## Architecture

React -> FastAPI -> OllamaSession -> ToolGateway -> existing PolicyEngine ->
ApprovalManager -> WindowsSandbox -> private Python worker. Every custom tool
passes strict schema validation, normalization and policy evaluation. Unknown tools,
extra keys, unsupported shell syntax, credential/control paths, links, reparse points
and hard links are rejected. The shell grammar remains deliberately narrow.
File writes exclusively create new files; there is no overwrite capability.

The trusted launcher sets a minimal environment, passes no inherited handles,
uses a per-workspace AppContainer SID with **zero capabilities**, and creates the
worker suspended. It assigns a Job Object, inspects the effective AppContainer SID,
elevation state, capability count and job membership, then resumes. Job limits are
read back before execution: 20% CPU hard cap, 256 MiB process and job memory,
four active processes, 15-second deadline. No breakaway flags are enabled. Parent
completion or timeout terminates the whole job; active process count must reach
zero before results are read. The worker separately refuses ambient-token startup.
This is source implementation, **not evidence that these controls worked here**.

AppContainer supplies the restricted token boundary; a separate CreateRestrictedToken
path is not implemented. AppContainer is not LPAC: some Windows resources granted
to ALL APPLICATION PACKAGES remain readable. It does not provide an exclusively
workspace-visible filesystem, a private kernel, or a Linux read-only root mount.

## Explicit operator setup

For the configured project workspace, stop AgentGuard and double-click
`setup-agentguard-sandbox.cmd` in File Explorer under your normal Windows account.
It prints the scope, provisions it, and runs `backend/check_sandbox.py`. The window
stays open on failure so you can copy the actual error. It respects
`AGENTGUARD_WORKSPACE` and `AGENTGUARD_DATA`; defaults are `workspace` and `data`.
Use `setup-agentguard-sandbox.cmd --plan` to print the scope without applying it.
Restart AgentGuard only after the worker startup check succeeds. This is a startup
check, not proof that all containment tests pass.

Use PowerShell under the normal Windows account. Do not run setup inside the
restricted coding-agent context. No command below requests elevation, changes the
global firewall, installs a Linux backend, or modifies credential permissions.
Setup creates a Windows AppContainer profile and changes ACLs on the printed paths.
Review `--plan` before `--apply`. If Windows denies an operation, stop and investigate;
there is no unrestricted fallback. Enterprise ACL/profile policies may require an
administrator to provision these exact resources. Do not grant broad runtime writes.

First use a disposable fixture workspace:

```powershell
python backend/security_harness.py --prepare
python backend/setup_windows_sandbox.py --workspace "<printed-root>\workspace" --audit-dir "<printed-root>\replay" --plan
python backend/setup_windows_sandbox.py --workspace "<printed-root>\workspace" --audit-dir "<printed-root>\replay" --apply
python backend/security_harness.py --root "<printed-root>" --replay
python backend/security_harness.py --root "<printed-root>" --os-probes
```

Setup grants the unique workspace SID Modify on that workspace and a sibling
control/temp directory, Read on the fixed worker script, and a low integrity label
on the two writable directories. It explicitly denies that SID access to the audit
directory and workspace control folders. Other ACL entries are retained. Python
and its standard library must already be executable/readable by AppContainer.
**Do not fix runtime access by granting write access to Python or backend code.**

The worker can write its per-profile Windows AppContainer storage in addition to
the explicitly granted workspace/control directories. Disk quotas are not implemented.
Do not run two backends against the same sandbox workspace/profile concurrently.
The trusted backend and operator must not race filesystem modifications with calls.

If setup reports successful ACL changes but worker startup fails with WinError 203,
run `python backend/check_sandbox.py` with the current launcher code. The launcher
now supplies LOCALAPPDATA, APPDATA and USERPROFILE from the registered AppContainer
folder while retaining an explicit environment allowlist. It does not inherit host
credentials or proxies. Windows redirects profile-related environment variables
during AppContainer startup. This change addresses a suspected bootstrap issue;
success must still be confirmed by the no-op worker check under the normal account.
GetAppContainerFolderPath errors identify a missing/inaccessible registration for
the current account separately from CreateProcessW failures. Do not reapply ACLs
to fix an environment error or switch to an unrestricted process fallback.

If worker launch succeeds but exits 1 without a result, check for the Python 3.13
temporary-directory ACL regression. `TemporaryDirectory` uses mode 0700, which
removes the inherited package grant on Windows. The launcher now adds only the
workspace AppContainer SID to each private per-call directory; request/result files
inherit that grant. A Windows regression test verifies both directory and file ACLs.
The fixed worker bootstrap also captures bounded startup stderr without inheriting
backend handles. Re-run `python backend/check_sandbox.py`; no profile/ACL setup
rerun is necessary for this code fix. A successful probe still needs actual file
and independent containment verification. See [Python's Windows mkdir behavior](https://docs.python.org/3.13/library/os.html#os.mkdir).

Setup is additive and is never run automatically by backend startup. Save the
printed SID and an ACL backup before applying it to a non-disposable workspace.
For rollback, stop workers, remove only that SID's grant/deny entries from the
printed resources using `icacls <exact-path> /remove <SID>`, and restore the prior
integrity labels from your ACL backup. Remove only the corresponding AppContainer
profile using Windows `DeleteAppContainerProfile` with the exact printed name.
No bulk profile/firewall cleanup is provided. Retained `.qa` fixtures can be removed
by the operator after evidence export. Do not recursively delete computed paths.

## Local open-weight model

Install Ollama for Windows separately and obtain `qwen3:4b` or `qwen3:8b` under the
normal account. Model acquisition requires outbound networking and disk space;
it was not performed in this restricted session. The model service is trusted
infrastructure outside the tool sandbox and receives approved tool results.

```powershell
ollama pull qwen3:4b
ollama serve
```

If Ollama already runs in the tray, use that service instead of starting another.
The custom agent calls `127.0.0.1:11434/api/chat`; configure another loopback port
with `AGENTGUARD_OLLAMA_PORT`. Set `AGENTGUARD_OLLAMA_MODEL` for the API default,
or select Qwen3 4B/8B in the dashboard. No prompt can change the endpoint. Limits:
eight iterations, four calls per iteration, 240-second turn budget, 60-second model
request timeout, bounded context/output. Cancelling a turn waits for active worker
cleanup. Inference requests running in a thread may finish after cancellation but
their returned tool requests are discarded.

For dashboard use, provision the configured workspace with the **actual** audit
directory (normally `data`), then launch `start-agentguard.cmd` under the normal
account. After backend edits restart that launcher; after frontend edits run
`npm.cmd run build`. Select **Custom agent (Ollama / AppContainer)**. Existing
default CLI selection is retained for compatibility. The CLI sandbox checkbox
does not control or disable custom-agent isolation.

## Network contract

Workers receive no network capabilities. No firewall exemptions or global rules
are created. AppContainer capability enforcement is the proposed independent
network boundary; live IPv4/IPv6, DNS and loopback-bypass verification remains
outstanding. In particular, zero capabilities must **not** be assumed to prove
that every Windows DNS client-service path is blocked. Existing loopback exemptions
or grants to this profile invalidate assumptions and must be investigated.

HTTP uses a trusted broker after the same policy/approval gate and a worker readiness
probe. Default allowlist is empty. Configure exact origins mapped to numeric IPs:

```powershell
$env:AGENTGUARD_HTTP_DESTINATIONS='{"http://fixture.test:19888":"127.0.0.1"}'
```

The broker pins connections to operator-provided addresses, preserves the Host
header and TLS hostname validation, never resolves model-supplied names, ignores
environment proxies, accepts only GET/POST and bounded text bodies, and does not
follow redirects. Every scheme/host/port must match exactly. IPv6 literals use
bracketed origins. Loopback AgentGuard/inference default ports are forbidden even
if listed. Other local control services must not be allowlisted. Allowlisting an
origin authorizes all its paths; this is not a per-path data-loss-prevention policy.
Broker transport/TLS/DNS errors are not NETWORK_BLOCK evidence. The inference service
and HTTP broker are trusted host processes, not AppContainer workers.

## Audit

New SQLite rows use version 2, hashing canonical ID, timestamp, event type, decision,
previous hash and complete payload (reasons, arguments, outcomes and metadata).
Version 1 rows remain unchanged and are counted explicitly. Tool calls correlate
requested/normalized arguments, policy, approval and result IDs. Write/HTTP bodies
are stored as length + SHA-256, not plaintext; model output/file content is not in
gateway execution-result events. The existing legacy audit may contain old content.

The `.head` sidecar records the committed ID/hash and detects database-only tail
truncation. A missing/mismatched anchor fails verification and prevents further
appends. A crash between DB commit and anchor replacement can cause this condition;
preserve both artifacts and investigate offline. There is no automatic repair that
would silently bless tampering. SQLite and sidecar must have a single backend writer.

HTTP DELETE `/api/audit` returns 403; the Clear log button is disabled. The internal
`Audit.clear()` method remains for tests/offline compatibility, not a public API.
Copy the `.head` checkpoint to independently controlled storage before a demo, then:

```powershell
python backend/verify_audit.py "data\audit.db" --checkpoint "<independently-retained-checkpoint>"
```

The verifier is read-only. An old checkpoint authenticates its prefix, not a later
tail. A hash chain and co-located sidecar cannot defeat an administrator rewriting
both, whole-directory rollback, or deletion of all copies. No remote notarization
service, signing key custody or automatic external checkpoint delivery is implemented.

## API references

- [Microsoft AppContainer isolation](https://learn.microsoft.com/en-us/windows/win32/secauthz/appcontainer-isolation)
- [Microsoft AppContainer launch guidance](https://learn.microsoft.com/en-us/windows/win32/secauthz/implementing-an-appcontainer)
- [Microsoft Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)
- [Ollama tool calling](https://github.com/ollama/ollama/blob/main/docs/capabilities/tool-calling.mdx)
