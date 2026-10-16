import { useEffect, useRef, useState } from 'react';
import { ArrowUp, ArrowDown, CornerDownLeft, RotateCw, Maximize2, Minimize2, Minus, Plus, Terminal as TerminalIcon } from 'lucide-react';
import xterm from '../vendor/xterm/xterm.js';
import '../vendor/xterm/xterm.css';
import './terminal.css';
import { ZipperScrollbar } from './ZipperScrollbar';

function terminalTheme() {
  const root = document.documentElement;
  const style = getComputedStyle(root);
  const color = (name: string) => style.getPropertyValue(name).trim();
  const dark = root.dataset.theme === 'dark';
  return {
    background: color('--bg-pre'), foreground: color('--text-main'),
    cursor: color('--blue'), cursorAccent: color('--bg-pre'),
    selectionBackground: dark ? '#365984' : '#c9daf5',
    selectionInactiveBackground: dark ? '#2b405e' : '#e0e8f3',
    black: dark ? '#526580' : '#172b46', brightBlack: dark ? '#9badc4' : '#596c84',
    red: dark ? '#ff9fae' : '#ad3049', brightRed: dark ? '#ffbdc7' : '#a12640',
    green: dark ? '#8bd6b0' : '#226950', brightGreen: dark ? '#b3e8ce' : '#176244',
    yellow: dark ? '#e7bf75' : '#85580c', brightYellow: dark ? '#f1d8a8' : '#795008',
    blue: dark ? '#92b8ff' : '#315fbc', brightBlue: dark ? '#bed5ff' : '#274e9c',
    magenta: dark ? '#d4a7e6' : '#83479a', brightMagenta: dark ? '#e6c7f1' : '#713b87',
    cyan: dark ? '#8bd2df' : '#236b79', brightCyan: dark ? '#b5e6ed' : '#185e6b',
    white: dark ? '#c2cee0' : '#384d67', brightWhite: color('--text-main'),
  };
}

