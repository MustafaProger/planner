const fs=require('node:fs');
const {chromium}=require('/Users/mustafa/Desktop/Artel-CRM/node_modules/playwright');
(async()=>{
 const browser=await chromium.launch({headless:true}),context=await browser.newContext();
 const credentials=fs.readFileSync('data/local-login.txt','utf8');
 const login=await context.request.post('http://127.0.0.1:8765/api/login',{data:{name:credentials.match(/Пользователь: (.+)/)[1],password:credentials.match(/Пароль: (.+)/)[1]}});if(!login.ok())throw Error('Login failed');
 const page=await context.newPage(),errors=[],results=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/api/**',r=>r.request().method()==='GET'?r.continue():r.abort());
 await page.goto('http://127.0.0.1:8765/analytics/statistics');await page.locator('.table-tools').first().waitFor();
 const paths=await page.evaluate(()=>[...new Set(Object.values(sections).flat())].map(k=>pagePath(k)));
 for(const width of [1440,390,320]){
 await page.setViewportSize({width,height:1000});
 for(const path of paths){
 await page.goto('http://127.0.0.1:8765'+path);await page.waitForLoadState('networkidle');
 const result=await page.evaluate(()=>{const m=document.querySelector('.months'),buttons=m?[...m.querySelectorAll('button')]:[];return {overflow:document.documentElement.scrollWidth>innerWidth+1,counts:document.querySelectorAll('.table-count').length,searches:document.querySelectorAll('.table-tools').length,compact:document.querySelectorAll('.compact-table-head .table-tools').length,monthsOneRow:buttons.every(b=>b.offsetTop===buttons[0].offsetTop),monthsScrollable:!m||m.scrollWidth<=m.clientWidth||(()=>{m.scrollLeft=100;return m.scrollLeft>0})()}});
 results.push({width,path,...result,errors:errors.splice(0)});
 if(['/analytics/statistics','/analytics/comparison'].includes(path)&&width!==320){await page.locator('.compact-table-head').first().scrollIntoViewIfNeeded();await page.screenshot({path:`docs/compact-tables-20261029/${path.split('/').pop()}-${width}.png`})}
 }
 }
 await page.goto('http://127.0.0.1:8765/analytics/statistics');await page.locator('.table-search input').first().fill('zzzz-no-match');await page.locator('.table-wrap .empty:visible').first().waitFor();
 await page.locator('.table-search input').first().fill('');
 fs.writeFileSync('docs/compact-tables-20261029/results.json',JSON.stringify(results,null,2));
 console.log(JSON.stringify({checks:results.length,failed:results.filter(r=>r.overflow||r.counts||!r.monthsOneRow||!r.monthsScrollable||r.errors.length)},null,2));await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
