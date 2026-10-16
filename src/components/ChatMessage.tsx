import { ScrollFrame } from './ScrollFrame';
import { lazy, memo, Suspense } from 'react';
const ResponseRenderer = lazy(() => import('./ResponseRenderer'));
export type Chat = { id:string; role:string; text:string; streaming?:boolean; auditId?:number; issueTitle?:string; files?:{name:string;size_bytes:number}[] };
export const ChatMessage = memo(function ChatMessage({message,onInspect}: {message:Chat;onInspect?:(id:number)=>void}) {
  const user = message.role === 'You';
  if(message.files)return <article className="message agent" aria-label="Workspace file listing">
    <strong className="message-author">AgentGuard · Workspace files</strong>
    <p className="user-content">{message.text}</p>
    {message.files.length?<ScrollFrame label="Table"><div className="response-table"><table><thead><tr><th>File</th><th>Size (bytes)</th></tr></thead><tbody>{message.files.map(file=><tr key={file.name}><td>{file.name}</td><td>{file.size_bytes}</td></tr>)}</tbody></table></div></ScrollFrame>:<p>No regular files found.</p>}
  </article>;
  if(message.auditId!==undefined)return <article className="message action-issue" aria-label="Action notice" role="status">
    <strong className="message-author">{message.issueTitle}</strong>
    {message.text&&<div className="user-content">{message.text}</div>}
    <button aria-label={`Inspect audit event #${message.auditId}`} onClick={()=>onInspect?.(message.auditId!)}>View details in audit</button>
  </article>;
  return <article className={`message ${user ? 'user' : 'agent'}`} aria-label={user ? 'Your message' : 'Agent response'}>
    <strong className="message-author">{message.role}</strong>
    {user ? <div className="user-content">{message.text}</div> : <Suspense fallback={<div className="response-loading" role="status">Preparing response…</div>}><ResponseRenderer text={message.text} streaming={message.streaming}/></Suspense>}
  </article>;
});
