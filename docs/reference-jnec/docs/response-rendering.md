# AgentGuard response rendering

Agent responses use the existing React chat and WebSocket transport. User messages stay plain text. The backend, audit records, approval flow, and original Markdown source are unchanged.

## Implementation

| File | Purpose |
| --- | --- |
| `src/components/ChatMessage.tsx` | Memoized message wrapper; lazy-loads the response renderer. |
| `src/components/ResponseRenderer.tsx` | Markdown, GFM, math, safe links, streaming completion, response copy/download. |
| `src/components/CodeBlock.tsx` | Language label, horizontally scrolling code, debounced highlighting, copy action. |
| `src/components/CopyButton.tsx` | Clipboard action with success and retry feedback. |
| `src/components/ThemeSelect.tsx` | Light, dark, and system theme preferences, persisted locally. |
| `src/rendering/highlight.ts` | On-demand Shiki engine and explicit language grammar imports. |
| `src/rendering/rich-content.tsx` | Validated notice/disclosure data and explicit React component registry. |
| `src/response.css` | Scoped response typography, tables, math, code, and structured content. |
| `src/theme.css` | Application theme overrides and conversation layout. |
| `src/main.tsx` | Integration, streaming state, optimistic user messages, bottom-follow scrolling. |
| `src/style.css` | Narrows existing message selectors so they do not override formatted prose. |
| `tests/response-browser.mjs` | Browser regression coverage using mocked API/WebSocket events. |
| `package.json`, `package-lock.json` | Renderer dependencies and test command. |

The design retains navy, blue, and slate tones. Prose has a 72-character maximum reading width, distinct heading sizes, and restrained code/table surfaces. Code and tables scroll within their containers. The scroll position follows output only while near the bottom; **Jump to latest** restores following. Font size and line spacing remain consistent during highlighting.

## Libraries

- [React Markdown](https://github.com/remarkjs/react-markdown) renders Markdown as React elements, with raw HTML disabled.
- `remark-gfm` supplies tables, nested/task lists, strikethrough, and automatic links.
- `remend` completes unfinished formatting for the streaming view only. Copy/download retain the original source.
- `remark-math`, `rehype-katex`, and `katex` render `$inline$` and `$$` display math, with bundled fonts and untrusted math commands disabled.
- `shiki` supplies syntax tokens, rendered as React spans instead of injected HTML. Its engine and individual grammars load only when requested.

Completed messages are memoized. Active Markdown uses React deferred rendering. Code tokenization is delayed 120 ms and falls back to readable plain code while loading or if it fails. Code over 30,000 characters is kept plain to avoid expensive highlighting.

## Safe structured content

An optional `agentguard-json` fenced block accepts exactly two component types. It does not evaluate HTML, JavaScript, component names, or expressions.

````markdown
```agentguard-json
{"type":"notice","tone":"info","title":"Review required","body":"Read the arguments before approving."}
```

```agentguard-json
{"type":"details","title":"Additional context","body":"These files are inside the workspace."}
```
````

Notice tones are `info`, `success`, or `warning`. Titles are limited to 180 characters, bodies to 12,000, and source blocks to 20,000. Unknown types, invalid field types, or malformed data remain visible as code. All title/body content is rendered as text.

## Security and limits

- HTML in Markdown is not enabled. There is no `dangerouslySetInnerHTML` in the response components.
- Links permit HTTP, HTTPS, mailto, and simple fragment URLs. External links use `noopener noreferrer` and no referrer. Relative/local filesystem links are shown as text.
- Markdown images become explicit image links; no remote image is fetched automatically.
- KaTeX runs with `trust: false`, bounded expansion, and bounded size. Invalid expressions have a readable error fallback. Parenthesized TeX delimiters (`\(...\)`) are not converted; use dollar delimiters.
- Highlighting supports JavaScript, TypeScript, JSX, TSX, Python, JSON, Bash, PowerShell, CSS, HTML, SQL, and YAML, including common aliases. Fence language labels select grammars; unlabeled/unsupported code stays plain rather than guessing its language.
- Mermaid, charts, and arbitrary interactive tables are not implemented. Mermaid and unknown fences remain copyable source. Tables are semantic and scrollable.
- Chat remains live-only and resets on reload, as before. This change does not add history persistence.

## Verification

Build and serve the static dashboard without starting a real CLI session:

```powershell
npm.cmd run build
python -m http.server 5174 --bind 127.0.0.1 --directory dist
```

In another terminal:

```powershell
npm.cmd run test:responses
$env:AGENTGUARD_CHECK_URL='http://127.0.0.1:5174'
npm.cmd run test:browser
```

Chrome must be installed; `CHROME_PATH` overrides its executable. Tests use mocked REST and WebSocket responses and do not use CLI authentication or affect a real session. Screenshots are saved under ignored `.qa/`.

Verified in Chrome: H1–H6, inline formatting, nested and task lists, quotes, dividers, tables, inline/display/invalid math, all supported syntax grammars, code whitespace, real clipboard success, simulated clipboard rejection, downloads, unsafe link/HTML rejection, no image tracking requests, structured validation, incomplete bold/links/code, 100-paragraph streaming, retained scroll position, jump-to-latest, persisted themes, and no page overflow at 1024/768/390 pixels. Desktop and mobile screenshots were visually reviewed. Existing start/send/stop/restart browser regression checks also pass. TypeScript checks run as part of the production build. No lint script is configured.


## Action notices and final answers

The backend broadcasts `action_issue` with the saved audit record for policy blocks, human blocks, approval timeouts, and CLI tool errors. Chat displays these as plain-text AgentGuard notices, separate from model output. Inspect audit opens and focuses the matching record, retaining it even if it has left the latest 200 events. Notices are deduplicated by audit ID and remain live-only. Events missed while disconnected are available in Audit trail.

A DONE update finalizes streaming even without a text delta. Result-only answers appear in chat; final answers that extend the last streamed response complete that message, identical answers are deduplicated, and distinct final answers appear after earlier progress messages. Browser tests cover these paths along with block notices and audit navigation.

CLI-denial cards use **Action not permitted** and **View details in audit**. Raw
CLI error text and internal instructions remain in the audit; agy's own output
provides any conversational explanation. The CLI may return an empty response
and `denied_actions` even with result status `SUCCESS`. This is not proof that
the requested task completed. Its "user denied" text can follow an Allow click
in AgentGuard because CLI permissions are evaluated separately.

The native **List files** action renders an explicitly labeled AgentGuard
workspace table using escaped text, not a model-generated reply. The desired
chat UX still depends on verifying real agy tool execution and final output.

**Clear log** permanently removes saved audit entries after confirmation.
Connected clients discard selected/cached records and action notices through the
cleared event ID. Other conversation messages remain; new events continue to be
recorded. Export JSON covers the loaded audit records, not an unlimited archive.
