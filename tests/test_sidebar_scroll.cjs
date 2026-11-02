const {test,expect}=require('@playwright/test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');

const root=path.resolve(__dirname,'..');
const origin='http://fleet.test';
const apiFixtures={
 '/api/session':{user:{id:1,name:'Sidebar test',role:'admin',vehicles:[]},csrf:'synthetic-test-token'},
 '/api/data':{trips:[],plans:[],drivers:{},vehicles:{},statuses:[],satellite:[]},
 '/api/connections':[
  {id:'transtrade',name:'ТрансТрейд',detail:'Synthetic fixture',status:'Тест'},
  {id:'monitoring',name:'ГЛОНАССсофт',detail:'Synthetic fixture',status:'Тест'},
  {id:'neftm',name:'Нефтьмагистраль',detail:'Synthetic fixture',status:'Тест'},
  {id:'rosneft',name:'Роснефть',detail:'Synthetic fixture',status:'Тест'},
 ],
 '/api/refresh':{status:'idle',server_scheduler:false,sources:{},last_finished_at:null,alerts:{incidents:[],recent:[],delivery:{configured:false}}},
};
const staticFiles=new Set(['style.css','main.js','workspace.js','ui.js','planviews.js','motion.js','evidence.js','refresh.js']);

test('sidebar keeps scroll across navigation, rerender, Back and Forward',async({page,context,browser},testInfo)=>{
 const mobile=testInfo.project.name==='mobile';
 const scroller=mobile?'.sidebar':'.sidebar nav';
 const unexpected=[],pageErrors=[],requests=[];
 const positions={};
 const mark=async step=>{
  // Wait for layout/mutation observers after render. Exact pixels detect a
  // reset: no tolerance and no replacing the expected value after navigation.
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  positions[step]=await page.locator(scroller).evaluate(el=>el.scrollTop);
  assert.equal(positions[step],positions.initial,`sidebar scroll after ${step}`);
 };
 page.on('pageerror',error=>pageErrors.push(error.message));
 await context.route('**/*',async route=>{
  const request=route.request(),url=new URL(request.url());
  requests.push(request.method()+' '+url.pathname);
  if(url.origin===origin&&request.method()==='GET'){
   if(Object.hasOwn(apiFixtures,url.pathname)&&!url.search)return route.fulfill({json:apiFixtures[url.pathname]});
   if(['/settings/connections','/help/guide'].includes(url.pathname)&&request.isNavigationRequest())return route.fulfill({path:path.join(root,'app/static/index.html'),contentType:'text/html'});
   const name=url.pathname.replace('/static/','');
   if(url.pathname==='/static/'+name&&staticFiles.has(name))return route.fulfill({body:fs.readFileSync(path.join(root,'app/static',name)),contentType:name.endsWith('.js')?'application/javascript':'text/css'});
  }
  unexpected.push(request.method()+' '+url.href);
  return route.abort('blockedbyclient');
 });
 await test.step('open real connections page with exact mocked APIs',async()=>{
  await page.goto(origin+'/settings/connections');
  await expect(page.locator('#main h1')).toHaveText('Подключения');
  await expect(page.locator('.source-card')).toHaveCount(4);
  await expect(page.locator('#data-refresh')).toBeVisible();
 });
 await test.step('scroll overflowing sidebar',async()=>{
  if(mobile)await page.locator('#menu-toggle').click();
  positions.initial=await page.locator(scroller).evaluate(el=>{el.scrollTop=el.scrollHeight;return el.scrollTop});
  assert.ok(positions.initial>0,'fixture must overflow');
  await expect(page.locator('[data-tab="guide"]')).toBeVisible();
 });
 await test.step('navigate to guide',async()=>{
  const selector=process.env.SIDEBAR_FAILURE_PROBE==='selector'?'[data-tab="missing-probe"]':'[data-tab="guide"]';
  await page.locator(selector).click();
  await expect(page).toHaveURL(origin+'/help/guide');
  await expect(page.locator('#main h1')).toHaveText('Как пользоваться');
  await expect(page.locator('.guide-map')).toBeVisible();
  if(process.env.SIDEBAR_FAILURE_PROBE==='scroll-reset')await page.locator(scroller).evaluate(el=>{el.scrollTop=0});
  await mark('navigation');
 });
 await test.step('rerender current view',async()=>{
  await page.evaluate(()=>render());
  await expect(page.locator('.guide-map')).toBeVisible();
  await mark('rerender');
 });
 await test.step('browser Back restores connections',async()=>{
  await page.goBack();
  await expect(page).toHaveURL(origin+'/settings/connections');
  await expect(page.locator('.source-card')).toHaveCount(4);
  await mark('back');
 });
 await test.step('browser Forward restores guide',async()=>{
  await page.goForward();
  await expect(page).toHaveURL(origin+'/help/guide');
  await expect(page.locator('.guide-map')).toBeVisible();
  await mark('forward');
  if(mobile){
   await page.locator('#menu-toggle').click();
   await expect(page.locator('.sidebar')).toBeVisible();
   await mark('reopen');
  }
 });
 assert.deepEqual(unexpected,[],'all network requests must match the allowlisted fixture');
 assert.deepEqual(pageErrors,[],'browser must not hide runtime errors');
 for(const endpoint of Object.keys(apiFixtures))assert.ok(requests.includes('GET '+endpoint),`fixture reached ${endpoint}`);
 console.log(JSON.stringify({scenario:'sidebar',viewport:testInfo.project.name,browser:browser.version(),positions,unexpectedRequests:unexpected.length,pageErrors:pageErrors.length,requests}));
});
