import { ScrollFrame } from './components/ScrollFrame';
import React, { lazy, Suspense, useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ShieldCheck, MessageSquare, Fingerprint, SlidersHorizontal, Play, Square, Send, Check, X, RefreshCw, Terminal, Folder, Activity, PanelLeftClose, PanelLeftOpen } from 'lucide-react';
import './style.css';
import './theme.css';
import './design-system.css';
import './workspace-layout.css';
import './reference-theme.css';
import { BrandMark } from './components/BrandMark';
import { ChatMessage, type Chat } from './components/ChatMessage';
const InteractiveTerminal = lazy(() => import('./components/InteractiveTerminal').then(m => ({default:m.InteractiveTerminal}))); 
import { ZipperScrollbar } from './components/ZipperScrollbar';
import { ThemeSelect } from './components/ThemeSelect';

type Status = { enforcement?: {state:string;boundary:string;network:string;last_launch:unknown}; workspace: string; policy_default: string; ultra_security?: boolean; agy: {version:string}; session: {state:string; model:string|null; sandbox:boolean; conversation_id:string|null;provider?:string;error?:string|null;interactive?:boolean;terminal_id?:string} };
type Approval = {id:string; ts:string; tool:string; args:Record<string,unknown>; reason:string; decision?:string; decided_by?:string};
type Audit = {id:number; ts:string; event_type:string; decision:string|null; payload:Record<string,unknown>};
type Event = {event?:string; ws_type?:string; conversation_id?:string; payload?:{step_type?:string; step_index?:number; text_delta?:string; response?:string; status?:string; tool_name?:string; state?:string}; data?:unknown};
async function api<T>(path:string, method='GET', body?:unknown):Promise<T> {
  const res = await fetch('/api'+path,{method,headers:body?{'Content-Type':'application/json'}:undefined,body:body?JSON.stringify(body):undefined});
  const data = await res.json();
  if(!res.ok) throw new Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail||data));
  return data;
}
const pretty = (value:unknown) => JSON.stringify(value,null,2);
const clock = (ts:string) => new Date(ts).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'});

