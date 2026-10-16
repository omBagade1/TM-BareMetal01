import { ScrollFrame } from './ScrollFrame';
import { memo, useDeferredValue, useMemo } from 'react';
import Markdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import remend from 'remend';
import { Download } from 'lucide-react';
import { CodeBlock } from './CodeBlock';
import { CopyButton } from './CopyButton';
import { parseRichContent, RichBlock } from '../rendering/rich-content';
import 'katex/dist/katex.min.css';
import '../response.css';

export function safeUrl(value:string):string {
  if (/^#[\w-]+$/.test(value)) return value;
  try {
    const url = new URL(value);
    return ['http:', 'https:', 'mailto:'].includes(url.protocol) ? url.href : '';
  } catch { return ''; }
}
const components: Components = {
  span: ({node: _node, ...props}) => props.className?.split(' ').includes('katex-display')
    ? <ScrollFrame inline label="Equation"><span {...props}/></ScrollFrame>
    : <span {...props}/>,
  a: ({href, children}) => href ? <a href={href} target={href.startsWith('#') ? undefined : '_blank'} rel="noopener noreferrer" referrerPolicy="no-referrer">{children}</a> : <span>{children}</span>,
  // Generated images are explicit links: no automatic third-party requests or tracking pixels.
  img: ({src, alt}) => typeof src === 'string' && safeUrl(src) ? <a className="response-image-link" href={safeUrl(src)} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer">View image: {alt || 'image'}</a> : <span>{alt || 'Image unavailable'}</span>,
  table: ({children}) => <ScrollFrame label="Table"><div className="response-table" tabIndex={0} role="region" aria-label="Response table"><table>{children}</table></div></ScrollFrame>,
  input: ({checked}) => <input type="checkbox" checked={Boolean(checked)} disabled aria-label={checked ? 'Completed task' : 'Incomplete task'}/>,
  pre: ({node, children}) => {
    const element = node?.children[0];
    if (!element || element.type !== 'element' || element.tagName !== 'code') return <ScrollFrame label="Details"><pre>{children}</pre></ScrollFrame>;
    const classes = element.properties.className;
    const language = (Array.isArray(classes) ? classes.map(String).find(c => c.startsWith('language-'))?.slice(9) : '') || '';
    const code = element.children.map(child => child.type === 'text' ? child.value : '').join('');
    const rich = language === 'agentguard-json' ? parseRichContent(code) : null;
    return rich ? <RichBlock value={rich}/> : <CodeBlock code={code} language={language.toLowerCase()}/>;
  },
};
const remarkPlugins = [remarkGfm, remarkMath];
const katexOptions = {trust:false, strict:'ignore' as const, maxExpand:100, maxSize:20};

const ResponseRenderer = memo(function ResponseRenderer({text, streaming=false}: {text:string; streaming?:boolean}) {
  const deferred = useDeferredValue(text);
  const content = useMemo(() => streaming ? remend(deferred) : deferred, [deferred, streaming]);
  function download() {
    const url = URL.createObjectURL(new Blob([text], {type:'text/markdown;charset=utf-8'}));
    const a = document.createElement('a'); a.href=url; a.download='agentguard-response.md'; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return <div className="response-body">
    <div className="response-prose"><Markdown skipHtml urlTransform={safeUrl} remarkPlugins={remarkPlugins} rehypePlugins={[[rehypeKatex,katexOptions]]} components={components}>{content}</Markdown></div>
    {streaming ? <div className="response-streaming" role="status"><span/>Writing response</div> : <div className="response-actions"><CopyButton text={text} label="Copy response"/><button onClick={download} aria-label="Download response as Markdown"><Download size={14}/>Download</button></div>}
  </div>;
});
export default ResponseRenderer;
