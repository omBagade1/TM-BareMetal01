import type { ReactNode } from 'react';
type Notice = { type:'notice'; tone:'info'|'success'|'warning'; title:string; body:string };
type Disclosure = { type:'details'; title:string; body:string };
type RichContent = Notice | Disclosure;

export function parseRichContent(source:string): RichContent | null {
  if (source.length > 20000) return null;
  try {
    const value:unknown = JSON.parse(source);
    if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
    const v = value as Record<string, unknown>;
    if (typeof v.title !== 'string' || typeof v.body !== 'string' || v.title.length > 180 || v.body.length > 12000) return null;
    if (v.type === 'details') return {type:'details', title:v.title, body:v.body};
    if (v.type === 'notice' && (v.tone === 'info' || v.tone === 'success' || v.tone === 'warning')) return {type:'notice', tone:v.tone, title:v.title, body:v.body};
  } catch { /* Incomplete or unknown structured data remains a code block. */ }
  return null;
}
const registry: { [K in RichContent['type']]: (value:Extract<RichContent,{type:K}>)=>ReactNode } = {
  notice: value => <aside className={`response-notice ${value.tone}`}><strong>{value.title}</strong><p>{value.body}</p></aside>,
  details: value => <details className="response-details"><summary>{value.title}</summary><p>{value.body}</p></details>,
};
export function RichBlock({value}: {value:RichContent}) {
  return value.type === 'notice' ? registry.notice(value) : registry.details(value);
}
