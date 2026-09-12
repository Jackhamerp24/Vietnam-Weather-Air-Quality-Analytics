/* Browser evidence for the offline dashboard. Playwright is verification tooling,
 * not an application dependency. Supply NODE_PATH if using a bundled runtime. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');

async function main() {
  const args = process.argv.slice(2);
  const url = args[0] || 'http://127.0.0.1:8765/';
  assert(['127.0.0.1', 'localhost'].includes(new URL(url).hostname), 'Tests only target loopback');
  const output = args[1];
  assert(output, 'Supply a NEW evidence output directory as second argument');
  await fs.mkdir(output); // Exclusive directory: do not overwrite prior evidence.
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 },
    locale: 'en-GB', timezoneId: 'America/New_York', acceptDownloads: true });
  const page = await context.newPage();
  const errors = [], external = [], checks = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('request', r => { if (/^https?:/.test(r.url()) && new URL(r.url()).origin !== new URL(url).origin) external.push(r.url()); });
  const pass = name => { checks.push(name); console.log(`PASS ${name}`); };
  async function screenshot(name) {
    await page.evaluate(()=>window.scrollTo({top:0,left:0,behavior:'instant'}));
    await page.mouse.move(0,0);
    await page.screenshot({path:path.join(output,name),fullPage:true,animations:'disabled'});
  }
  async function contrastCheck(theme) {
    const failures = await page.evaluate(() => {
      const rgb = value => (value.match(/[\d.]+/g) || []).map(Number);
      const luminance = value => rgb(value).slice(0,3).map(c => {
        c /= 255; return c <= .04045 ? c / 12.92 : ((c + .055) / 1.055) ** 2.4;
      }).reduce((v,c,i)=>v+c*[.2126,.7152,.0722][i],0);
      return [...document.querySelectorAll('.button:not(:disabled), .card-subtitle, .view-intro, .notice, .metric-foot, .badge')]
        .filter(el=>el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden')
        .flatMap(el=> {
          let bg = el; while(bg && (rgb(getComputedStyle(bg).backgroundColor)[3] ?? 1) < .99) bg = bg.parentElement;
          if(!bg) return [];
          const a=luminance(getComputedStyle(el).color), b=luminance(getComputedStyle(bg).backgroundColor);
          const ratio=(Math.max(a,b)+.05)/(Math.min(a,b)+.05);
          return ratio>=4.5 ? [] : [{element:el.className, ratio, text:el.textContent.slice(0,55)}];
        });
    });
    assert.deepEqual(failures,[], `Rendered ${theme} text contrast under 4.5:1`);
  }
  try {
    await page.goto(url);
    await page.locator('#dashboard-app').waitFor({state:'visible'});
    assert(await page.locator('#view-title').innerText());
    assert.equal(await page.locator('#app-error').isVisible(), false);
    const from = await page.locator('#global-start-filter').inputValue();
    const to = await page.locator('#global-end-filter').inputValue();
    assert.equal(from, '2026-06-08'); assert.equal(to, '2026-09-06');
    pass('Overview loads with Vietnam dates in a non-Vietnam browser timezone');
    await screenshot('overview-desktop.png');
    await contrastCheck('light');

    await page.locator('#daily-trend-svg').focus();
    await page.keyboard.press('ArrowRight');
    assert(await page.locator('#daily-trend-tooltip').innerText());
    await page.locator('#daily-trend-show-table').click();
    assert(await page.locator('#overview-trend-card table').isVisible());
    const downloadPromise = page.waitForEvent('download');
    await page.locator('#daily-trend-export').click();
    const download = await downloadPromise;
    const csv = await fs.readFile(await download.path(), 'utf8');
    assert(csv.includes('Station') && csv.includes('CMT8') && csv.includes('OceanPark'));
    await page.locator('#daily-trend-show-chart').click();
    pass('Chart keyboard inspection, table alternative and CSV download');

    await page.locator('#global-sensor-filter').selectOption('openaq_11357424');
    await page.locator('#global-start-filter').fill('2026-07-01');
    await page.locator('#global-start-filter').dispatchEvent('change');
    await page.locator('#global-end-filter').fill('2026-07-07');
    await page.locator('#global-end-filter').dispatchEvent('change');
    assert((await page.locator('#overview-trend-card').innerText()).includes('Jul'));
    await page.locator('#global-start-filter').fill('2026-08-01');
    await page.locator('#global-start-filter').dispatchEvent('change');
    await page.locator('#global-date-error').waitFor({state:'visible'});
    await page.locator('#reset-descriptive-filters').click();
    assert.equal(await page.locator('#global-start-filter').inputValue(), from);
    pass('Station/date filters, invalid range feedback and reset');

    const views = ['air-quality','weather-context','model-diagnostics','methods-provenance'];
    for (const view of views) {
      await page.locator(`[data-view-link="${view}"]`).click();
      await page.locator(`#view-${view}`).waitFor({state:'visible'});
      assert.equal(await page.locator('[data-view]:visible').count(),1);
      assert.equal(await page.locator(`#view-${view} #view-title`).count(),1);
      assert.equal(await page.locator(`[data-view-link="${view}"]`).getAttribute('aria-current'),'page');
    }
    pass('Five views and active navigation semantics');
    await page.locator('.skip-link').focus();
    await page.keyboard.press('Enter');
    assert.equal(new URL(page.url()).hash, '#methods-provenance');
    assert.equal(await page.evaluate(()=>document.activeElement.id), 'main-content');
    pass('Skip link preserves the current research view');
    await page.locator('#provenance-toggle-0').click();
    assert(await page.locator('#provenance-phase-5').getAttribute('open') !== null);
    assert((await page.locator('#bundle-sha256').innerText()).length === 64);
    pass('Provenance details and source digest');

    await page.locator('[data-view-link="weather-context"]').click();
    await page.locator('#weather-variable-filter').selectOption('wind_speed_10m');
    assert((await page.locator('#weather-hourly-card').innerText()).includes('m/s'));
    await page.locator('#weather-variable-filter').selectOption('shortwave_radiation');
    assert((await page.locator('#weather-hourly-card').innerText()).match(/preceding|end/i));
    await page.locator('#weather-sensor-filter').selectOption('openaq_11357424');
    assert((await page.locator('#cams-card').innerText()).includes('CAMS'));
    const camsSelect = page.locator('#cams-location-filter');
    if (await camsSelect.count()) {
      await camsSelect.selectOption('hanoi');
      assert((await page.locator('#cams-card').innerText()).includes('Hanoi'));
    }
    pass('Weather variables, units and temporal-support labels');
    await screenshot('weather-desktop.png');

    await page.locator('[data-view-link="model-diagnostics"]').click();
    assert((await page.locator('#model-limited-notice').innerText()).includes('Limited diagnostic'));
    await page.locator('#model-feature-filter').selectOption('history_only');
    assert((await page.locator('#model-metrics-card').innerText()).match(/unavailable|insufficient/i));
    await page.locator('#model-feature-filter').selectOption('calendar_only');
    await page.locator('#model-split-filter').selectOption('test');
    assert((await page.locator('#model-comparisons-card').innerText()).match(/mismatch|unequal/i));
    pass('Model empty-feature state and visible test fit-history warnings');
    await screenshot('models-desktop.png');

    await page.locator('[data-view-link="overview"]').click();
    await page.locator('#theme-toggle').click();
    assert.equal(await page.locator('html').getAttribute('data-theme'),'dark');
    await screenshot('overview-dark.png');
    await contrastCheck('dark');
    await page.reload(); await page.locator('#dashboard-app').waitFor({state:'visible'});
    assert.equal(await page.locator('html').getAttribute('data-theme'),'dark');
    await page.locator('#theme-toggle').click();
    pass('Light/dark text contrast and persisted theme preference');

    for (const [width,height] of [[375,812],[768,1024],[1024,768],[812,375],[1440,1000]]) {
      await page.setViewportSize({width,height});
      for (const view of ['overview',...views]) {
        await page.locator(`[data-view-link="${view}"]`).click();
        const dimensions = await page.evaluate(() => ({width:innerWidth, scroll:document.documentElement.scrollWidth}));
        assert(dimensions.scroll <= dimensions.width + 1, `${view} horizontal page overflow at ${width}: ${dimensions.scroll}`);
      }
    }
    await page.setViewportSize({width:375,height:812});
    await page.locator('[data-view-link="overview"]').click();
    await screenshot('overview-mobile.png');
    await page.emulateMedia({reducedMotion:'reduce'});
    assert(await page.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches));
    const duration = await page.locator('.nav-item').first().evaluate(e=>getComputedStyle(e).transitionDuration);
    assert(parseFloat(duration) < .01, duration);
    pass('All views reflow at 375/768/1024/1440 and landscape; reduced motion');

    const denied = ['.env','.git/config','data/','README.md','%2e%2e/.env'];
    for (const suffix of denied) assert.equal((await context.request.get(new URL(suffix,url).href)).status(),404);
    assert.equal((await context.request.post(url,{data:'forbidden'})).status(),405);
    pass('Live server rejects unlisted files and mutation');

    const errorPage = await context.newPage();
    await errorPage.route('**/data/dashboard.json',route=>route.abort());
    await errorPage.goto(url); await errorPage.locator('#app-error').waitFor({state:'visible'});
    assert.equal(await errorPage.locator('#dashboard-app').isVisible(),false);
    await errorPage.unroute('**/data/dashboard.json');
    await errorPage.locator('#retry-load').click();
    await errorPage.locator('#dashboard-app').waitFor({state:'visible'});
    await errorPage.close();
    pass('Visible data failure state and successful retry');

    assert.deepEqual(errors,[], 'Browser script errors'); assert.deepEqual(external,[], 'External requests');
    pass('No browser script errors or external network requests');
    await fs.writeFile(path.join(output,'browser_checks.json'),JSON.stringify({checks,errors,external},null,2)+'\n');
  } finally { await browser.close(); }
}
main().catch(e=>{console.error(e.stack);process.exitCode=1;});
