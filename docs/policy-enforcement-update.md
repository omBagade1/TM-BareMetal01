# Policy and chat enforcement update

Reference documents were copied from `C:/Users/Akhilesh/Downloads/jnec` into
`docs/reference-jnec`, with SHA-256 digests in `manifest.json`. They are historical
context, not proof of current containment. Current implementation and test evidence
take precedence over older claims and metadata auto-approval instructions.

The PS01 problem statement requires allow/block/ask decisions with reasons, workspace
boundaries, network allowlisting, resource containment and a visible audit trail.

The default policy now blocks unmatched actions. An explicit
`review-workspace-operations` Ask rule permits review of normal workspace reads,
listings, edits and eligible commands. Hard path, credential, command and Ultra
Security restrictions run first and cannot be overridden by human approval.
Removing or disabling that rule blocks those operations unless another rule applies.

Unknown tools and browser JavaScript are hard-blocked. HTTP must pass the custom
gateway's exact-origin/IP network broker before policy can permit it. Legacy hook
and ACP HTTP calls do not acquire broker permission from model-supplied arguments.

Custom-agent policy blocks now publish `action_issue` with the persisted audit row,
matching the CLI paths. Chat displays “Action blocked by AgentGuard”, the tool,
reason and audit link. Rejected approvals, timeouts and policy rechecks retain their
actual reasons. A model declining an injected instruction without attempting a tool
is not fabricated into a policy block.

These changes enforce mediated tool requests. They do not establish complete PS01
compliance: legacy CLIs are cooperative adapters, not isolated workers; independent
OS/network/resource containment evidence and provider-backed attack trials remain
necessary. See the imported security report for the documented gaps.

## Source content inspection

`content_guard.py` now inspects bounded workspace `view_file`, `read_file` and
validated `Get-Content` requests before policy rules or approval. A combination
of a parent-relative read instruction, an HTTP send/upload instruction, and a
task-override or concealment instruction blocks the source read under
`__content_inspection`. This catches the vendor-note fixture regardless of its name.
The existing hook/gateway block path supplies the reason, chat notice and audit ID.
The notice describes a blocked source read, not an upload that never occurred.

This conservative heuristic can also block quoted examples and security training
material. It is not a semantic prompt-injection classifier and does not cover all
encodings, search-tool output, fetched pages, cached model context or transformed
payloads. Ordinary tool boundaries remain necessary. Files over 64 KiB and failed
inspection are blocked; the narrow installed-skill exception remains unchanged.
Restart the backend and start a fresh CLI session when testing, so previously read
content is not already present in the agent's context. Historical events are unchanged.
