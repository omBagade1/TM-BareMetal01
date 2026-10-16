import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { chromium } from 'playwright-core';

async function setTheme(page, theme) {
  const toggle = page.getByRole('button', {name:'Dark mode', exact:true});
  if ((await toggle.getAttribute('aria-pressed') === 'true') !== (theme === 'dark')) await toggle.click();
  await page.waitForFunction(value => document.documentElement.dataset.theme === value, theme);
}


// Presentation regression checks. All transport is mocked; no real agent is started.
const base = process.env.AGENTGUARD_CHECK_URL || 'http://127.0.0.1:5174';
const browser = await chromium.launch({headless:true, ...(process.env.CHROME_PATH ? {executablePath:process.env.CHROME_PATH} : {channel:'chrome'})});
await mkdir('.qa/redesign', {recursive:true});
try {
  const page = await browser.newPage({viewport:{width:1440,height:1000}});
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  const consoleIssues = [];
  page.on('console', msg => {if(['error','warning'].includes(msg.type())) consoleIssues.push(msg.text());});
  const status = {workspace:'C:\\Users\\Akhilesh\\Downloads\\jnec\\workspace', policy_default:'ask', ultra_security:false,
    agy:{version:'test'}, session:{state:'stopped'}, enforcement:{state:'UNVERIFIED',boundary:'No verified OS boundary',network:'Network enforcement has not been tested.',last_launch:{status:'not verified'}}};
  let policy = {default_action:'ask',rules:[]};
  const pending = ['read','write'].map((id,i)=>({id,ts:new Date().toISOString(),tool:i?'write_file':'view_file',args:{AbsolutePath:'C:\\workspace\\test.txt'},reason:'This action requires your review.'}));
  const history = [];
  const events = [{id:21,ts:new Date().toISOString(),event_type:'policy_eval',decision:'ask',payload:{tool:'view_file',reason:'Default policy'}}];
  const calls = [];
  await page.routeWebSocket('**/ws', socket => socket.send(JSON.stringify({type:'status',data:status})));
  await page.route('**/api/**', async route => {
    const req=route.request(), path=new URL(req.url()).pathname, method=req.method();
    const data=req.postData()?req.postDataJSON():undefined;
    calls.push({path,method,data});
    let body={};
    if(path==='/api/config') body={workspace:status.workspace,models:[{id:'test-model',label:'Test model'}],gemini_acp_available:true};
    else if(path==='/api/status') body=status;
    else if(path==='/api/approvals') body={pending,history};
    else if(path.startsWith('/api/approvals/')) { const index=pending.findIndex(a=>a.id===path.split('/').at(-1)); assert.ok(index>=0); history.push({...pending.splice(index,1)[0],decision:data.decision,decided_by:'human'}); body={ok:true}; }
    else if(path==='/api/policy') {if(method==='PUT') policy=data.data; body=policy;}
    else if(path==='/api/policy/evaluate') body={decision:'ask',reason:'Default policy'};
    else if(path==='/api/policy/ultra-security') { status.ultra_security=data.enabled; body={enabled:data.enabled}; }
    else if(path==='/api/audit') body={events};
    else if(path==='/api/audit/verify') body={verified:true,total:1,tampered_ids:[],legacy_records:0};
    else if(path==='/api/security/results') body={state:'UNVERIFIED',tests:[]};
    else throw new Error(`Unexpected API: ${method} ${path}`);
    await route.fulfill({json:body});
  });
  await page.goto(base);
  await page.getByRole('button',{name:'Start session',exact:true}).waitFor();
  await page.locator('.workspace-layout').evaluate(async el => { await Promise.all(el.getAnimations().map(animation => animation.finished)); });
  const conversation=page.locator('.conversation');
  const originalConversation=await conversation.boundingBox();
  const controls=page.locator('#session-controls-drawer');
  assert.ok((await controls.boundingBox()).x < originalConversation.x, 'Session controls are on the left');
  await page.getByRole('button',{name:'Hide session controls',exact:true}).click();
  assert.equal(await controls.isVisible(),false);
  assert.ok((await conversation.boundingBox()).width > originalConversation.width, 'Collapsing settings widens conversation');
  await page.getByRole('button',{name:'Show session controls',exact:true}).click();
  assert.equal(await controls.isVisible(),true);
  const queue=page.getByRole('region',{name:'Permission queue',exact:true});
  const queueBefore=await queue.boundingBox();
  const restoredConversation=await conversation.boundingBox();
  assert.ok(queueBefore.y >= restoredConversation.y + restoredConversation.height - 1, 'Approvals sit below the conversation');
  await page.screenshot({path:'.qa/redesign/workspace-light.png',fullPage:true});
  const navigate = async name => {await page.locator('nav button').filter({hasText:name}).click();};
  await navigate('Approvals');
  await page.screenshot({path:'.qa/redesign/approvals-light.png',fullPage:true});
  await navigate('Workspace');
  await page.getByRole('button',{name:'Allow once',exact:true}).first().click();
  await page.waitForFunction(()=>document.querySelectorAll('.approval').length===1);
  await page.getByRole('button',{name:'Block',exact:true}).click();
  await page.locator('.workspace-review.is-clear').waitFor();
  assert.ok((await queue.boundingBox()).height < queueBefore.height, 'Resolved approvals release their space');
  await navigate('Approvals');
  await page.getByRole('heading',{name:'All clear',exact:true}).waitFor();
  assert.deepEqual(history.map(a=>a.decision),['allow','block']);
  await page.locator('details summary').first().click();
  assert.ok(await page.locator('details[open] pre').innerText());
  await navigate('Policy');
  await page.locator('#policy').fill('{invalid');
  await page.getByRole('button',{name:'Save policy',exact:true}).click();
  await page.getByRole('alert').waitFor();
  assert.equal(calls.filter(c=>c.method==='PUT').length,0,'Invalid JSON is not submitted');
  await page.getByRole('button',{name:'Dismiss error'}).click();
  const edited={default_action:'block',rules:[]};
  await page.locator('#policy').fill(JSON.stringify(edited));
  await page.getByRole('button',{name:'Save policy',exact:true}).click();
  await page.getByText('Policy saved. New actions will use these rules.').waitFor();
  assert.deepEqual(policy,edited);
  await page.locator('#policy').fill('{}');
  await page.getByRole('button',{name:'Reload saved'}).click();
  await page.waitForFunction(()=>document.querySelector('#policy').value.includes('block'));
  await page.getByLabel('Tool name',{exact:true}).fill('view_file');
  await page.getByRole('button',{name:'Evaluate action'}).click();
  await page.locator('.result').waitFor();
  assert.ok((await page.locator('.result').innerText()).includes('ask'));
  await page.getByRole('button',{name:'Enable Ultra Security Mode'}).click();
  await page.getByRole('button',{name:'Switch to Standard Mode'}).waitFor();
  assert.equal(status.ultra_security,true);
  await page.screenshot({path:'.qa/redesign/policy-light.png',fullPage:true});
  await navigate('Audit trail');
  await page.getByRole('button',{name:'Verify chain'}).click();
  await page.locator('.verification').waitFor();
  assert.ok((await page.locator('.verification').innerText()).includes('verified across 1'));
  const download=page.waitForEvent('download');
  await page.getByRole('button',{name:'Export JSON'}).click();
  assert.equal((await download).suggestedFilename(),'agentguard-audit.json');
  assert.equal(await page.getByRole('button',{name:'Clear log'}).isDisabled(),true);
  await page.locator('.audit-row summary').click();
  await page.screenshot({path:'.qa/redesign/audit-light.png',fullPage:true});
  await navigate('Workspace');
  await page.getByRole('button',{name:'View retained test results'}).click();
  await page.getByText('Recorded results (not a live certification)').waitFor();
  await page.getByLabel('Agent backend').selectOption('ollama');
  await page.getByLabel('Open-weight model').selectOption('qwen3:8b');
  await page.getByLabel('Agent backend').selectOption('gemini-acp');
  await page.getByText('AgentGuard applies policy to ACP permission requests,').waitFor();
  await page.getByLabel('Agent backend').selectOption('agy');
  await page.getByLabel('Session interface').selectOption('headless');
  await page.getByRole('button',{name:'Read test.txt and summarize it.',exact:true}).click();
  assert.equal(await page.getByRole('textbox',{name:'Message your agent',exact:true}).inputValue(),'Read test.txt and summarize it.');
  await page.screenshot({path:'.qa/redesign/chat-light.png',fullPage:true});
  for(const theme of ['light','dark']) {
    await setTheme(page, theme);
    for(const width of [1440,1024,768,390,320]) {
      await page.setViewportSize({width,height:900});
      for(const tab of ['Workspace','Approvals','Policy','Audit trail']) {
        await navigate(tab);
        assert.equal(await page.locator('nav button[aria-current="page"]').count(),1);
        const geometry=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));
        assert.ok(geometry.scroll<=geometry.width+1,`${tab} ${theme} ${width}: overflow ${JSON.stringify(geometry)}`);
        if(width===390 || (width===1440 && theme==='dark')) await page.screenshot({path:`.qa/redesign/${tab.replaceAll(' ','-')}-${theme}-${width}.png`,fullPage:true});
      }
    }
  }
  await page.setViewportSize({width:1440,height:1000});
  await navigate('Workspace');
  await page.getByLabel('Session interface').selectOption('terminal');
  await page.screenshot({path:'.qa/redesign/terminal-dark.png',fullPage:true});
  await page.emulateMedia({reducedMotion:'reduce'});
  const policyNav=page.locator('nav button').filter({hasText:'Policy'});
  await page.keyboard.press('Tab');
  await policyNav.focus();
  assert.equal(await policyNav.evaluate(el=>getComputedStyle(el).outlineStyle),'solid');
  await page.keyboard.press('Enter');
  await page.getByRole('heading',{name:'Policy',exact:true}).waitFor();
  await page.locator('.skip-link').focus();
  await page.keyboard.press('Enter');
  assert.equal(await page.evaluate(()=>document.activeElement.id),'main-content');
  assert.equal(await page.locator('.page-heading').evaluate(el=>getComputedStyle(el).animationName),'none');
  assert.deepEqual(errors,[]);
  assert.deepEqual(consoleIssues,[],'No browser console errors or warnings');
  console.log('PASS: All four views at 320/390/768/1024/1440px in both themes; approvals, policy save/reload/validation/evaluation, security mode, evidence, audit verify/export, provider controls, suggestions, keyboard skip and reduced motion. Transport mocked.');
} finally { await browser.close(); }
