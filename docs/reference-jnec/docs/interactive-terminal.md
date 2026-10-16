# Interactive agy in the browser

The dashboard now defaults to **Antigravity CLI (agy) → Interactive CLI
(native permission options)**. The existing headless chat and Gemini ACP
providers remain available explicitly. Detecting Gemini on disk no longer
switches the selected provider.

## Start it

1. Stop any existing CLI session in the dashboard.
2. Close the old backend launcher terminal and reopen `start-agentguard.cmd`
   from File Explorer under your normal Windows account.
3. Refresh http://127.0.0.1:8912 and select the interactive interface.
4. Start a session. Click inside the terminal and type your task.
5. Use the options **actually displayed by agy**. The browser forwards typing,
   arrow keys, Enter, Escape, and Ctrl+C to the same interactive process.

`pywinpty>=3.0,<4` is included in `backend/requirements.txt` (Windows only).
Install that requirements file if starting the terminal reports it missing.
After frontend changes, run `npm.cmd run build` before refreshing.

## Approval behavior

This is a Windows ConPTY terminal running the installed `agy` executable,
without `--print` or `stream-json`. It is not an ACP adapter, and it does not
inject `y` into a headless process. Terminal escape sequences are rendered by
a local xterm.js copy; no remote terminal assets are loaded.

The existing AgentGuard PreToolUse hook applies allow/block/ask policy.
Every Ask, including interactive commands, waits in AgentGuard's own approval
queue. Allow releases the hook; Block and timeout deny it. The CLI can still
ask its own permission after AgentGuard Allow. There may therefore be two
reviews. The bridge makes the native prompt answerable in the browser but
does not synchronize the two approvals.

**Live regression, 2026-10-11:** audit #537 recorded native delegation with
`force_ask`, while the retained terminal output showed the requested directory
listing completed. The user reported that no permission prompt appeared.
The documented directive did not establish a reliable human review gate in
this installed CLI/context. Delegation has been removed. The hook now rejects
`force_ask` responses, including those from an old backend that has not yet
restarted. It fails closed until that backend is restarted.

An audit `approval_delegated` record is not evidence of human approval. Keep
historical records intact. Do not reintroduce native-only Ask handling based
on documentation or mocked tests. AgentGuard's real approval queue is tested
for pending, human Allow, human Block, and timeout with an interactive session.

Native CLI menus are displayed verbatim, including any persistent-grant
choices that agy itself offers. The bridge neither creates these choices
nor selects one automatically. It does not scrape prompt text to infer an
approval ID. No skip-permissions setting or global allow rule is added.

## Lifecycle and boundaries

- A session-specific WebSocket accepts only explicit trusted browser origins.
  Input to an old session ID cannot reach a replacement process.
- The first attached browser controls input and resizing. Other browsers are
  read-only. When the controller disconnects, a remaining browser is promoted
  and notified automatically, including overlapping refresh/remount connections.
  Use Take control to explicitly move input ownership to a different browser;
  the old browser immediately becomes read-only. Reconnect never replays input.
  Clicking anywhere inside the terminal or Focus terminal focuses keyboard input.
- Disconnecting or switching dashboard tabs does not stop agy. Stop session
  terminates the CLI process tree. Starting a second session while one is
  running is rejected.
- The backend retains up to two million characters of terminal output in
  memory for reconnects. Older history may be trimmed; it is not a durable
  transcript. Resize/redraw behavior is controlled by agy.
- Terminal text is not HTML. OSC clipboard operations and terminal-provided
  hyperlinks are disabled. No image/web-link addon is enabled.
- Hook policy decisions and lifecycle events remain audited. Native terminal
  keystrokes and permission selections are **not** parsed into audit decisions
  or written to disk. Do not claim the audit contains every CLI interaction.
- Structured Markdown chat rendering belongs to headless/ACP sessions. The
  interactive interface renders agy's terminal conversation and native menus.
- The sandbox checkbox only requests agy's sandbox; this bridge does not
  establish container/network containment on Windows.

## Verification

