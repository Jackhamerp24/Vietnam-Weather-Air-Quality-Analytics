/* Phase 12 curated dashboard screenshots. Playwright is verification tooling,
 * not an application dependency. Supply NODE_PATH if using a bundled runtime. */
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs/promises');
const path = require('node:path');

const BUNDLE_FILE_SHA256 = 'd2c017952150828f30a1a6617940983ece43c06c20aa4498a44d933046fe131d';
const BUNDLE_CANONICAL_SHA256 = 'b3b43813751628cc0d3439c209484a7c588cbdc9f355eb38cbe9233b1e0a167d';
const sha256 = bytes => crypto.createHash('sha256').update(bytes).digest('hex');

function captureUrl(value) {
  const parsed = new URL(value);
  assert(parsed.protocol === 'http:' && ['127.0.0.1', 'localhost'].includes(parsed.hostname)
    && parsed.pathname === '/' && !parsed.username && !parsed.password && !parsed.search && !parsed.hash,
  'Capture requires a plain HTTP loopback root URL');
  return parsed.href;
}

function verifyBundle(bytes) {
  assert.equal(sha256(bytes), BUNDLE_FILE_SHA256, 'Served/local dashboard byte mismatch');
  const bundle = JSON.parse(bytes);
  assert.equal(bundle.bundle_sha256, BUNDLE_CANONICAL_SHA256, 'Dashboard canonical identity mismatch');
  return bundle;
}

async function installNetworkGuard(context, url, blocked) {
  const origin = new URL(url).origin;
  await context.route('**/*', route => {
    const requested = new URL(route.request().url());
    if (requested.protocol === 'http:' && requested.origin === origin) return route.continue();
    blocked.push('external_request_blocked');
    return route.abort();
  });
  // The static dashboard has no websocket or service-worker requirement.
  await context.routeWebSocket('**/*', socket => {
    blocked.push('websocket_blocked');
    socket.close();
  });
}