function App(){
  const [page,setPage]=useState('Workspace');
  const [controlsOpen,setControlsOpen]=useState(true);
  const [status,setStatus]=useState<Status|null>(null);
  const [models,setModels]=useState<{id:string;label:string}[]>([]);
  const [model,setModel]=useState('');
  const [sandbox,setSandbox]=useState(true);
  const [acpSandbox,setAcpSandbox]=useState(false);
  const [provider,setProvider]=useState('agy');
  const [ollamaModel,setOllamaModel]=useState('qwen3:4b');
  const [securityEvidence,setSecurityEvidence]=useState<unknown>(null);
  const [interactive,setInteractive]=useState(true);
  const [geminiAcpAvailable,setGeminiAcpAvailable]=useState(false);
  const [cwd,setCwd]=useState('');
  const [pending,setPending]=useState<Approval[]>([]);
  const [history,setHistory]=useState<Approval[]>([]);
  const [audit,setAudit]=useState<Audit[]>([]);
  const [selectedAudit,setSelectedAudit]=useState<Audit|null>(null);
  const clearedThrough=useRef(0);
  const issueRecords=useRef(new Map<number,Audit>());
  const applyAuditClear=useCallback((throughId:number)=>{
    clearedThrough.current=Math.max(clearedThrough.current,throughId);
    setAudit(old=>old.filter(a=>a.id>clearedThrough.current));
    setSelectedAudit(old=>old && old.id>clearedThrough.current?old:null);
    setVerification('');
    for(const id of issueRecords.current.keys())if(id<=clearedThrough.current)issueRecords.current.delete(id);
    setChat(old=>old.filter(c=>c.auditId===undefined || c.auditId>clearedThrough.current));
  },[]);
  const inspectAudit=useCallback((id:number)=>{
    setSelectedAudit(issueRecords.current.get(id)||null);setPage('Audit trail');
  },[]);
  useEffect(()=>{
    if(page==='Audit trail' && selectedAudit){
      const row=document.getElementById(`audit-${selectedAudit.id}`);
      if(row){row.scrollIntoView({block:'center'});row.focus();}
    }
  },[page,selectedAudit]);
  const [policy,setPolicy]=useState('');
  const [tool,setTool]=useState('view_file');
  const [args,setArgs]=useState('{"AbsolutePath":"test.txt"}');
  const [evaluation,setEvaluation]=useState('');
  const [verification,setVerification]=useState('');
  const [chat,setChat]=useState<Chat[]>([]);
  const [message,setMessage]=useState('');
  const [error,setError]=useState('');
  const [notice,setNotice]=useState('');
  const [busy,setBusy]=useState(false);
  const [listing,setListing]=useState(false);
  const [connected,setConnected]=useState(false);
  const [waiting,setWaiting]=useState(false);
  const [activity,setActivity]=useState('Ready when you are');
  const messages=useRef<HTMLDivElement>(null);
  const messageContent=useRef<HTMLDivElement>(null);
  const followBottom=useRef(true);
  const [showLatest,setShowLatest]=useState(false);
  function scrollToLatest(){
    followBottom.current=true;setShowLatest(false);
    if(messages.current)messages.current.scrollTop=messages.current.scrollHeight;
  }
  const turn=useRef(0);
  const running=status?.session.state==='running';
  const terminalMode=running?!!status?.session.interactive:provider==='agy'&&interactive;
  useEffect(()=>{if(status?.session.error){setError(status.session.error);setWaiting(false);}},[status?.session.error]);

  async function refresh(){
    const [s,a,events]=await Promise.all([api<Status>('/status'),api<{pending:Approval[];history:Approval[]}>('/approvals'),api<{events:Audit[]}>('/audit?limit=200')]);
    setStatus(s);setPending(a.pending);setHistory(a.history);setAudit([...new Map([...events.events,...issueRecords.current.values()].filter(a=>a.id>clearedThrough.current).map(a=>[a.id,a])).values()].sort((a,b)=>a.id-b.id).slice(-200));
  }
  useEffect(()=>{
    let disposed=false; let socket:WebSocket; let reconnect:ReturnType<typeof setTimeout>;
    Promise.all([api<{models:{id:string;label:string}[];workspace:string;gemini_acp_available:boolean}>('/config'),api<unknown>('/policy')]).then(([c,p])=>{if(disposed)return;setModels(c.models);setCwd(c.workspace);setPolicy(pretty(p));setGeminiAcpAvailable(c.gemini_acp_available);}).catch(e=>setError(e.message));
    refresh().catch(e=>setError(e.message));
    function connect(){
      socket=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws`);
      socket.onopen=()=>{setConnected(true);refresh().catch(()=>{});};
      socket.onclose=()=>{setConnected(false);if(!disposed)reconnect=setTimeout(connect,2000);};
      socket.onmessage=({data})=>{
        const msg=JSON.parse(data);
        if(msg.type==='status'){setStatus(msg.data);if(msg.data.session.state!=='running')setWaiting(false);}
        if(msg.type==='approval')refresh().catch(()=>{});
        if(msg.type==='security_event'){const row=msg.data as Audit;setAudit(old=>[...old.filter(x=>x.id!==row.id),row].slice(-200));setActivity(String(row.payload.attribution||row.decision||row.event_type));}
        if(msg.type==='audit_cleared')applyAuditClear(msg.data.through_id);
        if(msg.type==='action_issue'){
          const record=msg.data as Audit;
          if(record.id<=clearedThrough.current)return;
          issueRecords.current.set(record.id,record);
          setAudit(old=>[...old.filter(a=>a.id!==record.id),record].sort((a,b)=>a.id-b.id).slice(-200));
          const blocked=record.decision==='block';
          const payload=record.payload;
          const denied=record.event_type==='tool_denied';
          const title=blocked?'Action blocked by AgentGuard':denied?'Action not permitted':'Tool failed';
          const reason=String(payload.reason||(payload.error as {message?:string}|undefined)?.message||'No additional details available.');
          const source=payload.decided_by==='timeout'?'Approval timed out. ':payload.decided_by==='human'?'You blocked this action. ':'';
          // agy receives the tool failure and writes the conversational explanation.
          // Keep its internal error/instructions in the audit, not in the chat card.
          const text=denied?'':`${String(payload.tool||'Tool')}: ${source}${reason}`;
          setChat(old=>old.some(c=>c.id===`audit-${record.id}`)?old:[...old,{id:`audit-${record.id}`,role:'AgentGuard',text,auditId:record.id,issueTitle:title}]);
          setActivity(title);
        }
        if(msg.type!=='event')return;
        const e=msg.data as Event;const p=e.payload;
        if(e.ws_type==='session_end'){setChat(old=>old.map(c=>c.streaming?{...c,streaming:false}:c));setWaiting(false);setActivity('Session ended');return;}
        if(p?.step_type==='tool')setActivity(`${p.tool_name||'Tool'} · ${(p.state||'').toLowerCase()}`);
        if(p?.step_type==='agent_response' && typeof p.text_delta==='string' && p.text_delta){
          const id=`${e.conversation_id}-${turn.current}-${p.step_index}`;
          setChat(old=>{const found=old.find(x=>x.id===id);return found?old.map(x=>x.id===id?{...x,text:x.text+p.text_delta,streaming:p.state!=='DONE'}:x):[...old,{id,role:'Agent',text:p.text_delta!,streaming:p.state!=='DONE'}];});
        }
        if(p?.step_type==='agent_response' && p.state==='DONE'){
          const id=`${e.conversation_id}-${turn.current}-${p.step_index}`;
          setChat(old=>old.map(c=>c.id===id?{...c,streaming:false}:c));
        }
        if(e.event==='result'){
          setChat(old=>old.map(c=>c.streaming?{...c,streaming:false}:c));
          setWaiting(false);setActivity(`Turn ${p?.status||'complete'}`);
          if(p?.response){
            const prefix=`${e.conversation_id}-${turn.current}-`;
            setChat(old=>{
              const last=[...old].reverse().find(x=>x.role==='Agent' && x.id.startsWith(prefix));
              if(last && last.text===p.response)return old;
              if(last && p.response!.startsWith(last.text))return old.map(x=>x.id===last.id?{...x,text:p.response!,streaming:false}:x);
              return [...old,{id:prefix+'result',role:'Agent',text:String(p.response)}];
            });
          }
          refresh().catch(()=>{});
        }
      };
    }
    connect();const poll=setInterval(()=>refresh().catch(()=>{}),5000);
    return()=>{disposed=true;clearTimeout(reconnect);clearInterval(poll);socket?.close();};
  },[]);
  useLayoutEffect(()=>{
    if(followBottom.current && messages.current) messages.current.scrollTop=messages.current.scrollHeight;
  },[chat]);
  useEffect(()=>{
    const content=messageContent.current;
    if(!content)return;
    const observer=new ResizeObserver(()=>{
      if(followBottom.current && messages.current) messages.current.scrollTop=messages.current.scrollHeight;
    });
    observer.observe(content);
    return ()=>observer.disconnect();
  },[page]);
  async function action(fn:()=>Promise<void>){setBusy(true);setError('');setNotice('');try{await fn();await refresh();}catch(e){setError(e instanceof Error?e.message:String(e));}finally{setBusy(false);}}
  function start(){void action(async()=>{await api('/session/start','POST',{cwd,model:provider==='ollama'?ollamaModel:provider==='agy'?(model||null):null,sandbox,acp_sandbox:acpSandbox,provider,interactive:provider==='agy'&&interactive});setChat([]);followBottom.current=true;setShowLatest(false);setActivity('Session started');});}
  function send(){
    if(!message.trim())return;
    const content=message.trim(), id=crypto.randomUUID();
    void action(async()=>{
      turn.current++;setWaiting(true);scrollToLatest();
      setChat(old=>[...old,{id,role:'You',text:content}]);setMessage('');
      try { await api('/session/message','POST',{content});setActivity('Agent is working'); }
      catch(e){setChat(old=>old.filter(c=>c.id!==id));setMessage(content);setWaiting(false);throw e;}
    });
  }
  async function listFiles(){
    setListing(true);setError('');setActivity('File listing requested. Review any pending approval');
    try{
      const result=await api<{directory:string;files:{name:string;size_bytes:number}[];skipped:number;truncated:boolean;audit_id:number}>('/workspace/files','POST',{directory:cwd});
      setChat(old=>[...old,{id:crypto.randomUUID(),role:'AgentGuard',files:result.files,
        text:`${result.directory} · immediate files only. Audit event #${result.audit_id}.${result.skipped?` Skipped ${result.skipped} links or inaccessible entries.`:''}${result.truncated?' Listing limited to the first 1,000 directory entries.':''}`}]);
      setActivity('Workspace files listed');await refresh();
    }catch(e){setError(e instanceof Error?e.message:String(e));setActivity('File listing did not complete');}
    finally{setListing(false);}
  }
  function clearAudit(){
    if(!window.confirm('Clear the entire activity log? This permanently deletes all saved audit events, including older events not shown here. Export JSON first if you need a copy.'))return;
    void action(async()=>{
      const result=await api<{cleared:number;through_id:number}>('/audit','DELETE');
      applyAuditClear(result.through_id);
      setNotice(`Activity log cleared (${result.cleared} events removed).`);
    });
  }
  function decide(id:string,decision:string){void action(async()=>{await api(`/approvals/${id}`,'POST',{decision});});}
  async function toggleUltraSecurity(enabled:boolean){
    void action(async()=>{
      await api('/policy/ultra-security','POST',{enabled});
      setNotice(enabled?'Ultra Security mode enabled: all deletions and destructive actions are hard-blocked.':'Standard mode enabled: safe workspace file deletions will request your approval (Ask).');
    });
  }
  const visibleAudit=selectedAudit && !audit.some(a=>a.id===selectedAudit.id)?[...audit,selectedAudit].sort((a,b)=>a.id-b.id):audit;
  const nav=[{title:'Workspace',icon:MessageSquare},{title:'Approvals',icon:ShieldCheck},{title:'Policy',icon:SlidersHorizontal},{title:'Audit trail',icon:Fingerprint}];
  function approvalCard(a:Approval){return <article className="approval" key={a.id}><div className="row"><span className="badge ask">Needs your review</span><time>{clock(a.ts)}</time></div><h3>{a.tool}</h3><p>{a.reason}</p><ScrollFrame label="Details"><pre>{pretty(a.args)}</pre></ScrollFrame><div className="buttons"><button className="danger" disabled={busy} onClick={()=>decide(a.id,'block')}><X size={16}/>Block</button><button className="primary" disabled={busy} onClick={()=>decide(a.id,'allow')}><Check size={16}/>Allow once</button></div></article>;}

  return <div className="app"><a className="skip-link" href="#main-content">Skip to content</a><aside className="sidebar"><a className="brand" href="#" onClick={e=>{e.preventDefault();setPage('Workspace');}}><BrandMark/><span>AgentGuard<small>Your agent. Your boundaries.</small></span></a><nav aria-label="Main navigation">{nav.map(({title,icon:Icon})=><button key={title} aria-current={page===title?'page':undefined} className={page===title?'selected':''} onClick={()=>setPage(title)}><Icon size={19}/><span>{title}</span>{title==='Approvals'&&pending.length>0&&<b>{pending.length}</b>}</button>)}</nav><div className="sidebar-bottom"><div className="connection"><i className={connected?'online':''}/>{connected?'Live connection':'Reconnecting…'}</div><p>Local workspace</p><span>Local control interface</span></div></aside>
    <main id="main-content" tabIndex={-1}><header><div className="breadcrumb">AgentGuard <span>/</span> {page}</div><ThemeSelect/><span className={`badge ${running?'allow':''}`}><i/>{running?'Session running':'Session stopped'}</span></header><div className="content"><div className="page-heading"><div><h1>{page==='Workspace'?'A workspace with boundaries.':page}</h1><p>{page==='Workspace'?'Work with your agent. Stay in control of every action.':page==='Approvals'?'Review the exact action before your agent proceeds.':page==='Policy'?'Define what your agent can do, and what needs a review.':'A verifiable record of your agent’s activity.'}</p></div><button className="icon-button" title="Refresh status" onClick={()=>void action(refresh)} disabled={busy}><RefreshCw size={18}/></button></div>
    {error&&<div className="alert" role="alert">{error}<button aria-label="Dismiss error" onClick={()=>setError('')}><X size={16}/></button></div>}{notice&&<div className="notice" role="status">{notice}</div>}
    {page==='Workspace'&&<><section className="session-bar"><div className="workspace-path"><Folder size={20}/><div><strong>Approved workspace</strong><span title={status?.workspace}>{status?.workspace||'Connecting to backend…'}</span></div></div><div><span className="muted">Unmatched actions</span><strong className="policy-default">{status?.policy_default||'—'}</strong></div><div><span className="muted">Execution</span><strong>{running?(status?.session.interactive?'Interactive agy':status?.session.provider==='gemini-acp'?'Gemini CLI · ACP':status?.session.provider==='ollama'?'Custom agent':'Legacy CLI (OS isolation unverified)'):'Not started'}</strong></div></section><div className="workspace-toolbar"><button className="controls-toggle" aria-expanded={controlsOpen} aria-controls="session-controls-drawer" onClick={()=>setControlsOpen(open=>!open)}>{controlsOpen?<PanelLeftClose size={18}/>:<PanelLeftOpen size={18}/>}<span>{controlsOpen?'Hide session controls':'Show session controls'}</span></button><span className="muted">{pending.length?`${pending.length} action${pending.length===1?'':'s'} waiting for review`:'No pending permissions'}</span></div>
    <div className={`work-grid workspace-layout ${controlsOpen?'controls-open':'controls-closed'}`}><aside id="session-controls-drawer" className="session-controls-drawer" aria-label="Session settings" hidden={!controlsOpen}><section className="panel setup session-setup"><h2><Terminal size={19}/>Session controls</h2><label>Agent backend<select value={provider} onChange={e=>setProvider(e.target.value)} disabled={running}><option value="gemini-acp" disabled={!geminiAcpAvailable}>Gemini CLI (ACP permissions)</option><option value="ollama">Custom agent (Ollama / AppContainer)</option><option value="agy">Antigravity CLI (legacy development)</option></select></label>{provider==='agy'&&<label>Session interface<select aria-label="Session interface" value={interactive?'terminal':'headless'} onChange={e=>setInteractive(e.target.value==='terminal')} disabled={running}><option value="terminal">Interactive CLI (native permission options)</option><option value="headless">Headless chat (CLI approval limitation)</option></select></label>}{provider==='agy'&&<label>Model<select value={model} onChange={e=>setModel(e.target.value)} disabled={running}><option value="">CLI default</option>{models.map(m=><option key={m.id} value={m.id}>{m.label}</option>)}</select></label>}{provider==='ollama'&&<label>Open-weight model<select value={ollamaModel} onChange={e=>setOllamaModel(e.target.value)} disabled={running}><option value="qwen3:4b">Qwen3 4B</option><option value="qwen3:8b">Qwen3 8B</option></select></label>}{provider==='gemini-acp'&&<p className="help">AgentGuard applies policy to ACP permission requests, then sends your Allow once or Block choice back to Gemini CLI.</p>}<label>Working directory<input value={cwd} onChange={e=>setCwd(e.target.value)} disabled={running}/></label>{provider==='agy'&&<><label className="checkbox"><input type="checkbox" checked={sandbox} onChange={e=>setSandbox(e.target.checked)} disabled={running}/><span>Request legacy CLI sandbox flag</span></label><p className="help">Requests the CLI sandbox; availability depends on your OS and CLI. AgentGuard policy remains active.</p></>}{provider==='gemini-acp'&&<><label className="checkbox"><input type="checkbox" checked={acpSandbox} onChange={e=>setAcpSandbox(e.target.checked)} disabled={running}/><span>Request Gemini CLI sandbox</span></label><p className="help">Requires Docker or Podman on Windows. Off by default: Gemini runs without OS sandbox isolation. AgentGuard still reviews ACP permission requests.</p></>}<label className="checkbox"><input type="checkbox" checked={status?.ultra_security??false} onChange={e=>toggleUltraSecurity(e.target.checked)}/><span>Ultra Security Mode</span></label><p className="help">{status?.ultra_security?'Strict lockdown: all file deletions are hard-blocked without prompt.':'Standard mode: workspace file deletions will request your approval (Ask).'}</p>{running?<button className="danger full" disabled={busy} onClick={()=>void action(async()=>{await api('/session/stop','POST');setWaiting(false);})}><Square size={15}/>Stop session</button>:<button className="primary full" disabled={busy||!status||!cwd.trim()} onClick={start}><Play size={15}/>Start session</button>}</section><section className="panel evidence-panel"><h2><Fingerprint size={18}/>Enforcement evidence</h2><button onClick={()=>void action(async()=>setSecurityEvidence(await api('/security/results')))}>View retained test results</button>{securityEvidence!=null&&<details open><summary>Recorded results (not a live certification)</summary><ScrollFrame label="Security test evidence"><pre>{pretty(securityEvidence)}</pre></ScrollFrame></details>}<p>{status?.enforcement?.state||'UNVERIFIED'} · {status?.enforcement?.boundary||'No verified OS boundary'}</p><p className="help">{status?.enforcement?.network||'Network enforcement has not been tested.'}</p><p className="help">Legacy CLI adapters are not isolated by this worker. Setup success alone does not prove attack containment.</p>{status?.enforcement?.last_launch!=null&&<details><summary>Last worker launch</summary><pre>{pretty(status.enforcement.last_launch)}</pre></details>}</section></aside><div className="conversation-column"><section className="conversation panel"><div className="panel-heading"><h2><MessageSquare size={19}/>Conversation</h2><button disabled={terminalMode||listing||busy||waiting||!connected||!cwd.trim()} onClick={()=>void listFiles()}>{listing?'Listing files…':'List files'}</button></div>{terminalMode?<><Suspense fallback={<p className="empty">Opening terminal…</p>}><InteractiveTerminal expanded={!controlsOpen} onToggleExpand={()=>setControlsOpen(open=>!open)} terminalId={status?.session.interactive?status.session.terminal_id:undefined}/></Suspense></>:<><div className="zipper-frame conversation-scroll-frame"><div className="messages" tabIndex={0} aria-label="Conversation messages" ref={messages} onScroll={()=>{const el=messages.current;if(el){followBottom.current=el.scrollHeight-el.scrollTop-el.clientHeight<72;setShowLatest(!followBottom.current);}}}><div ref={messageContent}>{chat.length===0?<div className="empty-chat"><div className="shield-mark"><ShieldCheck size={40}/></div><h2>Make room for good work.</h2><p>Start a session, then give your agent a task.<br/>Actions that need permission will appear below the conversation.</p><div className="suggestions">{['Read test.txt and summarize it.','List the files in this workspace.'].map(s=><button key={s} onClick={()=>setMessage(s)}>{s}</button>)}</div></div>:chat.map(c=><ChatMessage key={c.id} message={c} onInspect={inspectAudit}/>)}{waiting&&chat.at(-1)?.role!=='Agent'&&<p className="thinking-status" role="status">Agent is working…</p>}</div></div><ZipperScrollbar targetRef={messages} label="Conversation scrollbar" /></div>{showLatest&&<button className="jump-latest" onClick={scrollToLatest}>Jump to latest</button>}<div className="composer"><div className="composer-label">Message your agent <span>Enter to send · Shift + Enter for a new line</span></div><ScrollFrame label="Message editor"><textarea aria-label="Message your agent" placeholder={running?'What would you like to work on?':'Start a session to send a message'} value={message} onChange={e=>setMessage(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();if(running&&!busy&&!waiting&&connected)send();}}}/></ScrollFrame><div className="row"><span><Activity size={13}/>{activity}</span><button className="primary" onClick={send} disabled={!running||!connected||busy||waiting||!message.trim()}><Send size={15}/>{waiting?'Working…':'Send'}</button></div></div></>}</section><section className={`review-panel workspace-review ${pending.length?'has-requests':'is-clear'}`} aria-label="Permission queue"><div className="row"><h2><ShieldCheck size={18}/>Permission queue</h2><span className="count">{pending.length}</span></div>{pending.length?<div className="workspace-approval-list">{pending.map(approvalCard)}</div>:<div className="queue-empty"><ShieldCheck size={28}/><strong>Nothing waiting on you</strong><p>Review policy requests here. agy may also ask for confirmation in the terminal.</p></div>}</section>{terminalMode&&<div className="terminal-action-notices" aria-label="AgentGuard action notices">{chat.filter(c=>c.auditId!==undefined).slice(-5).map(c=><ChatMessage key={c.id} message={c} onInspect={inspectAudit}/>)}</div>}</div></div></>}

    {page==='Approvals'&&<><div className="review-overview"><div><span>Pending requests</span><strong>{pending.length}</strong></div><div><span>Recent decisions</span><strong>{history.length}</strong></div><p>Review the tool and its arguments before allowing an action. Each approval applies once.</p></div><div className="section-title"><h2>Waiting for review</h2><span className="count">{pending.length}</span></div>{pending.length?<div className="approval-grid">{pending.map(approvalCard)}</div>:<div className="panel empty"><ShieldCheck size={34}/><h2>All clear</h2><p>There are no pending requests. New requests appear automatically.</p></div>}<h2 className="section-title">Recent decisions</h2><div className="panel">{history.length?history.map(a=><details key={a.id}><summary><span className={`badge ${a.decision}`}>{a.decision}</span><strong>{a.tool}</strong><span className="muted">{a.decided_by} · {clock(a.ts)}</span></summary><ScrollFrame label="Details"><pre>{pretty(a.args)}</pre></ScrollFrame></details>):<p className="empty">Decisions will be recorded here.</p>}</div></>}
    {page==='Policy'&&<><div className={`security-banner ${status?.ultra_security?'ultra':''}`}><div className="row"><div><strong>Security mode: {status?.ultra_security?'Ultra Security (Strict Lockdown)':'Standard (Human-in-the-Loop)'}</strong><p className="help" style={{margin:'4px 0 0'}}>{status?.ultra_security?'Destructive commands and file deletions are unconditionally blocked at the hard boundary.':'Deleting single regular files in the workspace routes to your approval queue (Ask).'}</p></div><button className={status?.ultra_security?'danger':'primary'} onClick={()=>toggleUltraSecurity(!status?.ultra_security)} disabled={busy}>{status?.ultra_security?'Switch to Standard Mode':'Enable Ultra Security Mode'}</button></div></div><div className="policy-grid"><section className="panel setup"><h2>Policy rules</h2><p className="help">Rules run in order; the first match wins. Hard safety boundaries run before these rules and cannot be overridden by Allow. Changes apply to the next action.</p><label htmlFor="policy">Policy JSON</label><ScrollFrame label="Policy editor"><textarea id="policy" className="code policy-editor" value={policy} onChange={e=>setPolicy(e.target.value)} spellCheck={false}/></ScrollFrame><div className="buttons"><button disabled={busy} onClick={()=>void action(async()=>setPolicy(pretty(await api('/policy'))))}>Reload saved</button><button className="primary" disabled={busy} onClick={()=>void action(async()=>{const p=JSON.parse(policy);setPolicy(pretty(await api('/policy','PUT',{data:p})));setNotice('Policy saved. New actions will use these rules.');})}>Save policy</button></div></section><section className="panel setup"><h2>Test an action</h2><p className="help">Check how the current saved policy evaluates an action. This does not execute the tool.</p><label>Tool name<input value={tool} onChange={e=>setTool(e.target.value)}/></label><label>Arguments (JSON)<ScrollFrame label="Arguments editor"><textarea className="code" rows={8} value={args} onChange={e=>setArgs(e.target.value)} spellCheck={false}/></ScrollFrame></label><button disabled={busy||!tool.trim()} onClick={()=>void action(async()=>setEvaluation(pretty(await api('/policy/evaluate','POST',{tool,args:JSON.parse(args)}))))}>Evaluate action</button>{evaluation&&<ScrollFrame label="Details"><pre className="result">{evaluation}</pre></ScrollFrame>}</section></div></>}
    {page==='Audit trail'&&<section className="panel audit-panel"><div className="panel-heading"><h2>Activity log <span className="count">{audit.length}</span></h2><div className="buttons"><button onClick={()=>{const url=URL.createObjectURL(new Blob([pretty(audit)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='agentguard-audit.json';a.click();URL.revokeObjectURL(url);}}>Export JSON</button><button disabled={busy} onClick={()=>void action(async()=>{const v=await api<{verified:boolean;total:number;tampered_ids:number[];legacy_records?:number}>('/audit/verify');setVerification(v.verified?`Chain and local checkpoint verified across ${v.total} events (${v.legacy_records??0} legacy records lack full-field hashing).`:`Integrity check failed: chain or checkpoint mismatch. Events: ${v.tampered_ids.join(', ')||'see checkpoint'}.`);})}><Fingerprint size={16}/>Verify chain</button><button className="danger" disabled title="HTTP audit deletion is disabled; archive offline" onClick={clearAudit}>Clear log</button></div></div>{verification&&<p className="verification" role="status">{verification}</p>}<p className="audit-note">Latest 200 events. Expand an event to inspect its details. Block records mean an attempted action was stopped by policy, your decision, or an approval timeout. An agent ignoring an instruction without attempting a tool call does not produce a policy block; its saved answer appears in the result event.</p>{visibleAudit.length?[...visibleAudit].reverse().map(a=><details key={a.id} id={`audit-${a.id}`} tabIndex={-1} open={selectedAudit?.id===a.id?true:undefined} className={`audit-row ${selectedAudit?.id===a.id?'audit-selected':''}`}><summary><span className="event-id">#{a.id}</span><time>{clock(a.ts)}</time><strong>{a.event_type.replaceAll('_',' ')}</strong>{a.decision&&<span className={`badge ${a.decision}`}>{a.decision}</span>}</summary><ScrollFrame label="Details"><pre>{pretty(a.payload)}</pre></ScrollFrame></details>):<div className="empty">Start a session to see activity here.</div>}</section>}
    <footer><ShieldCheck size={14}/>AgentGuard <span>Policy enforcement · Human review · Verifiable history</span></footer></div></main><ZipperScrollbar page label="Page scrollbar" /></div>;
}
createRoot(document.getElementById('root')!).render(<React.StrictMode><App/></React.StrictMode>);
