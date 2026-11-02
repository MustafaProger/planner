// Acceptance of report drill-downs with the real application and a disposable synthetic backend.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { createInterface } = require('node:readline');
const { chromium } = require('playwright');
const root = path.resolve(__dirname, '../..');
const output = path.resolve(process.env.ACCEPTANCE_OUTPUT || path.join(root, '.local/functional-followup-20261102'));
fs.mkdirSync(output, {recursive:true});
const result = {at:new Date().toISOString(), playwright:require('playwright/package.json').version, scenarios:[], errors:[], isolation:'temporary FLEET_DATA; scheduler disabled; synthetic books, users and saved provider response; real Python endpoints'};
const firstCar='Т711РМ797', firstDriver='Водитель · Первый';
let host,browser,timer;
const started=Date.now();
async function stop(){
  clearTimeout(timer);
  if(browser)await browser.close().catch(()=>{});
  if(host&&host.exitCode===null){const ended=new Promise(r=>host.once('exit',r));host.kill('SIGTERM');const kill=setTimeout(()=>host.kill('SIGKILL'),3000);await ended;clearTimeout(kill);}
}
async function start(){
  host=spawn(process.env.ACCEPTANCE_PYTHON||path.join(root,'.venv/bin/python'),[path.join(__dirname,'server.py')],{cwd:root,stdio:['ignore','pipe','pipe']});
  let error='';host.stderr.on('data',b=>{error=(error+b.toString()).slice(-1500)});
  return await new Promise((resolve,reject)=>{
    const startup=setTimeout(()=>reject(Error('Synthetic server startup exceeded 15 seconds')),15000);
    createInterface({input:host.stdout}).once('line',line=>{clearTimeout(startup);resolve('http://127.0.0.1:'+JSON.parse(line).port)});
    host.once('error',reject);host.once('exit',code=>{clearTimeout(startup);if(code)reject(Error('Synthetic host exited '+code+': '+error))});
  });
}
async function main(){
  timer=setTimeout(async()=>{result.errors.push('Global 120-second limit exceeded');await stop();process.exitCode=1},120000);
  const base=await start();browser=await chromium.launch({headless:true});result.chromium=browser.version();
  for(const viewport of [{width:1440,height:1000},{width:390,height:844}]){
    for(const role of ['admin','viewer']){
      const context=await browser.newContext({viewport,reducedMotion:'reduce'}),page=await context.newPage();page.setDefaultTimeout(7000);
      const errors=[],external=[];
      page.on('pageerror',e=>errors.push(e.message));
      await context.route('**/*',route=>{const url=new URL(route.request().url());if(url.origin!==base){external.push(url.origin+url.pathname);return route.abort()}return route.continue()});
      const go=async route=>{await page.goto(base+route);await page.locator('#content').waitFor();await page.waitForFunction(()=>!document.querySelector('#content')?.textContent.includes('Загрузка данных…'))};
      const select=async(selector,value)=>{
        const native=page.locator(selector);
        if(await native.isVisible())return native.selectOption({label:value});
        const wrapper=native.locator('..');const input=wrapper.getByRole('combobox');await input.fill(value);await page.getByRole('option',{name:value,exact:true}).click();
      };
      const filter=async({car='',driver=''})=>{
        await page.locator('#from').fill('2026-08-01');await page.locator('#to').fill('2026-08-02');
        if(car)await select('#car',car);if(driver)await select('#driver',driver);
        const loaded=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/workspace/report'&&r.status()===200);
        await page.locator('#apply').click();await loaded;await page.locator('#content tr[data-row]').first().waitFor();
      };
      const close=async()=>{await page.locator('#dialog .dialog-close').click();await page.locator('#dialog').waitFor({state:'hidden'})};
      const detail=async(row,keyboard=false)=>{
        const reply=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/workspace/report/details');
        if(keyboard){await row.focus();await row.press('Enter')}else await row.click();
        const response=await reply;assert.equal(response.status(),200);const body=await response.json();
        await page.locator('[data-report-details] [data-detail-plans]').waitFor();
        return body;
      };
      await page.goto(base);await page.locator('#auth-name').fill('acceptance-'+role);await page.locator('#auth-password').fill('isolated-test-only-password');await page.locator('#login button').click();await page.locator('#group').waitFor();
      await go('/analytics/planreport');await filter({car:firstCar,driver:firstDriver});
      const dated=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/workspace/report'&&new URL(r.url()).searchParams.get('group')==='date');await select('[name=workspaceGroup]','Дни');await dated;await page.waitForFunction(()=>document.querySelector('#content tr[data-row] td')?.textContent.trim()!=='Т711РМ797');
      const plans=await detail(page.locator('#content tr[data-row]').first(),true);
      assert.equal(plans.name,'2026-08-01');assert.equal(plans.summary.revenue,2000);assert.equal(plans.plans.length,2);assert.equal(plans.excluded_plans.length,2);
      assert.equal(await page.locator('[data-detail-plans] tbody tr').count(),2);
      assert.equal(await page.locator('[data-detail-excluded-plans] tbody tr').count(),2);
      assert.ok((await page.locator('[data-report-details]').innerText()).replace(/\s/g,'').includes('2000'));
      assert.deepEqual(plans.scope,{from:'2026-08-01',to:'2026-08-02',vehicle:firstCar,driver:firstDriver});
      await page.screenshot({path:path.join(output,'plans-'+role+'-'+viewport.width+'.png')});await close();
      await go('/analytics/comparison');await filter({driver:firstDriver});
      await page.locator('[name=workspaceGroup]').selectOption('pair');
      await page.waitForFunction(()=>document.querySelector('#content tr[data-row]')?.textContent.includes(' · '));
      const comparison=await detail(page.locator('#content tr[data-row]').filter({hasText:firstCar}));
      assert.equal(comparison.name,firstCar+' · '+firstDriver);assert.equal(comparison.summary.plan_revenue,2000);assert.equal(comparison.summary.fact_revenue,3000);assert.equal(comparison.summary.delta_revenue,null);
      assert.equal(comparison.plans.length,2);assert.equal(comparison.trips.length,2);assert.equal(comparison.excluded_trips.length,2);
      assert.deepEqual(comparison.trips.map(x=>x.id).sort(),['1','2']);assert.equal(comparison.summary.fact_km,null);
      assert.equal(await page.locator('[data-detail-trips] tbody tr').count(),2);assert.equal(await page.locator('[data-detail-excluded-trips] tbody tr').count(),2);
      await page.screenshot({path:path.join(output,'comparison-'+role+'-'+viewport.width+'.png')});await close();
      // Set an unrelated calendar month, then navigate in-app to retain a real return context.
      await go('/planning/calendar');await page.locator('#calMonth').fill('2026-07');await page.locator('#calMonth').dispatchEvent('change');
      if(viewport.width<700)await page.locator('#menu-toggle').click();
      await page.locator('[data-tab=reconcile]').click();await page.locator('#from').waitFor();
      await page.locator('#from').fill('2026-08-01');await page.locator('#to').fill('2026-08-02');await select('#car',firstCar);
      const reconcileLoaded=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/reconcile');await page.locator('#apply').click();await reconcileLoaded;
      const reconcileReply=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/reconcile/details');
      await page.locator('#content tr[data-row]').first().click();
      const reconcileResponse=await reconcileReply;assert.equal(reconcileResponse.status(),200);const day=await reconcileResponse.json();
      await page.locator('[data-reconcile-details] [data-detail-satellite]').waitFor();
      assert.equal(day.date,'2026-08-01');assert.equal(day.vehicle,firstCar);assert.equal(day.summary.sat_km,334);assert.equal(day.summary.sat_hours,24);assert.equal(day.summary.sat_engine_hours,5);
      assert.equal(day.satellite.length,1);assert.equal(day.satellite_raw.length,1);assert.equal(day.satellite_raw[0].km,310);
      assert.equal(day.metric_usage.km.excel_role,'replaced_by_api');assert.equal(day.metric_usage.hours.excel_role,'used');
      assert.equal(await page.locator('[data-detail-satellite] table').last().locator('tbody tr').count(),1);assert.equal(await page.locator('[data-detail-satellite-raw] tbody tr').count(),1);
      const dayText=await page.locator('[data-reconcile-details]').innerText();assert.ok(dayText.includes('334')&&dayText.includes('310')&&dayText.includes('ГЛОНАССсофт API')&&dayText.includes('Excel'));
      await page.locator('[data-detail-satellite]').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(output,'reconcile-'+role+'-'+viewport.width+'.png')});
      await page.locator('#detail-calendar').click();await page.locator('#calMonth').waitFor();
      assert.equal(new URL(page.url()).pathname,'/planning/calendar');assert.equal(await page.locator('#calMonth').inputValue(),'2026-08');assert.equal(await page.locator('#car').inputValue(),firstCar);
      assert.ok((await page.locator('[data-day="2026-08-01"]').first().innerText()).includes('Сервис'));
      await page.goBack();await page.locator('#from').waitFor();
      assert.equal(new URL(page.url()).pathname,'/analytics/reconcile');assert.equal(await page.locator('#from').inputValue(),'2026-08-01');assert.equal(await page.locator('#to').inputValue(),'2026-08-02');assert.equal(await page.locator('#car').inputValue(),firstCar);
      await page.goForward();await page.locator('#calMonth').waitFor();assert.equal(await page.locator('#calMonth').inputValue(),'2026-08');assert.equal(await page.locator('#car').inputValue(),firstCar);
      await page.goBack();await page.locator('#from').waitFor();
      await page.goBack();await page.locator('#calMonth').waitFor();assert.equal(await page.locator('#calMonth').inputValue(),'2026-07');
      // The dashboard must open the same explanatory card rather than a trip-only modal.
      await go('/analytics/dashboard');
      const dashReply=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/reconcile/details');
      await page.locator('#content tr[data-row]').filter({hasText:'У930ЕХ797'}).click();
      const dash=await (await dashReply).json();await page.locator('[data-reconcile-details] #detail-calendar').waitFor();
      assert.equal(dash.vehicle,'У930ЕХ797');assert.equal(dash.date,'2026-08-02');assert.equal(dash.summary.sat_km,150);
      await page.locator('#detail-calendar').click();await page.locator('#calMonth').waitFor();assert.equal(await page.locator('#car').inputValue(),'У930ЕХ797');
      await page.goBack();await page.locator('#from').waitFor();assert.equal(new URL(page.url()).pathname,'/analytics/dashboard');
      // A satellite-only vehicle has a selected day but no invented trip or downtime record.
      await go('/analytics/reconcile');await page.locator('#from').fill('2026-08-04');await page.locator('#to').fill('2026-08-04');await select('#car','А111АА797');
      const onlyLoaded=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/reconcile');await page.locator('#apply').click();await onlyLoaded;
      const onlyReply=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/reconcile/details');await page.locator('#content tr[data-row]').first().click();
      const only=await (await onlyReply).json();await page.locator('[data-reconcile-details] #detail-calendar').waitFor();
      assert.equal(only.trips.length,0);assert.equal(only.summary.sat_km,88);assert.ok((await page.locator('[data-detail-trips]').innerText()).includes('нет учтённых'));
      await page.locator('#detail-calendar').click();await page.locator('#calMonth').waitFor();assert.equal(await page.locator('#car').inputValue(),'А111АА797');
      assert.ok((await page.locator('[data-calendar-focus]').innerText()).includes('2026-08-04'));
      assert.equal(await page.locator('#content [data-day]').count(),0);assert.ok((await page.locator('#content').innerText()).includes('нет фактических записей'));
      await page.goBack();await page.locator('#from').waitFor();assert.equal(await page.locator('#from').inputValue(),'2026-08-04');assert.equal(await page.locator('#car').inputValue(),'А111АА797');
      assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
      assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
      result.scenarios.push({viewport,role,plans:{rows:plans.plans.length,excluded:plans.excluded_plans.length,revenue:plans.summary.revenue},comparison:{plans:2,trips:2,excluded_charges:2,plan_revenue:2000,fact_revenue:3000,delta_revenue:null},reconcile:{effective_km:334,raw_excel_km:310,interval_hours_from_excel:24,engine_hours_from_api:5},navigation:'selected car/day to calendar; Back source period/car and original July calendar; Forward selected August calendar; dashboard card; satellite-only empty calendar' ,page_errors:errors.length,external_requests:external.length});
      await context.close();
    }
  }
}
(async()=>{try{await main();result.status='passed'}catch(e){result.status='failed';result.errors.push(e.stack);process.exitCode=1}finally{await stop();result.elapsed_seconds=(Date.now()-started)/1000;fs.writeFileSync(path.join(output,'browser.json'),JSON.stringify(result,null,2)+'\n');console.log(JSON.stringify(result,null,2))}})();
