const fs=require('node:fs');
const {chromium,webkit}=require('/Users/mustafa/Desktop/Artel-CRM/node_modules/playwright');
(async()=>{
 const credentials=fs.readFileSync('data/local-login.txt','utf8');
 const name=credentials.match(/Пользователь: (.+)/)[1],password=credentials.match(/Пароль: (.+)/)[1];
 const results=[];
 for(const [engine,type] of Object.entries({chromium,webkit})){
 const browser=await type.launch({headless:true});const context=await browser.newContext();
 const login=await context.request.post('http://127.0.0.1:8765/api/login',{data:{name,password}});if(!login.ok())throw Error('Login failed '+login.status());
 const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/api/**',r=>r.request().method()==='GET'?r.continue():r.abort());
 await page.goto('http://127.0.0.1:8765/data/orders');await page.locator('.panel-head').first().waitFor();
 const pages=await page.evaluate(()=>Object.values(sections).flat().map(key=>({key,path:pagePath(key)})));
 for(const width of [1440,768,320]){
 await page.setViewportSize({width,height:900});
 for(const item of pages){
 await page.goto('http://127.0.0.1:8765'+item.path);await page.waitForLoadState('networkidle');
 const check=await page.evaluate(()=>({download:[...document.querySelectorAll('button,a')].filter(e=>/Скачать/i.test(e.textContent)||e.hasAttribute('download')).map(e=>e.textContent),badAlign:[...document.querySelectorAll('.panel-head,.toolbar-actions,.actions,.refresh-bar,.refresh-overview,main>header')].filter(e=>['space-between','center','space-around','space-evenly','flex-end'].includes(getComputedStyle(e).justifyContent)).map(e=>e.className),overflow:document.documentElement.scrollWidth>innerWidth+1,heading:document.querySelector('h1')?.textContent,content:document.querySelector('#content')?.innerText.length||0}));
 results.push({engine,width,...item,...check,errors:errors.splice(0)});
 fs.writeFileSync('docs/layout-audit-20261029/results.json',JSON.stringify(results,null,2));
 if(width===1440&&['orders','plan_summary'].includes(item.key))await page.screenshot({path:`docs/layout-audit-20261029/${engine}-${item.key}.png`});
 }
 }
 await browser.close();
 }
 fs.writeFileSync('docs/layout-audit-20261029/results.json',JSON.stringify(results,null,2));
 const failed=results.filter(r=>r.download.length||r.badAlign.length||r.overflow||r.errors.length||!r.content);
 console.log(JSON.stringify({checks:results.length,pages:[...new Set(results.map(r=>r.key))],failed},null,2));
})().catch(e=>{console.error(e);process.exit(1)});