`python -m unittest discover -s backend -p 'test_*.py'` includes a real Windows
ConPTY round trip using a deterministic local menu fixture. It also checks
controller ownership, session isolation, origin rejection, bounded replay,
invalid input, and rejection of duplicate session starts.

Serve `dist` at port 5174, then run `npm.cmd run test:terminal`. This tests the
actual terminal renderer with mocked WebSocket/API traffic, option text,
exact key forwarding, read-only access, reconnects, non-executable HTML,
and mobile layout. Existing session/response suites use headless mode.

These checks do not prove a provider-backed agy tool turn. To verify that,
run from the normal-account launcher, request a harmless workspace listing,
approve the AgentGuard review, and if prompted choose the native agy Allow-once option
shown in the browser. Verify actual tool output. Repeat with a native deny
choice and confirm the tool did not execute. Do not replace an existing
normal-account backend with an agent-launched restricted process to do this.

See `src/vendor/xterm/README.md` for the local terminal library's provenance
and license. Package download access was unavailable during implementation.

## Terminal appearance

The terminal keeps agy?s native interface and wording, with larger, more widely
spaced text and an inset navy surface. Use the minus/plus buttons to adjust text
size and Expand terminal width to give long commands more space. These controls
resize the terminal without restarting the CLI or sending approval input.

## Command policy

Hard command/file boundaries now run before human review. Outside or protected
file access and unsupported shell syntax are blocked without an Allow button.
See [Command policy](command-policy.md) for the small supported grammar and
its limits; the terminal remains a normal-account CLI, not an OS sandbox.

## Block explanations

Denied hooks name AgentGuard, preserve the policy reason, and instruct agy to explain the block without bypassing the denied boundary. For syntax-only refusals, agy is instructed to continue with a supported equivalent under normal policy checks, without asking the user to repeat the task. Human blocks and approval timeouts are identified separately. This is guidance to the model, not a guarantee of its wording. The browser also shows the latest five action notices above the interactive terminal with reasons and audit links, independent of model output. Native CLI denials remain distinct from AgentGuard blocks. Notices are session-local and are not replayed on reload.

## Edge scrollbar

`src/components/ZipperScrollbar.tsx` overlays an existing native scroll viewport without intercepting terminal keystrokes. Terminal scrollback, conversation messages, and the page use the same component. A 17 ? 48 px handle straddles the container edge with a 44 px interaction rail; it moves inside when the viewport or an overflow-clipping ancestor cannot fit the outer interaction area. The page handle is always inside the screen. Resize and mutation observers track changing content, and native scroll events synchronize position. Pointer capture supports mouse, pen and touch; the focused scrollbar supports arrows, Page Up/Down, Home and End. Short content hides the rail. Existing light/dark themes are preserved.

`npm.cmd run test:terminal` covers alignment, bounds, rail clicks, wheel, keyboard, touch drag/cancellation, clipping fallback, and separation from CLI input using mocked transport and the real terminal renderer.

The shared `ScrollFrame` also adds both scroll axes to policy/argument/message editors, approval and audit detail panels, code blocks, tables, and display equations. Horizontal handles use Left/Right, Page Up/Down, Home and End. Editing and textarea resize controls stay native. Browser regressions cover editor value preservation and overflow hiding, horizontal code dragging/keyboard controls, and table scrolling.

## Copy and paste

Select terminal text, then use Copy selection or Ctrl+C (Cmd+C on macOS). Ctrl+C without a selection still interrupts the CLI; the Ctrl+C button always sends an interrupt. Paste uses the Paste button, Ctrl/Cmd+V, or Ctrl+Shift+V. Clipboard API denial shows a fallback message for native browser paste/copy. Pasted text goes through xterm newline/bracketed-paste handling and the existing input-size and session-ownership checks. Disconnected, ended, replaying and read-only sessions cannot receive pasted input. CLI-generated OSC 52 clipboard access remains blocked. Browser tests exercise selected-text copy, paste-button input, one-time native paste events, bracketed paste, and read-only rejection with mocked clipboard/transport.
