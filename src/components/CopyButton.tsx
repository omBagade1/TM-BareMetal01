import { useEffect, useRef, useState } from 'react';
import { Check, Copy } from 'lucide-react';

export function CopyButton({ text, label = 'Copy' }: { text: string; label?: string }) {
  const [state, setState] = useState<'idle' | 'copied' | 'failed'>('idle');
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);
  async function copy() {
    clearTimeout(timer.current);
    try { await navigator.clipboard.writeText(text); setState('copied'); }
    catch { setState('failed'); }
    timer.current = setTimeout(() => setState('idle'), 2200);
  }
  return <button className="copy-button" onClick={copy} aria-label={state === 'copied' ? 'Copied' : label}>
    {state === 'copied' ? <Check size={14}/> : <Copy size={14}/>}
    <span role="status">{state === 'copied' ? 'Copied' : state === 'failed' ? 'Copy failed — retry' : label}</span>
  </button>;
}