export function InteractiveTerminal({ terminalId, expanded, onToggleExpand }: { terminalId?: string; expanded: boolean; onToggleExpand: () => void }) {
  const host = useRef<HTMLDivElement>(null);
  const sendKey = useRef<(data: string) => void>(() => {});
  const changeFont = useRef<(size: number) => void>(() => {});
  const focusTerminal = useRef<() => void>(() => {});
  const claimControl = useRef<() => void>(() => {});
  const copySelection = useRef<() => void>(() => {});
  const pasteClipboard = useRef<() => void>(() => {});
  const [hasSelection, setHasSelection] = useState(false);
  const [fontSize, setFontSize] = useState(14);
  const [connection, setConnection] = useState('Start a session to open agy here.');
  const [writable, setWritable] = useState(false);
  const [canClaim, setCanClaim] = useState(false);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    setWritable(false); setCanClaim(false); setError(''); setHasSelection(false);
    if (!terminalId || !host.current) { setConnection('Start a session to open agy here.'); return; }
    let disposed = false;
    let ready = false;
    let owner = false;
    let replaying = true;
    let ended = false;
    let disconnected = false;
    const terminal = new xterm.Terminal({
      cols: 100, rows: 30, fontSize, lineHeight: 1.25, fontFamily: 'Consolas, "Courier New", monospace',
      cursorBlink: false, scrollback: 3000, screenReaderMode: true, disableStdin: true,
      theme: terminalTheme(),
    });
    // Update the renderer in place so theme changes preserve input, output and ownership.
    const themeObserver = new MutationObserver(() => { terminal.options.theme = terminalTheme(); });
    themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    const fit = new xterm.FitAddon(); terminal.loadAddon(fit);
    // Output is terminal text. Do not allow terminal-controlled clipboard or links.
    terminal.parser.registerOscHandler(52, () => true);
    terminal.parser.registerOscHandler(8, () => true);
    terminal.open(host.current);
    const socket = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/ws/terminal/${encodeURIComponent(terminalId)}`);
    const send = (message: unknown) => { if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(message)); };
    focusTerminal.current = () => {
      if (ready && !owner && !ended) send({ type: 'claim' });
      else if (ready && owner && !replaying) terminal.focus();
    };
    claimControl.current = () => { if (ready && !ended) send({ type: 'claim' }); };
    const input = (data: string) => {
      if (!ready || !owner || replaying) return;
      if (data.length > 8192) { setError('Input is too long. Paste at most 8,192 characters at a time.'); return; }
      send({ type: 'input', data });
    };
    sendKey.current = data => { input(data); terminal.focus(); };
    changeFont.current = size => {
      terminal.options.fontSize = size;
      if (ready && owner && !replaying) fit.fit();
    };
    terminal.onData(input);
    terminal.onSelectionChange(() => setHasSelection(!!terminal.getSelection()));
    const copy = async () => {
      const text = terminal.getSelection();
      if (!text) return;
      try { await navigator.clipboard.writeText(text); if (!disposed) setError(''); }
      catch { if (!disposed) setError('Clipboard access was denied. Select text and use the browser’s Copy command.'); }
    };
    const paste = (text: string) => {
      if (disposed || !ready || !owner || replaying) return;
      // xterm handles newline normalization and bracketed paste for the CLI.
      terminal.paste(text); terminal.focus();
    };
    const readClipboard = async () => {
      if (!ready || !owner || replaying) return;
      try { const text = await navigator.clipboard.readText(); paste(text); }
      catch { if (!disposed) setError('Clipboard access was denied. Focus the terminal and press Ctrl+V, or use the browser’s Paste command.'); }
    };
    copySelection.current = () => { void copy(); };
    pasteClipboard.current = () => { void readClipboard(); };
    terminal.attachCustomKeyEventHandler(event => {
      const key = event.key.toLowerCase();
      if (!(event.ctrlKey || event.metaKey) || event.altKey) return true;
      if (key === 'c' && (event.shiftKey || event.metaKey || terminal.getSelection())) {
        if (event.type === 'keydown') { event.preventDefault(); void copy(); }
        return false;
      }
      if (key === 'v') {
        if (event.shiftKey && event.type === 'keydown') { event.preventDefault(); void readClipboard(); }
        // Plain Ctrl/Cmd+V remains a browser paste event, never CLI input.
        return false;
      }
      return true;
    });
    const surface = host.current;
    const onMouseDown = () => { focusTerminal.current(); };
    surface.addEventListener('mousedown', onMouseDown, true);
    const onPaste = (event: ClipboardEvent) => {
      event.preventDefault(); event.stopPropagation();
      paste(event.clipboardData?.getData('text/plain') || '');
    };
    surface.addEventListener('paste', onPaste, true);
    terminal.onResize(({ cols, rows }) => {
      if (ready && owner && !replaying) send({ type: 'resize', cols: Math.max(20, Math.min(300, cols)), rows: Math.max(5, Math.min(120, rows)) });
    });
    const observer = new ResizeObserver(() => { if (ready && owner && !replaying) fit.fit(); });
    observer.observe(host.current);
    setConnection('Connecting to agy…');
    socket.onmessage = ({ data }) => {
      if (disposed) return;
      const message = JSON.parse(data);
      if (message.type === 'snapshot') {
        ended = message.ended;
        replaying = true; terminal.reset(); terminal.resize(message.cols, message.rows);
        owner = message.writable && !message.ended;
        terminal.write(message.data, () => {
          if (disposed || disconnected) return;
          replaying = false; ready = !ended; owner = owner && !ended;
          terminal.options.disableStdin = !owner; setWritable(owner);
          setCanClaim(ready && !owner);
          setConnection(ended ? 'Session ended' : owner ? 'Connected to agy' : 'Read-only — another browser controls this session');
          if (message.truncated) setError('Older terminal history was trimmed. The latest output is shown.');
          if (owner) { fit.fit(); send({ type: 'resize', cols: Math.max(20, Math.min(300, terminal.cols)), rows: Math.max(5, Math.min(120, terminal.rows)) }); terminal.focus(); }
        });
      } else if (message.type === 'output') terminal.write(message.data);
      else if (message.type === 'control') {
        owner = !!message.writable && !ended;
        if (!replaying && ready) {
          terminal.options.disableStdin = !owner; setWritable(owner); setCanClaim(!owner);
          setConnection(owner ? 'Connected to agy' : 'Read-only — another browser controls this session');
          if (owner) { fit.fit(); terminal.focus(); }
        }
      }
      else if (message.type === 'resize') { if (!owner) terminal.resize(message.cols, message.rows); }
      else if (message.type === 'error') setError(message.message);
      else if (message.type === 'ended') {
        ended = true;
        ready = false; owner = false; terminal.options.disableStdin = true; setWritable(false); setCanClaim(false);
        setConnection('Session ended'); if (message.error) setError(message.error);
      } else if (message.type === 'overflow') setError('Output exceeded the connection buffer. Reconnect to restore the terminal.');
    };
    socket.onclose = () => {
      disconnected = true;
      ready = false; owner = false;
      if (!disposed) { terminal.options.disableStdin = true; setWritable(false); setCanClaim(false); setConnection('Disconnected — reconnect to continue'); }
    };
    socket.onerror = () => { if (!disposed) setError('Could not connect to the interactive terminal.'); };
    return () => {
      disposed = true; ready = false; sendKey.current = () => {};
      changeFont.current = () => {};
      focusTerminal.current = () => {}; claimControl.current = () => {};
      copySelection.current = () => {}; pasteClipboard.current = () => {};
      surface.removeEventListener('mousedown', onMouseDown, true);
      surface.removeEventListener('paste', onPaste, true);
      observer.disconnect(); themeObserver.disconnect(); socket.close(); terminal.dispose();
    };
  }, [terminalId, attempt]);

  useEffect(() => { changeFont.current(fontSize); }, [fontSize]);

  return <div className={`interactive-terminal${expanded ? ' terminal-expanded' : ''}`}>
    <div className="terminal-toolbar">
      <div className="terminal-identity"><TerminalIcon size={18}/><strong>agy</strong><span>Interactive session</span></div>
      <div className="terminal-view-controls">
        <button disabled={fontSize<=12} aria-label="Decrease terminal font size" title="Smaller text" onClick={()=>setFontSize(s=>s-1)}><Minus size={14}/></button>
        <span aria-label="Terminal font size">{fontSize}px</span>
        <button disabled={fontSize>=20} aria-label="Increase terminal font size" title="Larger text" onClick={()=>setFontSize(s=>s+1)}><Plus size={14}/></button>
        <button aria-label={expanded?'Restore terminal width':'Expand terminal width'} title={expanded?'Restore width':'Use full width'} onClick={onToggleExpand}>{expanded?<Minimize2 size={16}/>:<Maximize2 size={16}/>}</button>
      </div>
    </div>
    <div className="terminal-connection" data-writable={writable}><span className="terminal-status-dot"/><span role="status">{connection}</span>{canClaim&&<button className="take-control-btn" onClick={()=>claimControl.current()}>Take control</button>}<button disabled={!writable && !canClaim} onClick={()=>focusTerminal.current()}>Focus terminal</button><button disabled={!terminalId} aria-label="Reconnect terminal" title="Reconnect terminal" onClick={() => setAttempt(a => a + 1)}><RotateCw size={14} /></button></div>
    <div className="zipper-frame terminal-scroll-frame">{!terminalId&&<div className="terminal-empty"><TerminalIcon size={32}/><h3>Your next session starts here.</h3><p>Choose your settings in Session controls, then start a session to work with agy.</p><span>Live output. Native CLI controls. Policy review alongside.</span></div>}<div className="terminal-surface" ref={host} aria-label="Interactive agy terminal" onClick={()=>focusTerminal.current()} /><ZipperScrollbar targetRef={host} selector=".xterm-viewport" label="Terminal scrollback" /></div>
    <div className="terminal-controls">
      <span className="terminal-key-hint">Choose an option, then confirm</span>
      <button disabled={!hasSelection} onMouseDown={event=>event.preventDefault()} onClick={()=>copySelection.current()}>Copy selection</button>
      <button disabled={!writable} onClick={()=>pasteClipboard.current()}>Paste</button>
      <button disabled={!writable} aria-label="Previous CLI option" onClick={() => sendKey.current('\x1b[A')}><ArrowUp size={16} /></button>
      <button disabled={!writable} aria-label="Next CLI option" onClick={() => sendKey.current('\x1b[B')}><ArrowDown size={16} /></button>
      <button disabled={!writable} onClick={() => sendKey.current('\r')}><CornerDownLeft size={16} />Enter</button>
      <button disabled={!writable} onClick={() => sendKey.current('\x1b')}>Esc</button>
      <button disabled={!writable} onClick={() => sendKey.current('\x03')}>Ctrl+C</button>
    </div>
    <p className="terminal-help">Select text to copy with Ctrl+C; paste with Ctrl+V or the Paste button. Ctrl+C without a selection interrupts the CLI. Review AgentGuard requests in the permission queue; agy may then ask for its own confirmation here.</p>
    {error && <p className="terminal-error" role="alert">{error}</p>}
  </div>;
}
