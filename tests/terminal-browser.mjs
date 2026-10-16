import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { chromium } from 'playwright-core';

async function setTheme(page, theme) {
  const toggle = page.getByRole('button', {name:'Dark mode', exact:true});
  if ((await toggle.getAttribute('aria-pressed') === 'true') !== (theme === 'dark')) await toggle.click();
  await page.waitForFunction(value => document.documentElement.dataset.theme === value, theme);
}


// Mock only transport. The real terminal emulator renders and processes input.
const base = process.env.AGENTGUARD_CHECK_URL || 'http://127.0.0.1:5174';
const browser = await chromium.launch({ headless: true,
  ...(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : { channel: 'chrome' }) });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1050 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const status = { workspace: 'C:\\workspace', policy_default: 'ask', agy: { version: 'test' },
    session: { state: 'stopped', model: null, sandbox: true, conversation_id: null, provider: 'agy' } };
  let terminalSocket;
  let eventSocket;
  let writable = true;
  const inputs = [];
  const menu = "\x1b[2J\x1b[HRequesting permission for:\r\nGet-ChildItem\r\n\r\nRun this command?\r\n> 1. Yes, run command\r\n  2. Yes, and always allow in this conversation\r\n  3. Yes, and always allow (Persist to settings.json)\r\n  4. No, cancel\r\n\x1b[6n";
  await page.routeWebSocket('**/ws', socket => { eventSocket = socket; });
  await page.routeWebSocket('**/ws/terminal/*', socket => {
    terminalSocket = socket;
    socket.onMessage(data => {
      const message = JSON.parse(data);
      if (message.type === 'input') inputs.push(message.data);
      if (message.type === 'claim') socket.send(JSON.stringify({ type: 'control', writable: true }));
    });
    socket.send(JSON.stringify({ type: 'snapshot', data: menu, writable, ended: false, cols: 100, rows: 30 }));
  });
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    let body = {};
    switch (path) {
      case '/api/config': body = { models: [], workspace: status.workspace, gemini_acp_available: true }; break;
      case '/api/status': body = status; break;
      case '/api/approvals': body = { pending: [], history: [] }; break;
      case '/api/audit': body = { events: [] }; break;
      case '/api/policy': body = { default_action: 'ask', rules: [] }; break;
      case '/api/session/start':
        assert.equal(route.request().postDataJSON().provider, 'agy');
        assert.equal(route.request().postDataJSON().interactive, true);
        Object.assign(status.session, { state: 'running', interactive: true, terminal_id: 'test-terminal' });
        body = status.session; break;
      default: throw new Error(`Unexpected route: ${path}`);
    }
    await route.fulfill({ json: body });
  });
  await page.goto(base);
  await page.getByRole('button', { name: 'Start session', exact: true }).click();
  await page.getByText('Connected to agy', { exact: true }).waitFor();
  await page.waitForFunction(() => document.querySelector('.xterm-accessibility-tree')?.textContent.includes('Yes, run command'));
  assert.deepEqual(inputs, [], 'Snapshot replay must not send terminal query responses or approval input');
  const initialSocket = terminalSocket;
  const terminalNode = await page.locator('.xterm').elementHandle();
  for (const theme of ['dark', 'light']) {
    await setTheme(page, theme);
    const expected = theme === 'dark' ? 'rgb(21, 24, 32)' : 'rgb(245, 246, 248)';
    await page.waitForFunction(background => {
      const surface = document.querySelector('.terminal-surface');
      const viewport = document.querySelector('.xterm-viewport');
      return surface && viewport && getComputedStyle(surface).backgroundColor === background && getComputedStyle(viewport).backgroundColor === background;
    }, expected);
    assert.ok(await terminalNode.evaluate(el => el.isConnected), 'Theme changes preserve the terminal instance');
    assert.equal(terminalSocket, initialSocket, 'Theme changes do not reconnect the CLI');
    assert.ok((await page.locator('.xterm-accessibility-tree').textContent()).includes('Yes, run command'), 'Output survives theme changes');
  }
  assert.deepEqual(inputs, [], 'Theme changes do not send terminal input');
  eventSocket.send(JSON.stringify({ type: 'action_issue', data: {
    id: 991, decision: 'block', event_type: 'policy_eval',
    payload: { tool: 'run_command', reason: 'Path is outside the approved workspace.' }
  } }));
  const blockNotice = page.getByLabel('AgentGuard action notices');
  await blockNotice.getByText('Action blocked by AgentGuard', { exact: true }).waitFor();
  assert.ok((await blockNotice.innerText()).includes('Path is outside the approved workspace.'));
  assert.deepEqual(inputs, [], 'Displaying a block must not send terminal input');
  const originalWidth = (await page.locator('.terminal-surface').boundingBox()).width;
  await page.getByRole('button', { name: 'Increase terminal font size' }).click();
  assert.equal(await page.getByLabel('Terminal font size', { exact: true }).innerText(), '15px');
  await page.getByRole('button', { name: 'Expand terminal width' }).click();
  assert.ok((await page.locator('.terminal-surface').boundingBox()).width > originalWidth);
  assert.deepEqual(inputs, [], 'Changing appearance must not send approval input');
  await page.getByRole('button', { name: 'Restore terminal width' }).click();
  assert.equal(terminalSocket, initialSocket, 'Collapsing and restoring settings preserves the terminal connection');
  assert.ok(await terminalNode.evaluate(el => el.isConnected), 'Layout changes preserve terminal output');
  await page.getByRole('button', { name: 'Next CLI option' }).click();
  await page.getByRole('button', { name: 'Enter', exact: true }).click();
  await page.waitForFunction(() => true);
  assert.deepEqual(inputs, ['\x1b[B', '\r']);
  // Exercise actual mouse focus and keyboard events, not locator.press (which
  // focuses the textarea for us and can conceal a broken terminal click).
  await page.getByLabel('Interactive agy terminal', { exact: true }).click({ position: { x: 25, y: 25 } });
  await page.keyboard.type('a');
  await page.waitForTimeout(50);
  assert.equal(inputs.at(-1), 'a');
  await page.getByRole('button', { name: 'Focus terminal', exact: true }).click();
  await page.keyboard.type('b');
  await page.waitForTimeout(50);
  assert.equal(inputs.at(-1), 'b');
  await page.evaluate(() => {
    window.copiedTerminalText = '';
    Object.defineProperty(navigator.clipboard, 'writeText', { configurable: true, value: async text => { window.copiedTerminalText = text; } });
    Object.defineProperty(navigator.clipboard, 'readText', { configurable: true, value: async () => 'pasted text' });
  });
  const screen = await page.locator('.xterm-screen').boundingBox();
  await page.mouse.move(screen.x + 2, screen.y + 8);
  await page.mouse.down(); await page.mouse.move(screen.x + 160, screen.y + 8, {steps: 6}); await page.mouse.up();
  await page.getByRole('button', {name:'Copy selection',exact:true}).click();
  assert.ok((await page.evaluate(() => window.copiedTerminalText)).length > 0, 'Copy selected terminal text');
  const beforeCopy = inputs.length;
  await page.keyboard.press('Control+c');
  assert.equal(inputs.length, beforeCopy, 'Copy selection must not interrupt CLI');
  await page.getByRole('button', {name:'Paste',exact:true}).click();
  await page.waitForTimeout(60);
  assert.equal(inputs.at(-1), 'pasted text');
  const beforeNativePaste = inputs.length;
  await page.locator('.xterm-helper-textarea').evaluate(el => {
    const data = new DataTransfer(); data.setData('text/plain', 'native paste');
    el.dispatchEvent(new ClipboardEvent('paste', {clipboardData:data,bubbles:true,cancelable:true}));
  });
  await page.waitForTimeout(60);
  assert.deepEqual(inputs.slice(beforeNativePaste), ['native paste'], 'Native paste delivered exactly once');
  terminalSocket.send(JSON.stringify({type:'output',data:'\x1b[?2004h'}));
  await page.waitForTimeout(80);
  await page.getByRole('button', {name:'Paste',exact:true}).click();
  await page.waitForTimeout(60);
  assert.equal(inputs.at(-1), '\x1b[200~pasted text\x1b[201~', 'Preserve CLI bracketed paste');
  terminalSocket.send(JSON.stringify({type:'output',data:'\x1b[?2004l'}));
  terminalSocket.send(JSON.stringify({ type: 'output', data: '\r\n<img src=x onerror="window.terminalXss=1">\r\n' }));
  await page.waitForTimeout(80);
  assert.equal(await page.evaluate(() => window.terminalXss), undefined);
  assert.equal(await page.locator('.terminal-surface img').count(), 0);
  const scrollInputCount = inputs.length;
  const zipper = page.getByRole('scrollbar', { name: 'Terminal scrollback' });
  assert.equal(await zipper.isVisible(), false, 'No handle for short content');
  terminalSocket.send(JSON.stringify({ type: 'output', data: Array.from({length: 150}, (_, i) => `\r\nHistory line ${i}`).join('') }));
  await zipper.waitFor({ state: 'visible' });
  // Keep both rail ends and the overshoot inside the browser viewport for pointer tests.
  await page.locator('.terminal-surface').evaluate(el => { el.scrollIntoView({block:'center'}); });
  const geometry = () => zipper.evaluate(el => {
    const thumb = el.getBoundingClientRect();
    const rail = el.parentElement.getBoundingClientRect();
    const frame = el.closest('.zipper-frame').getBoundingClientRect();
    return { x: thumb.x, y: thumb.y, width: thumb.width, height: thumb.height,
      edge: frame.right, top: rail.top, bottom: rail.bottom, inside: el.parentElement.dataset.inside };
  });
  let g = await geometry();
  assert.ok(Math.abs(g.x + g.width / 2 - g.edge) < 1, 'Handle straddles the container edge');
  assert.equal(g.width, 17); assert.equal(g.height, 48);
  await zipper.press('Home');
  await page.waitForFunction(() => document.querySelector('[aria-label="Terminal scrollback"]').getAttribute('aria-valuenow') === '0');
  g = await geometry(); assert.ok(Math.abs(g.y - g.top) < 1);
  await zipper.press('End');
  await page.waitForTimeout(100);
  g = await geometry(); assert.ok(Math.abs(g.y + g.height - g.bottom) < 2);
  await zipper.press('Home');
  g = await geometry();
  await page.mouse.move(g.x + 8, g.y + 24);
  await page.mouse.down();
  await page.mouse.move(g.x + 8, g.bottom + 100, { steps: 8 });
  await page.mouse.up();
  await page.waitForTimeout(100);
  g = await geometry(); assert.ok(Math.abs(g.y + g.height - g.bottom) < 2, 'Drag clamps to bottom');
  await page.locator('.terminal-surface').hover();
  await page.mouse.wheel(0, -500);
  await page.waitForTimeout(200);
  assert.ok(Number(await zipper.getAttribute('aria-valuenow')) < Number(await zipper.getAttribute('aria-valuemax')), 'Wheel updates handle');
  const rail = page.locator('.terminal-scroll-frame .zipper-rail');
  await rail.click({ position: { x: 22, y: 5 } });
  await page.waitForTimeout(80);
  assert.equal(Number(await zipper.getAttribute('aria-valuenow')), 0, 'Rail click scrolls to top');
  await zipper.press('PageDown');
  assert.ok(Number(await zipper.getAttribute('aria-valuenow')) > 0);
  await zipper.press('ArrowDown');
  await zipper.press('ArrowUp');
  await zipper.press('PageUp');
  await zipper.press('Home');
  // Real browser touch events exercise pointer capture and cancellation.
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('Emulation.setTouchEmulationEnabled', { enabled: true });
  g = await geometry();
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: g.x + 8, y: g.y + 24 }] });
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: g.x + 8, y: g.y + 150 }] });
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  await page.waitForTimeout(100);
  assert.ok(Number(await zipper.getAttribute('aria-valuenow')) > 0, 'Touch drag scrolls');
  g = await geometry();
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: g.x + 8, y: g.y + 24 }] });
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchCancel', touchPoints: [] });
  assert.equal(await zipper.evaluate(el => el.classList.contains('dragging')), false, 'Cancellation ends dragging');
  await cdp.send('Emulation.setTouchEmulationEnabled', { enabled: false });
  await cdp.detach();
  // A clipping ancestor forces the handle inward without changing the scroll viewport.
  await page.locator('.interactive-terminal').evaluate(el => { el.style.overflow = 'hidden'; el.style.paddingRight = '0'; });
  await page.setViewportSize({ width: 1439, height: 1050 });
  await page.waitForTimeout(100);
  g = await geometry(); assert.equal(g.inside, 'true'); assert.ok(g.x + g.width <= g.edge);
  await page.locator('.interactive-terminal').evaluate(el => { el.style.overflow = ''; el.style.paddingRight = ''; });
  await page.setViewportSize({ width: 1440, height: 1050 });
  assert.equal(inputs.length, scrollInputCount, 'Scrollbar keyboard and drag never type into CLI');
  await mkdir('.qa', { recursive: true });
  await page.screenshot({ path: '.qa/interactive-terminal.png', fullPage: true });
  writable = false;
  await page.getByRole('button', { name: 'Reconnect terminal' }).click();
  await page.getByText('Read-only — another browser controls this session', { exact: true }).waitFor();
  assert.equal(await page.getByRole('button', { name: 'Enter', exact: true }).isDisabled(), true);
  assert.equal(await page.getByRole('button',{name:'Paste',exact:true}).isDisabled(),true);
  const count = inputs.length;
  await page.locator('.xterm-helper-textarea').evaluate(el => { const data=new DataTransfer(); data.setData('text/plain','must not send'); el.dispatchEvent(new ClipboardEvent('paste',{clipboardData:data,bubbles:true,cancelable:true})); });
  await page.locator('.xterm-helper-textarea').press('Enter');
  assert.equal(inputs.length, count);
  await page.getByRole('button', { name: 'Take control', exact: true }).click();
  await page.getByText('Connected to agy', { exact: true }).waitFor();
  await page.keyboard.type('c');
  await page.waitForTimeout(50);
  assert.equal(inputs.at(-1), 'c');
  terminalSocket.send(JSON.stringify({ type: 'control', writable: false }));
  await page.getByText('Read-only — another browser controls this session', { exact: true }).waitFor();
  assert.equal(await page.getByRole('button', { name: 'Enter', exact: true }).isDisabled(), true);
  terminalSocket.send(JSON.stringify({ type: 'control', writable: true }));
  await page.getByText('Connected to agy', { exact: true }).waitFor();
  terminalSocket.close();
  await page.getByText('Disconnected — reconnect to continue', { exact: true }).waitFor();
  writable = true;
  await page.getByRole('button', { name: 'Reconnect terminal' }).click();
  await page.getByText('Connected to agy', { exact: true }).waitFor();
  terminalSocket.send(JSON.stringify({ type: 'ended' }));
  await page.getByText('Session ended', { exact: true }).waitFor();
  assert.equal(await page.getByRole('button', { name: 'Enter', exact: true }).isDisabled(), true);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: '.qa/interactive-terminal-mobile.png', fullPage: true });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
  assert.deepEqual(errors, []);
  console.log('Zipper: geometry, bounds, rail, wheel, keyboard, touch, cancellation and inside fallback passed. Interactive terminal: native menu text, exact keyboard routing, replay, read-only, disconnect, XSS and mobile checks passed. Transport mocked.');
} finally { await browser.close(); }
