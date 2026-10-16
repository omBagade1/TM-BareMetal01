# Command eligibility and hard policy boundaries

Human approval only applies to an eligible operation. A Block from the hard
boundary cannot be changed to Allow by the approval queue, `default_action`,
or a permissive explicit rule. These checks also apply to existing policy
files, without resetting the user's configured rules.

## Supported shell operations

`run_command` and recognized execution-tool aliases are checked before normal
policy rules. The supported grammar is intentionally small:

- `Get-ChildItem` with at most one literal workspace path and optional `-Force`,
  `-Name`, `-File`, `-Directory`, `-Path`, or `-LiteralPath`. Bounded recursive
  directory listings support `-Directory -Depth 0..3` with optional `-Recurse`;
  combining this with `-File` is blocked. A metadata preflight rejects links/
  reparse points and scans beyond 2,000 entries or two seconds. No file contents
  are read by this check. Descendant directory names can be listed without
  granting access to their protected contents.
- A validated `Get-ChildItem` may pipe to exactly `Select-Object Name`,
  `Select-Object -Property Name`, or `Select-Object -ExpandProperty Name`.
  Other pipeline stages, computed properties and added commands stay blocked.
- `Get-Location` and `pwd` without arguments report the validated working directory.
- `Get-Content` with one existing regular workspace file, optional `-Raw`,
  `-Path`, or `-LiteralPath`.
- `Remove-Item`, `del`, and `rm` with one existing regular workspace file, optional `-Force`,
  `-Path`, or `-LiteralPath`. Directory deletion, wildcards, recursion, and protected paths remain hard-blocked.
- The existing configured fixed metadata helper retains its separate exact
  command and workspace checks. An explicit policy block still overrides it.

### Security modes (Standard vs. Ultra Security)

- **Standard Mode (`ultra_security: false`)**: Targeted single regular file deletions inside the approved workspace route to human review (`ask` under `__workspace_file_delete`). Dangerous commands, wildcards, directories, recursion, and protected paths remain hard-blocked.
- **Ultra Security Mode (`ultra_security: true`)**: All destructive commands and file deletions are unconditionally hard-blocked at the policy boundary (`__ultra_security`) without creating approval requests. Non-destructive reads and listings remain active according to policy.

A command must have an absolute workspace `Cwd`. Missing/ambiguous paths,
outside paths, provider paths, alternate streams, wildcards, links/reparse
points, hard-linked files, unbounded recursion, persistent terminals, and sandbox
bypass requests are blocked. Operators, substitutions, comments, general pipelines,
redirection, scripts, encoded commands, wrappers and unknown commands are also
blocked. No regular-expression denylist or model judgment is used to approve
arbitrary shell syntax. Use structured workspace file tools for unsupported
work instead of rephrasing a denied action.

Explicit Allow/Ask/Block rules remain authoritative. When no rule matches,
all eligible operations follow the configured default, including metadata
commands, the fixed listing helper, and the dashboard List files action.
With default Ask these operations wait in AgentGuard's approval queue for
Allow or Block. agy's native confirmation remains independent and may still
require a separate decision.

## File boundaries

Recognized file tools check every recognized path argument, using a validated
working directory for relative targets. Missing, malformed, outside-workspace,
and linked targets are blocked before configurable rules. Environment files
(`.env`, `.env.*`, `*.env`), private-key extensions, common credential files,
and `.ssh`, `.aws`, `.azure`, `.gemini`, `.codex`, `.agents`, and `.git` paths
are protected even inside the workspace.

The installed built-in-skill exception remains read-only, limited to resolved
existing files under its fixed location. Protected names and hard-linked files
do not qualify. This is the only existing external file exception preserved.

After a queued human Allow, the policy is evaluated again. If the path or
policy is now blocked, the hook returns Block and audits
`approval_recheck_blocked`. The earlier human decision is retained as history;
it is not presented as authorization to bypass the newer boundary.

## Verified scope and limitations

The regression for `Get-Content ..\\.env` verifies that the hook returns Block
and never creates a pending approval. Tests also cover supported workspace
operations, permissive rules, path traversal, compound/encoded commands,
multiple path arguments, hard links, and changes while approval is pending.
Tests use fixture contents, not the user's actual environment file.

This is a conservative tool-policy filter, **not OS isolation**. The CLI still
runs under the Windows account. Shell startup/profile changes, runtime command
resolution, filesystem changes after the hook returns, unrecognized tool
interfaces, and direct user operations outside hooked tool calls are not
contained by these checks. This does not establish PS01 container/network or
resource isolation. Supporting general builds, scripts, interpreters, or
network commands requires a separately verified execution sandbox.

Restart the normal-account backend and CLI session to activate this code.
The styling and interactive terminal transport are unchanged.

PowerShell parameter reference: [Get-ChildItem](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.management/get-childitem?view=powershell-5.1). The preflight budget limits the policy check, not the later CLI process; filesystem races and runtime resolution remain limitations.
