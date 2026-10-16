# Narrow CLI listing permission

Run `enable-cli-listing.cmd` once from File Explorer under your normal Windows
account. It preserves existing agy settings, backs up changed settings, and adds
one permission: execution of this application's `list-workspace.cmd` helper.
It does not grant `ls`, `Get-ChildItem`, `python`, or arbitrary shell execution.

## Verified status (2026-10-11)

Setup was confirmed applied: the CLI allow list contains the fixed helper grant
and `data/listing-access.json` exists. A subsequent prompt, "strictly use 'ls'
command and tellme output", was approved in AgentGuard (audit #429) but denied
by agy (#430). Those audit IDs may no longer exist after Clear log.

That request requires a different command from the helper, so the installed
grant does not cover it. Neither sandbox mode nor the hook's permission override
has resolved general shell approvals. A successful live agent turn invoking the
helper itself has not yet been demonstrated. Do not keep reinstalling this same
grant expecting it to enable `ls`.

## Helper scope

The helper uses an absolute Python interpreter path and a fixed workspace saved
by setup. It ignores wrapper arguments, rejects Python-script arguments, does not
read file contents, skips symlinks/reparse points, and limits enumeration to 1,000
entries. It cannot accept a different directory from the agent. Its executable,
script, and configuration are outside the approved agent workspace. Keep them
there; do not widen the workspace to include the application installation.

Then restart AgentGuard with `start-agentguard.cmd` and start a new CLI session.
On its first message the backend provides the helper command as environment
guidance to agy. The user's prompt is preserved in the audit. The agent must run
the helper and report its real output; results are not fabricated or inserted
as if they came from the model.

AgentGuard permits the exact helper invocation only with a working directory
inside the configured workspace. Extra command text, outside working directories,
daemon mode, and sandbox bypass are blocked. Explicit user block rules still
take precedence over automatic helper approval. Other shell commands retain
their existing policy and CLI permission checks.

The CLI grant is in the user's global settings but targets only this fixed helper.
It may therefore also be invoked from other CLI projects; it still lists only
the configured AgentGuard workspace. Remove the specific helper entry from
`permissions.allow` to revoke that capability. Existing CLI deny/ask rules are
preserved and may still override the added allow rule.

Preview the change without writing settings:

```powershell
python backend/configure_cli_listing.py
```

This setup and its tests do not establish a successful provider-backed CLI turn.
After setup, verify the exact user prompt and check the recorded tool result.
