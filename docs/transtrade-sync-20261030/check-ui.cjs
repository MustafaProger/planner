const fs = require('node:fs');
const assert = require('node:assert/strict');
const {chromium, webkit} = require('/Users/mustafa/Desktop/Artel-CRM/node_modules/playwright');

(async () => {
  const login = fs.readFileSync('data/local-login.txt', 'utf8');
  const name = login.match(/Пользователь: (.+)/)[1];
  const password = login.match(/Пароль: (.+)/)[1];
  const results = [];
  for (const [engine, type] of Object.entries({chromium, webkit})) {
    const browser = await type.launch({headless: true});
    const context = await browser.newContext();
    assert((await context.request.post('http://127.0.0.1:8765/api/login', {data: {name, password}})).ok());
    const page = await context.newPage();
    await page.emulateMedia({reducedMotion: 'reduce'});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    for (const width of [1440, 390]) {
      await page.setViewportSize({width, height: 1000});
      await page.goto('http://127.0.0.1:8765/data/orders');
      await page.locator('summary').filter({hasText: 'Обновление заявок и сверка истории'}).click();
      await page.locator('#transtrade-reconcile').waitFor();
      if (engine === 'chromium' && width === 1440 && !process.env.SKIP_RECONCILE) {
        const response = page.waitForResponse(r => r.url().endsWith('/api/transtrade/reconcile'), {timeout: 180000});
        await page.locator('#transtrade-reconcile').click();
        const result = await (await response).json();
        assert.equal(result.status, 'success');
        assert.equal(result.created, 0);
        assert.equal(result.updated, 0);
        assert.equal(result.unchanged, 2971);
        fs.writeFileSync('docs/transtrade-sync-20261030/repeat.json', JSON.stringify(result, null, 2));
        await page.locator('#transtrade-reconcile:not([disabled])').waitFor();
      }
      const check = await page.evaluate(() => ({
        overflow: document.documentElement.scrollWidth > innerWidth + 1,
        history: document.querySelector('.transtrade-history').innerText,
        buttonEnabled: !document.querySelector('#transtrade-reconcile').disabled,
        automaticScope: document.querySelector('.refresh-details-body')?.innerText || ''
      }));
      assert(!check.overflow);
      assert(check.buttonEnabled);
      assert(check.history.includes('2 971') || check.history.includes('2 971') || check.history.includes('2971'));
      assert.equal(errors.length, 0);
      await page.locator('.transtrade-history').screenshot({path: `docs/transtrade-sync-20261030/history-${engine}-${width}.png`});
      results.push({engine, width, ...check, errors: [...errors]});
    }
    await browser.close();
  }
  fs.writeFileSync('docs/transtrade-sync-20261030/ui-results.json', JSON.stringify(results, null, 2));
  console.log(JSON.stringify({checks: results.length, errors: results.flatMap(x => x.errors), repeat: '2971 unchanged, no creates or updates'}));
})().catch(error => { console.error(error.message); process.exit(1); });
