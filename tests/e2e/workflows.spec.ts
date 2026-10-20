import { expect, test } from '../../web/node_modules/@playwright/test';

test.beforeEach(async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('Plugin URL').fill('https://localhost:8443');
  await page.getByLabel('Access token').fill('demo');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await expect(page.getByRole('heading', { name: 'Search', exact: true })).toBeVisible();
});

test('search 10k files, download, and pause a transfer', async ({ page }) => {
  await page.getByLabel('Search term', { exact: true }).fill('Ambient works');
  await page.getByRole('button', { name: 'Search network' }).click();
  await expect(page.getByText('10,000 files')).toBeVisible();
  await page.screenshot({ path: '/tmp/nicotine-webgui-search.png', fullPage: true });
  expect(await page.locator('tbody tr').count()).toBeLessThan(100);
  await page.getByRole('checkbox', { name: /Select Music/ }).first().check();
  await page.getByRole('button', { name: /Download selected/ }).click();
  await page.getByRole('navigation').getByRole('link', { name: 'Downloads' }).click();
  await expect(page.getByRole('heading', { name: 'Downloads', exact: true })).toBeVisible();
  await expect(page.locator('tbody')).toContainText('Track 0001.flac');
  await page.getByRole('checkbox', { name: /Select Music/ }).first().check();
  await page.getByRole('button', { name: 'pause', exact: true }).click();
  await expect(page.locator('tbody')).toContainText('Paused');
});

test('room chat sends and receives text safely', async ({ page }) => {
  await page.getByRole('navigation').getByRole('link', { name: 'Rooms' }).click();
  await page.getByRole('link', { name: '# music' }).click();
  await page.getByLabel('Message', { exact: true }).fill('<script>alert(1)</script>');
  await page.getByRole('button', { name: 'Send', exact: false }).click();
  await expect(page.getByRole('log')).toContainText('Thanks for sharing! <script>alert(1)</script>');
  await expect(page.getByLabel('Message', { exact: true })).toHaveValue('');
});

test('session reload, expiry, rejected origin and logout', async ({ page, context }) => {
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Search', exact: true })).toBeVisible();
  const saved = await page.evaluate(() => sessionStorage.getItem('nicotine-session')!);
  expect(saved).not.toContain('"demo"');
  await page.evaluate(() => {
    const data = JSON.parse(sessionStorage.getItem('nicotine-session')!);
    data.session_token = 'invalid-session';
    sessionStorage.setItem('nicotine-session', JSON.stringify(data));
  });
  await page.reload();
  await expect(page.getByLabel('Plugin URL')).toHaveValue('https://localhost:8443');
  await page.evaluate(value => sessionStorage.setItem('nicotine-session', value), saved);
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Search', exact: true })).toBeVisible();
  const rejected = await context.newPage();
  await rejected.goto('http://localhost:8180');
  await rejected.getByLabel('Plugin URL').fill('https://localhost:8443');
  await rejected.getByLabel('Access token').fill('demo');
  await rejected.getByRole('button', { name: 'Open workspace' }).click();
  await expect(rejected.getByRole('alert')).toContainText('Cannot reach the plugin');
  await rejected.close();
  await page.getByRole('button', { name: 'Log out' }).click();
  await expect(page.getByLabel('Access token')).toBeVisible();
  await expect(page.getByLabel('Access token')).toHaveValue('');
  expect(await page.evaluate(() => sessionStorage.getItem('nicotine-session'))).toBeNull();
  const result = await context.request.get('https://localhost:8443/api/v1/session', { headers: { Origin: 'http://127.0.0.1:8180', Authorization: 'Bearer ' + JSON.parse(saved).session_token } });
  expect(result.status()).toBe(401);
});

test('shows reconnect state and recovers when the event stream returns', async ({ page }) => {
  let interrupted = true;
  await page.route('**/api/v1/events?*', route => interrupted ? route.abort() : route.continue());
  await page.reload();
  await expect(page.getByText('Bridge connection interrupted.', { exact: false })).toBeVisible();
  interrupted = false;
  await expect(page.getByText('Live bridge', { exact: false })).toBeVisible({ timeout: 10000 });
});

test('browse folders and manage a buddy', async ({ page }) => {
  await page.getByRole('navigation').getByRole('link', { name: 'Browse' }).click();
  await page.getByLabel('Browse username').fill('alice');
  await page.getByRole('button', { name: 'Browse user', exact: true }).click();
  await expect(page.getByRole('tree', { name: 'Shared folders' })).toBeVisible();
  await page.getByRole('treeitem', { name: 'Music', exact: false }).click();
  await expect(page.locator('tbody')).toContainText('Example.flac');
  await page.getByRole('checkbox', { name: /Select Music/ }).check();
  await page.getByRole('button', { name: /Download selected/ }).click();
  await page.getByRole('navigation').getByRole('link', { name: 'Buddies' }).click();
  await page.getByLabel('Buddy username').fill('test-buddy');
  await page.getByRole('button', { name: 'Add buddy', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'test-buddy', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Remove', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'test-buddy', exact: true })).not.toBeVisible();
});
