// End-to-end cover for the public directory.
//
// The unit tests assert the mockup's structure; nothing asserted that it
// renders, that search narrows anything, or that the export produces a file.
// This drives a real browser against the committed feed.
//
// Assertions are relative — "search narrows the set", not "search returns 74" —
// so republishing the feed does not turn this red.

import { test, expect } from '@playwright/test';

const widget = '/mockup/index.html';

async function count(page) {
  const text = await page.locator('#count').innerText();
  const digits = text.replace(/,/g, '').match(/\d+/g) || [];
  return Number(digits[0]);
}

test('loads the feed and fills the metric tiles', async ({ page }) => {
  await page.goto(widget);
  await expect(page.locator('#m-outlets')).not.toHaveText('', { timeout: 15000 });
  for (const tile of ['#m-outlets', '#m-coverage', '#m-states', '#m-sources']) {
    expect(Number((await page.locator(tile).innerText()).replace(/,/g, ''))).toBeGreaterThan(0);
  }
});

test('opens on the data explorer with rows', async ({ page }) => {
  await page.goto(widget);
  await expect(page.locator('[role=tab][aria-selected=true]')).toHaveText(/Data explorer/);
  await expect(page.locator('#panel-explorer')).toBeVisible();
  await expect.poll(() => page.locator('#exp-body tr').count()).toBeGreaterThan(0);
  expect(await page.locator('#exp-head th').count()).toBeGreaterThan(0);
});

test('search narrows the set and reset restores it', async ({ page }) => {
  await page.goto(widget);
  await expect.poll(() => count(page)).toBeGreaterThan(0);
  const before = await count(page);

  // The mockup once threw TypeError on every keystroke because its search index
  // was built before the feed loaded. Any console error fails this test.
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));

  await page.fill('#q', 'tribune');
  await expect.poll(() => count(page)).toBeLessThan(before);
  expect(errors).toEqual([]);

  await page.click('#reset');
  await expect.poll(() => count(page)).toBe(before);
});

test('a facet filters, shows a chip, and the chip removes it', async ({ page }) => {
  await page.goto(widget);
  await expect.poll(() => count(page)).toBeGreaterThan(0);
  const before = await count(page);

  await page.click('#ms-state summary');
  await page.locator('#ms-state .pop input[type=checkbox]').first().check();
  await expect.poll(() => count(page)).toBeLessThan(before);
  await expect(page.locator('.chip')).toHaveCount(1);

  await page.locator('.chip button').first().click();
  await expect.poll(() => count(page)).toBe(before);
});

test('browse outlets renders cards and switches to a table', async ({ page }) => {
  await page.goto(widget);
  await page.click('#tab-browse');
  await expect.poll(() => page.locator('.card').count()).toBeGreaterThan(0);

  await page.click('#view button[data-view="table"]');
  await expect.poll(() => page.locator('#browse-out tbody tr').count()).toBeGreaterThan(0);
  expect(await page.locator('#browse-out th').count()).toBeGreaterThan(0);
});

test('coverage records tab lazy-loads its payload', async ({ page }) => {
  await page.goto(widget);
  await page.click('#tab-coverage');
  await expect.poll(() => page.locator('#cov-body tr').count(), { timeout: 30000 })
    .toBeGreaterThan(0);
  expect(await page.locator('#cov-head th').count()).toBeGreaterThan(0);
});

test('export produces a CSV of the filtered set', async ({ page }) => {
  await page.goto(widget);
  await expect.poll(() => count(page)).toBeGreaterThan(0);
  await page.click('#export');

  // The mockup shows the CSV rather than downloading it, because the preview
  // sandbox blocks downloads; the WordPress build saves a file.
  const csv = await page.locator('#csv').inputValue();
  const lines = csv.trim().split('\n');
  expect(lines.length).toBeGreaterThan(1);
  expect(lines[0]).toContain('outlet_name');
});
