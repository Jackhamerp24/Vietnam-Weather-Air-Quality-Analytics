/* Credential-free capture-contract tests; no Playwright/browser required. */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const { captureUrl, verifyBundle, installNetworkGuard, main } =
  require('./capture_dashboard_screenshots.cjs');

test('capture accepts only plain HTTP loopback root URLs', () => {
  assert.equal(captureUrl('http://127.0.0.1:8765/'), 'http://127.0.0.1:8765/');
  for (const url of ['https://example.com/', 'https://localhost/', 'http://localhost/path',
    'http://user:synthetic@localhost/', 'http://localhost/?synthetic=1', 'http://localhost/#view']) {
    assert.throws(() => captureUrl(url));
  }
});
test('served dashboard bytes must equal the pinned file, not just carry a digest', async () => {
  const bytes = await fs.readFile(path.join(__dirname, '../dashboard/data/dashboard.json'));
  assert.equal(verifyBundle(bytes).schema_version, 'phase10_dashboard_v1');
  const modified = JSON.parse(bytes);
  modified.meta.title = 'synthetic replacement';
  assert.throws(() => verifyBundle(Buffer.from(JSON.stringify(modified))));
});

test('external HTTP and websocket routes are blocked before transmission', async () => {
  let httpHandler, wsHandler;
  const blocked = [];
  await installNetworkGuard({
    route: async (_, handler) => { httpHandler = handler; },
    routeWebSocket: async (_, handler) => { wsHandler = handler; },
  }, 'http://127.0.0.1:8765/', blocked);
  let continued = 0, aborted = 0, closed = 0;
  for (const url of ['http://127.0.0.1:8765/data/dashboard.json', 'https://example.invalid/']) {
    await httpHandler({
      request: () => ({ url: () => url }),
      continue: () => { continued++; },
      abort: () => { aborted++; },
    });
  }
  wsHandler({ close: () => { closed++; } });
  assert.equal(continued, 1);
  assert.equal(aborted, 1);
  assert.equal(closed, 1);
  assert.deepEqual(blocked, ['external_request_blocked', 'websocket_blocked']);
});

test('existing evidence directory is rejected before browser startup', async () => {
  const output = await fs.mkdtemp(path.join(os.tmpdir(), 'phase12-capture-test-'));
  try {
    await fs.writeFile(path.join(output, 'sentinel'), 'unchanged');
    await assert.rejects(main(['http://127.0.0.1:8765/', output]), { code: 'EEXIST' });
    assert.equal(await fs.readFile(path.join(output, 'sentinel'), 'utf8'), 'unchanged');
  } finally {
    // Remove only the synthetic sentinel and empty directory created by this test.
    await fs.unlink(path.join(output, 'sentinel'));
    await fs.rmdir(output);
  }
});
