import { useEffect, useState } from 'react';
import { Sun, Moon } from 'lucide-react';
type Theme = 'system'|'light'|'dark';
export function ThemeSelect() {
  const [theme, setTheme] = useState<Theme>(() => {
    try { const saved=localStorage.getItem('agentguard-theme'); return saved==='dark'||saved==='light' ? saved : 'system'; }
    catch { return 'system'; }
  });
  const [dark, setDark] = useState(false);
  useEffect(() => {
    const query=matchMedia('(prefers-color-scheme: dark)');
    const apply=()=>{const isDark=theme==='dark'||(theme==='system'&&query.matches);document.documentElement.dataset.theme=isDark?'dark':'light';setDark(isDark);};
    apply();query.addEventListener('change',apply);
    try { localStorage.setItem('agentguard-theme',theme); } catch { /* Private storage can be unavailable. */ }
    return ()=>query.removeEventListener('change',apply);
  },[theme]);
  return <button className="theme-toggle" type="button" aria-label="Dark mode" aria-pressed={dark} title={dark?'Switch to light mode':'Switch to dark mode'} onClick={()=>setTheme(dark?'light':'dark')}>{dark?<Moon size={18} aria-hidden="true"/>:<Sun size={18} aria-hidden="true"/>}</button>;
}
