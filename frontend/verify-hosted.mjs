import { chromium, expect } from '@playwright/test';
import { readFile } from 'node:fs/promises';

const url = 'https://agentguard-production-2392.up.railway.app';
const env = await readFile(new URL('../.env.production', import.meta.url), 'utf8');
const token = env.match(/^AGENTGUARD_API_TOKEN=(.+)$/m)?.[1].trim();
if (!token) throw new Error('Missing local deployment token');
const browser = await chromium.launch();
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(url);
  await page.getByRole('button', { name: 'Workspace access', exact: true }).click();
  await page.getByLabel('Workspace API token').fill(token);
  await page.getByRole('button', { name: 'Apply', exact: true }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page.locator('tbody').first()).toContainText('customer-support:v1');
  await expect(page.getByRole('alert')).toHaveCount(0);
  await page.screenshot({ path: '../.qa/hosted-desktop.png', fullPage: true });
  await page.getByRole('button', { name: 'Traces', exact: true }).click();
  await page.getByRole('button', { name: /Inspect run/ }).first().click();
  await expect(page.getByRole('heading', { name: 'Execution timeline' })).toBeVisible();
  await page.getByRole('button', { name: 'Close dialog' }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: 'Toggle navigation' }).click();
  await page.getByRole('button', { name: 'Overview', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Agent performance' })).toBeVisible();
  if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) throw new Error('Mobile overflow');
  if (errors.length) throw new Error('Browser JavaScript errors occurred');
  console.log('Hosted desktop/mobile login, metrics, and trace inspection passed.');
} finally {
  await browser.close();
}