async function main(args = process.argv.slice(2)) {
  const url = captureUrl(args[0] || 'http://127.0.0.1:8765/');
  const output = args[1];
  assert(output, 'Supply a NEW evidence output directory as second argument');

  const bundlePath = path.join(__dirname, '..', 'dashboard', 'data', 'dashboard.json');
  const bundleBytes = await fs.readFile(bundlePath);
  const bundle = verifyBundle(bundleBytes);
  const styleBytes = await fs.readFile(path.join(__dirname, '..', 'dashboard', 'styles.css'));
  await fs.mkdir(output, { mode: 0o700 });
  const screenshots = [];
  const { chromium } = require('playwright');
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 },
      locale: 'en-GB', timezoneId: 'America/New_York', serviceWorkers: 'block' });
    const errors = [], external = [];
    await installNetworkGuard(context, url, external);
    const page = await context.newPage();
    page.on('pageerror', () => errors.push('browser_script_error'));

    async function capture(file, viewport, label) {
      await page.setViewportSize(viewport);
      await page.evaluate(() => window.scrollTo({ top: 0, left: 0, behavior: 'instant' }));
      await page.mouse.move(0, 0);
      const screenshotBytes = await page.screenshot({ fullPage: true, animations: 'disabled' });
      await fs.writeFile(path.join(output, file), screenshotBytes, { flag: 'wx', mode: 0o600 });
      screenshots.push({
        file,
        label,
        viewport: { width: viewport.width, height: viewport.height },
        capture_mode: 'full_page',
        image_pixels: { width: screenshotBytes.readUInt32BE(16), height: screenshotBytes.readUInt32BE(20) },
        bytes: screenshotBytes.length,
        sha256: sha256(screenshotBytes),
      });
      console.log(`CAPTURED ${file}`);
    }

    const [response, stylesheet] = await Promise.all([
      page.waitForResponse(response => response.url() === new URL('data/dashboard.json', url).href),
      page.waitForResponse(response => response.url() === new URL('styles.css', url).href),
      page.goto(url),
    ]);
    assert.equal(response.status(), 200, 'Dashboard response must succeed');
    verifyBundle(await response.body());
    assert.equal(stylesheet.status(), 200, 'Stylesheet response must succeed');
    assert.equal(sha256(await stylesheet.body()), sha256(styleBytes), 'Served stylesheet differs from local CSS');
    await page.locator('#dashboard-app').waitFor({ state: 'visible' });
    assert.equal(await page.locator('#app-error').isVisible(), false);

    await capture('01-overview-desktop.png', { width: 1440, height: 1000 },
      'Overview with default full frozen window');

    await page.locator('#global-sensor-filter').selectOption('openaq_11357424');
    await page.locator('#global-start-filter').fill('2026-07-01');
    await page.locator('#global-start-filter').dispatchEvent('change');
    await page.locator('#global-end-filter').fill('2026-07-07');
    await page.locator('#global-end-filter').dispatchEvent('change');
    assert.equal(await page.locator('#global-start-filter').inputValue(), '2026-07-01');
    await page.locator('[data-view-link="air-quality"]').click();
    await page.locator('#view-air-quality').waitFor({ state: 'visible' });
    await capture('02-air-quality-filtered-desktop.png', { width: 1440, height: 1000 },
      'Air quality filtered to CMT8, Vietnam-local 2026-07-01 to 2026-07-07');

    await page.locator('[data-view-link="overview"]').click();
    await page.locator('#reset-descriptive-filters').click();
    assert.equal(await page.locator('#global-start-filter').inputValue(), '2026-06-08');

    await page.locator('[data-view-link="model-diagnostics"]').click();
    await page.locator('#view-model-diagnostics').waitFor({ state: 'visible' });
    assert((await page.locator('#model-limited-notice').innerText()).includes('Limited diagnostic'));
    await capture('03-model-diagnostics-limited-desktop.png', { width: 1440, height: 1000 },
      'Model diagnostics showing the limited-diagnostic boundary');

    await page.locator('[data-view-link="methods-provenance"]').click();
    await page.locator('#view-methods-provenance').waitFor({ state: 'visible' });
    await page.locator('#provenance-toggle-0').click();
    assert.equal((await page.locator('#bundle-sha256').innerText()).trim(), BUNDLE_CANONICAL_SHA256);
    await capture('04-methods-provenance-desktop.png', { width: 1440, height: 1000 },
      'Methods and provenance with verified bundle identity');

    await page.locator('[data-view-link="overview"]').click();
    await page.locator('#view-overview').waitFor({ state: 'visible' });
    await capture('05-overview-mobile.png', { width: 375, height: 812 },
      'Overview at 375x812 narrow layout');

    assert.deepEqual(errors, [], 'Browser script errors');
    assert.deepEqual(external, [], 'External requests');

    const manifest = {
      screenshot_version: 'phase12_screenshots_v2',
      command: `node scripts/capture_dashboard_screenshots.cjs ${url} <evidence-dir>`,
      browser_version: browser.version(),
      captured_at_utc: new Date().toISOString(),
      note: 'Static screenshots of frozen artifacts; capture time is evidence metadata, not dashboard data.',
      dashboard: {
        source: 'dashboard/data/dashboard.json',
        schema_version: bundle.schema_version,
        canonical_digest: bundle.bundle_sha256,
        file_sha256: sha256(bundleBytes),
        served_file_sha256: BUNDLE_FILE_SHA256,
        served_bytes_verified: true,
        stylesheet_sha256: sha256(styleBytes),
        served_stylesheet_verified: true,
      },
      screenshots,
      errors,
      external,
    };
    await fs.writeFile(path.join(output, 'screenshots_manifest.json'),
      JSON.stringify(manifest, null, 2) + '\n', { flag: 'wx', mode: 0o600 });
    console.log(`OK ${screenshots.length} screenshots, no errors or external requests`);
  } finally { await browser.close(); }
}
module.exports = { captureUrl, verifyBundle, installNetworkGuard, main };
if (require.main === module) main().catch(() => {
  console.error('screenshot_capture_failed');
  process.exitCode = 1;
});
