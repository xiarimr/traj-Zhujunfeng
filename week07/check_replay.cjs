// Optional browser QA: requires Playwright and Microsoft Edge.
const { chromium } = require('playwright');
const { pathToFileURL } = require('url');
const path = require('path');
(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 950 } });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(pathToFileURL(path.join(__dirname, 'index.html')).href);
    await page.locator('#timeline').fill('430');
    await page.screenshot({ path: path.join(__dirname, 'results/replay_preview.png'), fullPage: true });
    await page.locator('#timeline').fill('1000');
    if (!(await page.locator('#arrivals').innerText()).includes('100')) throw Error('End arrival count');
    await page.locator('#model').selectOption('straight');
    if ((await page.locator('#unsafe').innerText()) !== '4950') throw Error('Baseline metrics');
    await page.locator('#model').selectOption('predictive');
    await page.locator('#play').click();
    await page.waitForFunction(() => document.querySelector('#clock').textContent !== '0.0 s');
    await page.locator('#play').click();
    await page.locator('#targets').check();
    await page.locator('#trails').uncheck();
    await page.locator('#view').click();
    await page.setViewportSize({ width: 390, height: 844 });
    if (await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)) throw Error('Mobile overflow');
    if (errors.length) throw Error(errors.join('\n'));
    console.log('PASS: local replay, timeline, models, playback, toggles, mobile layout; no page errors.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error.message.slice(0, 1500)); process.exit(1); });
