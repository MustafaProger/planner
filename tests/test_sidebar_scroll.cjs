const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const {chromium}=require('playwright');

for(const [name,width,height,scroller] of [
 ['desktop',1440,700,'.sidebar nav'],
 ['mobile',390,600,'.sidebar'],
])test(`sidebar keeps scroll across navigation and rerender (${name})`,async()=>{
 const browser=await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL||undefined});
 try{
  const page=await browser.newPage({viewport:{width,height}});
  await page.route('http://fleet.test/**',route=>{
   const path=new URL(route.request().url()).pathname;
   if(path.startsWith('/api/')){
    const body=path==='/api/session'?{user:{name:'Test',role:'admin'},csrf:'test'}:
     path==='/api/data'?{trips:[],plans:[],drivers:{},statuses:[]}:
     ['rosneft','transtrade','axenta'].map(id=>({id,detail:'Test',status:'Test'}));
    return route.fulfill({json:body});
   }
   const file=path.startsWith('/static/')?'app'+path:'app/static/index.html';
   return route.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'text/html'});
  });
  await page.goto('http://fleet.test/integrations/rosneft');
  await page.locator('.connection').waitFor();
  if(name==='mobile')await page.locator('#menu-toggle').click();
  const before=await page.locator(scroller).evaluate(el=>{el.scrollTop=el.scrollHeight;return el.scrollTop});
  assert.ok(before>0,'fixture must overflow');
  await page.locator('[data-tab="transtrade"]').click();
  await page.waitForURL('**/integrations/transtrade');
  await page.locator('.connection[data-source="transtrade"]').waitFor();
  const check=async()=>assert.equal(await page.locator(scroller).evaluate(el=>el.scrollTop),before);
  await check();
  await page.evaluate(()=>render());await check();
  await page.goBack();await page.locator('.connection[data-source="rosneft"]').waitFor();await check();
  await page.goForward();await page.locator('.connection[data-source="transtrade"]').waitFor();await check();
 }finally{await browser.close()}
});
