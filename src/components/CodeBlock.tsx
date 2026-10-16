import { ScrollFrame } from './ScrollFrame';
import { memo, useEffect, useState, type CSSProperties } from 'react';
import type { ThemedToken } from 'shiki';
import { CopyButton } from './CopyButton';

export const CodeBlock = memo(function CodeBlock({code, language = ''}: {code:string; language?:string}) {
  const [result, setResult] = useState<{code:string; tokens:ThemedToken[][]} | null>(null);
  useEffect(() => {
    let active = true;
    // Keep long/unknown code readable without spending time tokenizing it.
    if (!language || code.length > 30000) return;
    const timer = setTimeout(() => {
      import('../rendering/highlight').then(m => m.highlight(code, language)).then(tokens => {
        if (active && tokens) setResult({code, tokens});
      }).catch(() => { /* Plain code is the fallback, including while grammars load. */ });
    }, 120);
    return () => { active = false; clearTimeout(timer); };
  }, [code, language]);
  return <div className="response-code">
    <div className="code-toolbar"><span>{language || 'Plain text'}</span><CopyButton text={code} label="Copy code"/></div>
    <ScrollFrame label={`${language || 'Plain text'} code`}><pre tabIndex={0} aria-label={`${language || 'Plain text'} code`}><code>{result?.code === code ? result.tokens.map((line, i) => <span className="code-line" key={i}>{line.map((token,j) => <span key={j} style={token.htmlStyle as CSSProperties}>{token.content}</span>)}{i < result.tokens.length - 1 ? '\n' : ''}</span>) : code}</code></pre></ScrollFrame>
  </div>;
});
