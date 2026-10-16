import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { chromium } from 'playwright-core';

async function setTheme(page, theme) {
  const toggle = page.getByRole('button', {name:'Dark mode', exact:true});
  if ((await toggle.getAttribute('aria-pressed') === 'true') !== (theme === 'dark')) await toggle.click();
  await page.waitForFunction(value => document.documentElement.dataset.theme === value, theme);
}


const base=process.env.AGENTGUARD_CHECK_URL || 'http://127.0.0.1:5174';
const browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{channel:'chrome'})});
const context=await browser.newContext({viewport:{width:1440,height:1100},permissions:['clipboard-read','clipboard-write']});
const errors=[], requests=[];
const page=await context.newPage();
page.on('pageerror', e=>errors.push(e.message));
page.on('request', r=>requests.push(r.url()));
let socket;
const status={workspace:'C:\\workspace',policy_default:'ask',agy:{version:'test'},session:{state:'stopped',model:null,sandbox:false,conversation_id:'qa'}};
await page.routeWebSocket('**/ws', ws=>{socket=ws;ws.send(JSON.stringify({type:'status',data:status}));});
await page.route('**/api/**',async route=>{
  const path=new URL(route.request().url()).pathname;
  let json={};
  if(path==='/api/config')json={models:[],workspace:status.workspace};
  if(path==='/api/status')json=status;
  if(path==='/api/approvals')json={pending:[],history:[]};
  if(path==='/api/audit')json={events:[]};
  if(path==='/api/policy')json={default_action:'ask',rules:[]};
  if(path==='/api/session/start'){status.session.state='running';json=status.session;}
  if(path==='/api/session/stop'){status.session.state='stopped';json={stopped:true};}
  if(path==='/api/session/message')json={queued:true};
  await route.fulfill({json});
});
function delta(text, step=0){socket.send(JSON.stringify({type:'event',data:{event:'step_update',conversation_id:'qa',payload:{step_type:'agent_response',step_index:step,state:'ACTIVE',text_delta:text}}}));}
function complete(){socket.send(JSON.stringify({type:'event',data:{event:'result',conversation_id:'qa',payload:{status:'success'}}}));}
const code='const greet = (name) => {\n  return `Hello, ${name}!`;\n};\n';
const rest=[
  ' and calm**. Use *emphasis*, ~~old text~~, and `inline code`.\n\n',
  '## Review the workspace\n\n### File changes\n\n#### Details\n\n##### Checks\n\n###### Notes\n\n',
  '- First item\n  - Nested item\n- Second item\n\n1. Inspect\n2. Review\n\n- [x] Tested\n- [ ] Ready for review\n\n',
  '> Keep every action within the approved workspace.\n\n---\n\n',
  '| File | Action | Result |\n| :--- | :--- | ---: |\n| `src/main.tsx` | Render | Passed |\n| `src/response.css` | Style | Passed |\n\n',
  '[Documentation](https://example.com/docs) and [unsafe](javascript:alert%281%29).\n\n',
  '```javascript\n'+code+'```\n\n',
  'Inline math: $E=mc^2$.\n\n$$\n\\int_0^1 x^2\\,dx=\\frac13\n$$\n\n',
  '```agentguard-json\n{"type":"notice","tone":"success","title":"Checks passed","body":"The workspace is ready for review."}\n```\n\n',
  '```agentguard-json\n{"type":"details","title":"Inspection details","body":"Only workspace files were inspected."}\n```\n\n',
  '<script>window.__injected=true</script>\n\n<img src="x" onerror="window.__injected=true">\n\n',
  '![Preview](https://tracking.invalid/pixel.png)\n\n',
  '```mermaid\ngraph LR\n  Review --> Approve\n```\n\n',
];
try{
  await page.goto(base);
  await page.getByLabel('Session interface').selectOption('headless');
  await page.getByRole('button',{name:'Start session',exact:true}).click();
  await page.getByRole('textbox',{name:'Message your agent'}).fill('Render a response');
  await page.getByRole('button',{name:'Send',exact:true}).click();
  await page.locator('.message.user').waitFor();
  delta('# A clear plan\n\nThis is **readable');
  await page.locator('.response-prose strong').filter({hasText:'readable'}).waitFor();
  assert.equal((await page.locator('.response-prose').innerText()).includes('**'),false,'Incomplete bold is repaired');
  for(const chunk of rest){delta(chunk);await page.waitForTimeout(35);}
  complete();
  await page.getByRole('button',{name:'Copy response',exact:true}).waitFor();
  for(let n=1;n<=6;n++)assert.equal(await page.locator(`.response-prose h${n}`).count(),1);
  assert.equal(await page.locator('.response-prose ul ul').count(),1);
  assert.equal(await page.locator('.response-prose ol').count(),1);
  assert.equal(await page.locator('.response-prose input:checked').count(),1);
  assert.equal(await page.locator('.response-prose input:disabled').count(),2);
  assert.equal(await page.locator('.response-prose blockquote').count(),1);
  assert.equal(await page.locator('.response-prose hr').count(),1);
  assert.equal(await page.locator('.response-table th').count(),3);
  assert.equal(await page.locator('.response-prose .katex-display').count(),1);
  assert.equal(await page.locator('.response-notice.success').count(),1);
  await page.getByText('Inspection details',{exact:true}).click();
  assert.equal(await page.locator('.response-details[open]').count(),1);
  await page.waitForFunction(()=>document.querySelector('.code-line span[style]'));
  const block=page.locator('.response-code').first();
  assert.equal(await block.locator('code').innerText(),code,'Code indentation and final newline preserved');
  await block.getByRole('button',{name:'Copy code',exact:true}).click();
  await block.getByRole('button',{name:'Copied',exact:true}).waitFor();
  assert.equal((await page.evaluate(()=>navigator.clipboard.readText())).replaceAll('\r\n','\n'),code,'Windows clipboard preserves code apart from native line endings');
  const link=page.getByRole('link',{name:'Documentation',exact:true});
  assert.equal(await link.getAttribute('target'),'_blank');
  assert.equal(await link.getAttribute('rel'),'noopener noreferrer');
  assert.equal(await page.locator('.response-prose a[href^="javascript:"]').count(),0);
  assert.equal(await page.locator('.response-prose script,.response-prose img,.response-prose iframe').count(),0);
  assert.equal(await page.evaluate(()=>window.__injected),undefined);
  assert.equal(requests.some(u=>u.includes('tracking.invalid')),false);
  const downloadEvent=page.waitForEvent('download');
  await page.getByRole('button',{name:'Download response as Markdown'}).click();
  assert.equal((await downloadEvent).suggestedFilename(),'agentguard-response.md');
  await mkdir('.qa',{recursive:true});
  await page.locator('.messages').evaluate(el=>{el.scrollTop=0;el.dispatchEvent(new Event('scroll'));});
  await page.screenshot({path:'.qa/response-light.png',fullPage:true});
  await setTheme(page, 'dark');
  assert.equal(await page.locator('html').getAttribute('data-theme'),'dark');
  await page.screenshot({path:'.qa/response-dark.png',fullPage:true});
  await block.scrollIntoViewIfNeeded();
  await page.locator('.conversation').screenshot({path:'.qa/response-code-dark.png'});
  await setTheme(page, 'light');
  await page.locator('.conversation').screenshot({path:'.qa/response-code-light.png'});
  await setTheme(page, 'dark');
  await page.locator('.messages').evaluate(el=>{el.scrollTop=0;el.dispatchEvent(new Event('scroll'));});

  // Stream long content and verify the reader's position is respected.
  delta('\n\n'+Array.from({length:100},(_,i)=>`Paragraph ${i}: A long response should remain comfortable to read.\n\n`).join(''));
  await page.waitForTimeout(250);
  assert.equal(await page.locator('.messages').evaluate(el=>el.scrollTop),0);
  await page.getByRole('button',{name:'Jump to latest'}).click();
  await page.waitForTimeout(100);
  assert.ok(await page.locator('.messages').evaluate(el=>el.scrollHeight-el.clientHeight-el.scrollTop<5));
  delta('```python\nprint("unfinished');
  await page.waitForTimeout(180);
  assert.ok((await page.locator('.response-code').last().innerText()).includes('unfinished'));
  delta('")\n```\n\n[partial link](https://exam');
  await page.waitForTimeout(100);
  assert.equal(await page.getByRole('link',{name:'partial link',exact:true}).count(),0);
  delta('ple.com)\n\n$$\n\\invalidcommand{\n$$\n\n');
  complete();
  await page.getByRole('link',{name:'partial link',exact:true}).waitFor();
  assert.ok(await page.locator('.katex-error').count());

  // Long code and wide tables must scroll inside their own panels.
  delta('\n\n```text\n'+ 'x'.repeat(450)+'\n```\n\n| '+Array.from({length:8},(_,i)=>'Column '+i).join(' | ')+' |\n| '+Array(8).fill('---').join(' | ')+' |\n| '+Array(8).fill('A wide value').join(' | ')+' |\n');
  complete();
  for(const width of [1024,768,390]){
    await page.setViewportSize({width,height:1000});await page.waitForTimeout(180);
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),`No page overflow at ${width}px`);
  }
  assert.ok(await page.locator('.response-code pre').last().evaluate(el=>el.scrollWidth>el.clientWidth),'Long code scrolls horizontally');
  assert.ok(await page.locator('.response-table').last().evaluate(el=>el.scrollWidth>el.clientWidth),'Wide table scrolls horizontally');
  const codeFrame = page.locator('.response-code').last();
  const horizontal = codeFrame.getByRole('scrollbar', {name:'text code horizontal scrollbar'});
  await horizontal.scrollIntoViewIfNeeded();
  await horizontal.press('End');
  assert.ok(await codeFrame.locator('pre').evaluate(el=>el.scrollLeft>0), 'Horizontal keyboard scroll moves code');
  await horizontal.press('Home');
  assert.equal(await codeFrame.locator('pre').evaluate(el=>el.scrollLeft),0);
  const box = await horizontal.boundingBox();
  await page.mouse.move(box.x+24,box.y+8); await page.mouse.down();
  await page.mouse.move(box.x+150,box.y+8,{steps:6}); await page.mouse.up();
  assert.ok(await codeFrame.locator('pre').evaluate(el=>el.scrollLeft>0), 'Horizontal drag moves code');
  assert.equal(await horizontal.getAttribute('aria-orientation'),'horizontal');
  assert.equal(await codeFrame.locator('pre').evaluate(el=>getComputedStyle(el).scrollbarWidth),'none');
  const tableScrollbar = page.getByRole('scrollbar',{name:'Table horizontal scrollbar'}).last();
  await tableScrollbar.press('End');
  assert.ok(await page.locator('.response-table').last().evaluate(el=>el.scrollLeft>0));
  await page.screenshot({path:'.qa/response-mobile.png',fullPage:true});
  // Every explicitly supported grammar must render tokens instead of silently falling back.
  const languages={typescript:'const n: number = 1;',tsx:'const view = <div>hello</div>;',jsx:'const view = <div>hello</div>;',python:'print("hello")',json:'{"ok": true}',bash:'echo "$HOME"',powershell:'Write-Output "hello"',css:'.item { color: red; }',html:'<div class="item">hello</div>',sql:'SELECT name FROM users;',yaml:'enabled: true'};
  for(const [language,source] of Object.entries(languages)){
    delta('\n\n```'+language+'\n'+source+'\n```\n');
  }
  complete();
  for(const language of Object.keys(languages)){
    const codePanel=page.locator('.response-code').filter({has:page.locator('.code-toolbar>span').filter({hasText:new RegExp('^'+language+'$')})}).last();
    await codePanel.locator('.code-line span[style]').first().waitFor();
  }
  delta('\n\n```agentguard-json\n{"type":"script","title":"No execution","body":"window.__injected=true"}\n```\n\n```agentguard-json\n{"type":"notice","tone":"info","title":"Plain title","body":"<img src=x onerror=alert(1)>"}\n```\n\n');
  complete();
  await page.locator('.response-notice.info').waitFor();
  assert.equal(await page.locator('.response-notice.info img').count(),0);
  assert.ok((await page.locator('.response-notice.info').innerText()).includes('<img'));
  assert.ok((await page.locator('.response-code').last().innerText()).includes('"type":"script"'));
  // Clipboard rejection must be recoverable and not crash the response.
  await page.evaluate(()=>Object.defineProperty(navigator.clipboard,'writeText',{configurable:true,value:()=>Promise.reject(new Error('denied'))}));
  await page.getByRole('button',{name:'Copy response',exact:true}).click();
  await page.getByText('Copy failed — retry',{exact:true}).waitFor();
  // Explicit selections persist across reload; no real session is touched.
  await page.reload();
  await page.waitForFunction(()=>document.documentElement.dataset.theme==='dark');
  assert.deepEqual(errors,[]);
  console.log('PASS: Markdown, math, code highlighting/copy/download, safe links/HTML/images, rich blocks, partial streams, long-response scrolling, themes and responsive overflow.');
}finally{await browser.close();}
