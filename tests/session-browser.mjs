import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { chromium } from 'playwright-core';

// Run against the built dashboard. API mocks avoid launching or modifying a real session.
const base = process.env.AGENTGUARD_CHECK_URL || 'http://127.0.0.1:8912';
const browser = await chromium.launch({
  headless: true,
  ...(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : { channel: 'chrome' }),
});
try {
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(() => {
    const scroll = Element.prototype.scrollIntoView;
    Element.prototype.scrollIntoView = function (...args) {
      scroll.apply(this, args);
      return Promise.resolve();
    };
  });
  const status = {
    workspace: 'C:\\workspace', policy_default: 'ask', agy: { version: 'test' },
    session: { state: 'stopped', model: null, sandbox: false, conversation_id: null },
  };
  let liveSocket;
  let clearRequests=0;
  await page.routeWebSocket('**/ws', socket => {
    liveSocket=socket;
    socket.send(JSON.stringify({ type: 'status', data: status }));
  });
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    let body = {};
    switch (path) {
      case '/api/config': body = { models: [], workspace: status.workspace }; break;
      case '/api/status': body = status; break;
      case '/api/approvals': body = { pending: [], history: [] }; break;
      case '/api/audit': if(route.request().method()==='DELETE'){clearRequests++;body={cleared:5,through_id:505};}else body = { events: [] }; break;
      case '/api/policy': body = { default_action: 'ask', rules: [] }; break;
      case '/api/session/start': assert.equal(route.request().postDataJSON().sandbox,true,'New sessions enable OS sandbox'); status.session.state = 'running'; body = status.session; break;
      case '/api/session/stop': status.session.state = 'stopped'; body = { stopped: true }; break;
      case '/api/session/message': body = { queued: true }; break;
      case '/api/workspace/files': body={directory:status.workspace,files:[{name:'test.txt',size_bytes:33}],skipped:0,truncated:false,audit_id:77}; break;
      default: throw new Error(`Unexpected API route: ${path}`);
    }
    await route.fulfill({ json: body });
  });
  await page.goto(base);
  await page.getByLabel('Session interface').selectOption('headless');
  await page.getByRole('button',{name:'List files',exact:true}).click();
  await page.getByLabel('Workspace file listing').waitFor();
  assert.ok((await page.getByLabel('Workspace file listing').innerText()).includes('test.txt'));
  assert.ok((await page.getByLabel('Workspace file listing').innerText()).includes('33'));
  await page.getByRole('button', { name: 'Start session', exact: true }).click();
  await page.getByRole('button', { name: 'Stop session', exact: true }).waitFor();
  assert.equal(await page.getByRole('heading', { name: 'A workspace with boundaries.' }).count(), 1);
  await page.getByRole('textbox', { name: 'Message your agent' }).fill('Test message');
  await page.getByRole('button', { name: 'Send', exact: true }).click();
  await page.locator('.message.user').filter({ hasText: 'Test message' }).waitFor();
  const emit=(data)=>liveSocket.send(JSON.stringify(data));
  const event=(payload,event='step_update')=>emit({type:'event',data:{event,conversation_id:'qa',payload}});
  event({step_type:'agent_response',step_index:1,state:'ACTIVE',text_delta:'Checking files.'});
  event({step_type:'agent_response',step_index:1,state:'DONE'});
  await page.getByRole('button',{name:'Copy response',exact:true}).waitFor();
  const records=[
    {id:501,event_type:'policy_eval',decision:'block',payload:{tool:'view_file',reason:'Path outside approved workspace: C:\\outside.txt',rule_id:'__workspace_containment'}},
    {id:502,event_type:'approval_decided',decision:'block',payload:{tool:'run_command',reason:'Default policy action',decided_by:'human'}},
    {id:503,event_type:'approval_decided',decision:'block',payload:{tool:'run_command',reason:'Default policy action (approval timed out)',decided_by:'timeout'}},
    {id:504,event_type:'tool_error',decision:null,payload:{tool:'run_command',error:{message:'Hook response could not be parsed'}}},
    {id:505,event_type:'tool_denied',decision:null,payload:{tool:'run_command',error:{message:'permission check failed for command "Get-ChildItem": user denied permission. Do not attempt to circumvent this denial.'}}},
  ];
  for(const record of records)emit({type:'action_issue',data:{...record,ts:new Date().toISOString()}});
  emit({type:'action_issue',data:{...records[0],ts:new Date().toISOString()}});
  await page.getByText('run_command: Approval timed out.',{exact:false}).waitFor();
  await page.getByText('Action not permitted',{exact:true}).waitFor();
  assert.equal(await page.getByLabel('Action notice').count(),5,'Duplicate audit events are ignored');
  assert.equal(await page.getByText('Do not attempt to circumvent',{exact:false}).count(),0,'Raw CLI instructions stay out of chat');
  await page.getByRole('button',{name:'Audit trail',exact:true}).click();
  await page.locator('#audit-501').waitFor();
  assert.equal(await page.locator('.audit-row').count(),5,'All live action issues appear without inspecting a chat link');
  assert.equal(await page.locator('#audit-501 .badge').innerText(),'block');
  await page.getByRole('button',{name:'Workspace',exact:true}).click();
  event({status:'SUCCESS',response:'Final answer: test.txt is 33 bytes.'},'result');
  await page.getByText('Final answer: test.txt is 33 bytes.',{exact:true}).waitFor();
  assert.equal(await page.locator('.message.agent').count(),2,'Final output survives earlier progress text');
  await mkdir('.qa',{recursive:true});
  await page.screenshot({path:'.qa/action-notices.png',fullPage:true});
  await page.getByRole('button',{name:'Inspect audit event #501',exact:true}).click();
  await page.locator('#audit-501[open]').waitFor();
  assert.ok((await page.locator('#audit-501').innerText()).includes('__workspace_containment'));
  assert.equal(await page.locator('#audit-501').evaluate(el=>el===document.activeElement),true);
  await page.getByRole('button',{name:'Workspace',exact:true}).click();
  await page.getByRole('button',{name:'Inspect audit event #505',exact:true}).click();
  await page.locator('#audit-505[open]').waitFor();
  assert.ok((await page.locator('#audit-505').innerText()).includes('Do not attempt to circumvent'),'Raw denial is preserved in audit');
  assert.equal(await page.getByRole('button',{name:'Clear log',exact:true}).isDisabled(),true);
  assert.equal(clearRequests,0,'Dashboard cannot delete the security audit');
  assert.equal(await page.locator('#audit-505[open]').count(),1);
  // Preserve compatibility with an older backend's explicit clear notification.
  liveSocket.send(JSON.stringify({type:'audit_cleared',data:{cleared:5,through_id:505}}));
  await page.locator('#audit-505').waitFor({state:'detached'});
  assert.equal(await page.locator('.audit-row').count(),0,'Clearing removes the selected cached audit event');

  await page.getByRole('button',{name:'Workspace',exact:true}).click();
  assert.equal(await page.getByLabel('Action notice').count(),0,'Cleared audit links are removed from chat');
  await page.getByRole('textbox', { name: 'Message your agent' }).fill('Second turn');
  await page.getByRole('button', { name: 'Send', exact: true }).click();
  await page.locator('.message.user').filter({hasText:'Second turn'}).waitFor();
  event({step_type:'agent_response',step_index:2,state:'ACTIVE',text_delta:'Partial'});
  event({status:'SUCCESS',response:'Partial response completed.'},'result');
  await page.getByText('Partial response completed.',{exact:true}).waitFor();
  assert.equal(await page.locator('.message.agent').count(),3,'Partial stream is completed without duplication');
  await page.getByRole('button', { name: 'Stop session', exact: true }).click();
  await page.getByRole('button', { name: 'Start session', exact: true }).waitFor();
  // Starting again clears existing messages, exercising the effect cleanup once more.
  await page.getByRole('button', { name: 'Start session', exact: true }).click();
  await page.getByRole('button', { name: 'Stop session', exact: true }).waitFor();
  assert.equal(await page.locator('.message.user').count(), 0);
  await page.getByRole('button',{name:'Policy',exact:true}).click();
  const editor = page.locator('#policy');
  const original = await editor.inputValue();
  await editor.fill(Array.from({length:150},(_,i)=>`line ${i}`).join('\n'));
  const editorScroll = page.getByRole('scrollbar',{name:'Policy editor vertical scrollbar'});
  await editorScroll.waitFor({state:'visible'});
  await editorScroll.press('End');
  assert.ok(await editor.evaluate(el=>el.scrollTop>0),'Editor scrollbar moves the textarea');
  assert.equal(await editor.inputValue(),Array.from({length:150},(_,i)=>`line ${i}`).join('\n'),'Scrollbar keys do not edit text');
  await editor.fill('{}');
  await editorScroll.waitFor({state:'hidden'});
  await editor.fill(original);
  assert.deepEqual(errors, [], 'No React errors during session transitions');
  console.log('PASS: Session transitions, block/error notices, audit navigation, and streamed/final responses.');
} finally {
  await browser.close();
}
