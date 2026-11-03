const fs=require('node:fs');const {chromium,webkit}=require('/Users/mustafa/Desktop/Artel-CRM/node_modules/playwright');
(async()=>{const login=fs.readFileSync('data/local-login.txt','utf8');const results=[];
for(const [engine,type] of Object.entries({chromium,webkit})){
 const browser=await type.launch();const ctx=await browser.newContext();const response=await ctx.request.post('http://127.0.0.1:8765/api/login',{data:{name:login.match(/Пользователь: (.+)/)[1],password:login.match(/Пароль: (.+)/)[1]}});if(!response.ok())throw Error('Login failed');
 for(const width of [1440,768,320]){
 const page=await ctx.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));await page.route('**/api/**',r=>r.request().method()==='GET'?r.continue():r.abort());
 await page.setViewportSize({width,height:1000});await page.goto('http://127.0.0.1:8765/analytics/downtime');await page.waitForLoadState('networkidle');
 const before=await page.evaluate(()=>{const input=document.querySelector('[name=downtimeEntity]'),label=input.closest('label'),bar=label.parentElement,s=getComputedStyle(bar),r=bar.getBoundingClientRect();return {download:!!document.querySelector('#export'),gap:Math.abs(label.getBoundingClientRect().right-(r.right-parseFloat(s.paddingRight)-parseFloat(s.borderRightWidth))),overflow:document.documentElement.scrollWidth>innerWidth+1}});
 await page.locator('[name=downtimeEntity]').selectOption('driver');await page.waitForLoadState('networkidle');const driver=await page.locator('[name=downtimeEntity]').inputValue();
 results.push({engine,width,...before,driver,errors:errors.splice(0)});
 if(width===1440){await page.locator('[name=downtimeEntity]').selectOption('vehicle');await page.waitForLoadState('networkidle');await page.screenshot({path:`docs/downtime-control-20261029/${engine}.png`});}
 await page.close();const other=await ctx.newPage();await other.goto('http://127.0.0.1:8765/analytics/planreport');await other.waitForLoadState('networkidle');if(!await other.locator('#export').count())throw Error('Other report export changed');await other.close();
 }
 await browser.close();
}
fs.writeFileSync('docs/downtime-control-20261029/results.json',JSON.stringify(results,null,2));console.log(JSON.stringify(results));if(results.some(r=>r.download||r.gap>1||r.overflow||r.driver!=='driver'||r.errors.length))process.exit(1);
})().catch(e=>{console.error(e);process.exit(1)});
