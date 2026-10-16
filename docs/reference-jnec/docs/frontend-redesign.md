# Frontend redesign

The existing Vite / React / TypeScript frontend keeps its four state-driven views: Workspace, Approvals, Policy, and Audit trail. There is no URL router or frontend sign-in flow. REST and WebSocket handling remain in `src/main.tsx`; the terminal keeps its separate WebSocket transport. No backend implementation or dependencies were changed.

## Design system

`src/design-system.css` provides the final presentation layer after the existing base and theme styles. It owns the navy/blue palette, light and dark surface tokens, system typography, spacing, component treatments, top navigation, and responsive layouts. The base styles retain the underlying component and scrolling contracts. `src/response.css` maps response surfaces to the same semantic tokens. Navigation, terminal chrome, and terminal output follow the selected theme. The terminal renderer updates its default and ANSI colors in place without reconnecting or clearing the session.

Controls use 6px radii; large panels use 12px. Blue identifies primary actions and selected navigation. Green, amber, and red are reserved for semantic states. No new dependencies, remote fonts, images, or motion libraries are required. Reduced-motion preferences disable the small heading entrance transition. The default theme still follows the system preference and the existing selector persists overrides.

The redesign covers navigation, workspace metadata, terminal/chat empty states, composer, session and provider controls, security settings, approval queue and decisions, enforcement evidence, policy editing and evaluation, audit details/export/verification, response tables, code blocks, and response actions. Existing disabled audit deletion remains disabled.

Session settings and enforcement evidence now occupy a collapsible left panel. The toggle and terminal expand/restore button control the same layout state; hiding settings preserves their values and the running terminal instance. On smaller screens, the panel stacks above the conversation. The permission queue is directly below the conversation and uses content-driven height: resolved requests disappear and the empty queue becomes a compact status strip. Terminal action notices follow the queue in a bounded scrolling area. These workspace-specific rules are in `src/workspace-layout.css`.

## Safety checkpoint

The working folder was not a Git repository. Before edits, frontend sources, package manifests, and the HTML entry point were archived to `.qa/redesign-baseline.zip`. No Git history was initialized and no existing work was discarded.

## Verification

Baseline: production build, 67 Python unit tests, and the existing session, response, and terminal browser suites passed. The Python run emitted an existing Starlette/httpx deprecation warning.

After the redesign, the production build and all three existing browser suites passed. The additional `node tests/redesign-browser.mjs` suite exercises:

- All four views at 320, 390, 768, 1024, and 1440px in both light and dark themes, with document overflow checks.
- Allow/block decisions and decision details.
- Invalid JSON rejection, policy saving/reloading/evaluation, and security-mode switching.
- Retained evidence, provider/interface controls, model selection, and chat suggestions.
- Audit verification/export and the disabled clear action.
- Current-page navigation semantics, skip-to-content, and reduced motion.

Screenshots are written to `.qa/redesign/`; desktop and mobile samples in both themes were visually inspected. The additional suite reports no browser console errors or warnings and checks keyboard activation and visible focus. API path references and package manifests were compared against the checkpoint and are unchanged. Existing suites cover session start/stop, streamed/final responses, copy/download, Markdown and math, output safety, scrolling, terminal input/control/replay, and disconnected states.

Browser tests mock REST/WebSocket traffic. They do not prove provider-backed CLI success, authentication, native permission integration, or OS containment. No real CLI session was started or existing backend restarted. Full assistive-technology and physical-device testing was not performed. There is no configured lint command.

## Files

- `src/main.tsx`: presentation structure, accessible navigation, composer hint, approval overview, and evidence styling hook.
- `src/style.css`: removed the remote font import.
- `src/design-system.css`: shared design tokens and all-view presentation.
- `src/workspace-layout.css`: collapsible left settings panel, wider conversation, and adaptive permission queue.
- `src/response.css`: response tokens and table/code/action styling.
- `src/components/InteractiveTerminal.tsx`: idle terminal presentation.
- `src/components/terminal.css`: terminal spacing and touch controls.
- `tests/redesign-browser.mjs`: additional responsive and workflow checks.
- `docs/frontend-redesign.md`: design and validation record.

Run `npm.cmd run build` after frontend edits. Refresh the existing application at `http://127.0.0.1:8912` to use the rebuilt assets.
