// Live UI acceptance against a disposable synthetic Python host; no production access.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { createInterface } = require('node:readline');
const { chromium } = require('playwright');
const root = path.resolve(__dirname, '../../..');
const output = path.resolve(process.env.ACCEPTANCE_OUTPUT || path.join(root, '.local/customer-acceptance-20261102'));
fs.mkdirSync(output, { recursive: true });
const started = Date.now();
const result = { at: new Date().toISOString(), playwright: require('playwright/package.json').version, isolation: 'temporary FLEET_DATA; scheduler disabled; generated workbooks; test users; no provider requests', viewports: [], errors: [] };
let host, browser, timeout;
async function readyServer() {
  const python = process.env.ACCEPTANCE_PYTHON || path.join(root, '.venv/bin/python');
  host = spawn(python, [path.join(__dirname, 'server.py')], { cwd: root, stdio: ['ignore', 'pipe', 'pipe'] });
  host.stderr.on('data', () => {}); // Flask access logs carry no acceptance evidence.
  return await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(Error('Synthetic server startup exceeded 15 seconds')), 15000);
    const lines = createInterface({ input: host.stdout });
    lines.once('line', line => { clearTimeout(timer); resolve('http://127.0.0.1:' + JSON.parse(line).port); });
    host.once('error', reject);
    host.once('exit', code => { clearTimeout(timer); if (code) reject(Error('Synthetic server exited: ' + code)); });
  });
}
async function stop() {
  clearTimeout(timeout);
  if (browser) await browser.close().catch(() => {});
  if (host && host.exitCode === null) {
    const ended = new Promise(resolve => host.once('exit', resolve));
    host.kill('SIGTERM');
    const kill = setTimeout(() => host.kill('SIGKILL'), 3000);
    await ended; clearTimeout(kill);
  }
}
async function main() {
  timeout = setTimeout(async () => { result.errors.push('Global 120-second limit'); await stop(); process.exitCode = 1; }, 120000);
  const base = await readyServer();
  browser = await chromium.launch({ headless: true });
  result.chromium = browser.version();
  for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
    const context = await browser.newContext({ viewport, reducedMotion: 'reduce', acceptDownloads: true });
    const page = await context.newPage();
    page.setDefaultTimeout(7000);
    const errors = [], external = [];
    let refreshStamp = '2026-08-01T00:00:00Z', dataGets = 0;
    page.on('pageerror', error => errors.push(error.message));
    page.on('request', req => { if (new URL(req.url()).pathname === '/api/data') dataGets++; });
    await context.route('**/*', async route => {
      const url = new URL(route.request().url());
      if (url.origin !== base) { external.push(url.origin + url.pathname); return route.abort(); }
      if (url.pathname === '/api/refresh' && route.request().method() === 'GET') {
        return route.fulfill({ json: { status: 'success', last_finished_at: refreshStamp, server_scheduler: false, sources: {}, alerts: { incidents: [], delivery: { configured: false } } } });
      }
      return route.continue();
    });
    const checks = [];
    const go = async (route, marker) => {
      await page.goto(base + route);
      await page.locator('#content').waitFor();
      if (marker) await page.locator(marker).first().waitFor();
      await page.waitForFunction(() => !document.querySelector('#content')?.textContent.includes('Загрузка данных…'));
    };
    await page.goto(base);
    await page.locator('#auth-name').fill('acceptance-admin');
    await page.locator('#auth-password').fill('isolated-test-only-password');
    await page.screenshot({ path: path.join(output, 'login-' + viewport.width + '.png') });
    await page.locator('#login button').click();
    await page.locator('#group').waitFor();
    assert.ok(await page.locator('.metrics').innerText().then(t => t.includes('3 200') && t.includes('31 часов')));
    const report = await context.request.get(base + '/api/report?from=2026-08-01&to=2026-08-31');
    const total = (await report.json()).totals;
    assert.deepEqual([total.revenue, total.payout, total.records, total.trips, total.days, total.hours, total.km], [3200,1100,4,2,1,31,null]);
    checks.push('UI login; money/hours without km; charges separate from 2 trips / 1 day');
    await page.locator('#statisticsView').selectOption('averages');
    await page.getByRole('columnheader', {name: /Средняя сумма записи/}).first().waitFor();
    for (const group of ['vehicle_brand','vehicle_company','driver_company','resource_type','pair','date','week','month','quarter','year']) {
      await page.locator('#group').selectOption(group);
      await page.waitForFunction(() => document.querySelector('#group'));
      assert.ok((await page.locator('#content tbody').first().innerText()).includes('800'));
    }
    const downloadPromise = page.waitForEvent('download');
    await page.locator('#export').click();
    const download = await downloadPromise;
    const stream = await download.createReadStream(); let csv = '';
    for await (const part of stream) csv += part.toString();
    assert.ok(csv.includes('800') && csv.includes('1500'));
    await page.locator('[data-row]').first().click();
    await page.locator('#dialog[open]').waitFor();
    assert.equal(await page.locator('#dialog tbody tr').count(), 4);
    await page.locator('#dialog .dialog-close').click();
    checks.push('average groups, CSV and four source records in detail');
    await go('/analytics/reconcile', '#content tbody');
    assert.ok((await page.locator('#content').innerText()).includes('Разница = ТТ − спутник'));
    assert.ok((await page.locator('#content tbody').innerText()).includes('—'));
    await go('/analytics/comparison', '[name=comparisonMetrics]');
    const deltaHeaders = [];
    for (const value of ['money','work','distance']) {
      await page.locator('[name=comparisonMetrics]').selectOption(value);
      const expected = {money: 'Выручка', work: 'Рейсы', distance: 'Пробег'}[value];
      await page.waitForFunction(text => document.querySelector('#content thead')?.textContent.includes(text), expected);
      deltaHeaders.push(...await page.locator('#content th').allTextContents());
    }
    assert.equal(deltaHeaders.filter(x => x.includes('Δ')).length, 6);
    assert.ok((await page.locator('#content').innerText()).includes('Полнота'));
    checks.push('two distinct reconciliations; all six delta columns; missing coverage/km explained');
    await go('/planning/calendar', '#statusAdd');
    await page.locator('#statusAdd').click();
    await page.locator('#statusForm [name=note]').fill('Synthetic acceptance draft');
    const before = dataGets;
    refreshStamp = '2026-08-01T00:10:00Z';
    await page.evaluate(async () => { await window.fleetRefresh.poll(); await window.fleetRefresh.updateView(); });
    assert.equal(dataGets, before);
    assert.equal(await page.locator('#statusForm [name=note]').inputValue(), 'Synthetic acceptance draft');
    const statusDate = viewport.width === 1440 ? '2026-08-10' : '2026-08-11';
    await page.locator('#statusForm [name=date]').fill(statusDate);
    await page.locator('#statusForm [name=end_date]').fill(statusDate);
    const entity = await page.locator('#statusForm [name=entity_id] option').evaluateAll(xs => xs.find(x => x.value)?.value);
    await page.locator('#statusForm [name=entity_id]').selectOption(entity);
    const reason = await page.locator('#statusForm [name=reason] option').evaluateAll(xs => xs.find(x => x.value)?.value);
    await page.locator('#statusForm').getByRole('combobox', {name:'Причина', exact:true}).fill(reason);
    await page.getByRole('option', {name:reason, exact:true}).click();
    await page.locator('#statusForm button.primary').click();
    await page.locator('#dialog').waitFor({ state: 'hidden' });
    await page.locator('[data-day="'+statusDate+'"] .status').first().waitFor();
    assert.equal((await (await context.request.get(base + '/api/report?from=2026-08-01&to=2026-08-31')).json()).totals.trips, 2);
    await page.locator('#statusAdd').click();
    await page.locator('#statusForm [name=kind]').selectOption('driver');
    await page.locator('#statusForm [name=date]').fill(statusDate);
    await page.locator('#statusForm [name=end_date]').fill(statusDate);
    const driverId = await page.locator('#statusForm [name=entity_id] option').evaluateAll(xs => xs.find(x => x.value)?.value);
    await page.locator('#statusForm [name=entity_id]').selectOption(driverId);
    await page.locator('#statusForm').getByRole('combobox', {name:'Причина', exact:true}).fill(reason);
    await page.getByRole('option', {name:reason, exact:true}).click();
    await page.locator('#statusForm button.primary').click();
    await page.locator('#dialog').waitFor({ state: 'hidden' });
    await page.locator('#calMode').selectOption('driver');
    await page.locator('[data-day="'+statusDate+'"] .status').first().waitFor();
    for (const entity of ['vehicle','driver']) {
      const downtime = await (await context.request.get(base+'/api/workspace/report?mode=downtime&entity='+entity+'&from='+statusDate+'&to='+statusDate)).json();
      assert.equal(downtime.rows.length, 1);
      assert.deepEqual([downtime.rows[0].trips,downtime.rows[0].work_days,downtime.rows[0].status_days], [0,0,1]);
    }
    const afterStatuses = (await (await context.request.get(base+'/api/report?from=2026-08-01&to=2026-08-31')).json()).totals;
    assert.deepEqual([afterStatuses.revenue,afterStatuses.payout,afterStatuses.trips,afterStatuses.hours,afterStatuses.km], [3200,1100,2,31,null]);
    checks.push('dirty dialog survives completed background refresh; independent statuses appear in calendar and downtime statistics without orders or changed money/hours');
    await go('/planning/planner', '#planAdd');
    const month = viewport.width === 1440 ? '2027-01' : '2027-02';
    const days = viewport.width === 1440 ? 31 : 28;
    async function newPlan(slot, end) {
      await page.locator('#planAdd').click();
      await page.locator('#planForm [name=date]').fill(month+'-01');
      await page.locator('#planForm [name=end_date]').fill(month+'-'+String(end).padStart(2,'0'));
      for (const name of ['vehicle_id','driver_id','route_id']) {
        const value = await page.locator('#planForm [name='+name+'] option').evaluateAll(xs => xs.find(x => x.value)?.value);
        await page.locator('#planForm [name='+name+']').selectOption(value);
      }
      await page.locator('#planForm [name=slot]').fill(slot);
      await page.locator('#planForm button.primary').click();
      await page.locator('#dialog').waitFor({ state: 'hidden' });
    }
    await newPlan('first', days);
    await page.locator('[name=planMonth]').fill(month);
    await page.locator('[name=planMonth]').dispatchEvent('change');
    await newPlan('second', 1);
    const planData = await (await context.request.get(base+'/api/data')).json();
    const monthPlans = planData.plans.filter(x => x.date.startsWith(month));
    assert.equal(monthPlans.length, days+1);
    assert.equal(monthPlans.reduce((sum,x) => sum+x.revenue,0), (days+1)*1000);
    await page.locator('[name=planView]').selectOption('calendar');
    assert.equal(await page.locator('.chip.plan').count(), days+1);
    await page.locator('[name=planRows]').selectOption('vehicle');
    assert.equal(await page.locator('.chip.plan').count(), days+1);
    checks.push('2027 monthly plan and second shift; both route/vehicle matrices preserve all assignments and sums');
    for (const [route, fields] of [
      ['/control/fuelcards',['vehicle_id','provider','card','start','end']],
      ['/control/expenses',['vehicle_id','date','category','amount']],
      ['/control/coverage',['source','start','end','complete']],
    ]) {
      await go(route, '#extraAdd'); await page.locator('#extraAdd').click();
      for (const field of fields) assert.equal(await page.locator('#extraForm [name="'+field+'"]').count(), 1);
      if (route.endsWith('coverage')) { await page.locator('#coveragePreview').click(); await page.waitForFunction(() => document.querySelector('#coveragePreviewStatus')?.textContent.includes('Исходных записей')); }
      await page.locator('#dialog .dialog-close').click();
    }
    await go('/control/evidence', '#content');
    assert.ok((await page.locator('#content').innerText()).toLowerCase().includes('смен'));
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
    checks.push('existing card / expense / coverage preview / evidence forms render; no document horizontal overflow');
    await page.screenshot({path: path.join(output, 'evidence-' + viewport.width + '.png')});
    const userRoles = {};
    for (const role of ['viewer','logist']) {
      await context.request.post(base + '/api/login', {data: {name:'acceptance-'+role,password:'isolated-test-only-password'}});
      await go('/planning/calendar', '#calMode');
      assert.equal(await page.locator('#statusAdd').count(), role === 'viewer' ? 0 : 1);
      assert.equal(await page.locator('[data-tab=users]').count(), 0);
      const session = await (await context.request.get(base + '/api/session')).json();
      const denied = await context.request.post(base + '/api/users', {headers:{'X-CSRF-Token':session.csrf}, data:{}});
      assert.equal(denied.status(), 403);
      userRoles[role] = {status_create_visible: role === 'logist', user_admin_forbidden: true};
    }
    assert.deepEqual(errors, []); assert.deepEqual(external, []);
    result.viewports.push({ ...viewport, checks, roles: userRoles, page_errors: errors.length, external_requests: external.length });
    await context.close();
  }
}
(async () => {
  try { await main(); result.status='passed'; }
  catch (error) { result.status='failed'; result.errors.push(error.stack); process.exitCode=1; }
  finally { await stop(); result.elapsed_seconds=(Date.now()-started)/1000; fs.writeFileSync(path.join(output,'browser.json'), JSON.stringify(result,null,2)+'\n'); console.log(JSON.stringify(result,null,2)); }
})();
