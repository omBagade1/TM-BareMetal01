# Built-in skill access

The `allow-cli-builtin-skills` policy rule automatically permits `view_file`
and `read_file` for existing files in the backend account's
`~/.gemini/antigravity-cli/builtin/skills/` folder. Disable this rule in Policy
to remove the exception. Earlier explicit rules still take precedence.

The `builtin_skills: true` matcher checks absolute paths after resolving links
and traversal. Every recognized path argument must qualify. A junction that
redirects the installed root elsewhere does not qualify. Writes, missing files,
directory listings, and recursive searches receive no exception. Credentials
and other configuration files outside the workspace remain outside this grant.
Legacy rules named `allow-cli-builtin-skills` receive the same containment check.

New sessions default to requesting CLI OS sandbox mode. This flag is separate
from permissions and is not proof of project-controlled container or network
containment. Live command requests have failed with sandbox both enabled and
disabled. Shell commands retain their policy approval checks.
Restart the backend and refresh the browser to load these changes; running CLI
sessions retain the sandbox mode with which they started.

The hook translates backend `block` to CLI `deny`. After a `run_command` action is approved, it sends the documented `permissionOverrides` field with the full command target for that invocation. This has not resolved the observed live command denials. The skill exception itself changes no global CLI permissions and enables no skip-permissions flag. The separate listing setup does add a single fixed-helper grant; see [CLI listing setup](cli-listing-setup.md).
