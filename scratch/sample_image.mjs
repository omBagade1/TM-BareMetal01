import { chromium } from 'playwright-core';
import fs from 'node:fs';

const browser = await chromium.launch({ headless: true, channel: 'chrome' });
const page = await browser.newPage();
const imgData = fs.readFileSync('C:/Users/Akhilesh/Pictures/Screenshots/Screenshot 2026-10-12 194738.png');
const base64 = imgData.toString('base64');
await page.setContent(`<html><body><img id="img" src="data:image/png;base64,${base64}" /></body></html>`);

const samples = await page.evaluate(async () => {
  const img = document.getElementById('img');
  await new Promise(r => img.onload = r);
  const canvas = document.createElement('canvas');
  canvas.width = img.naturalWidth;
  canvas.height = img.naturalHeight;
  const ctx = canvas.getContext('2d');
  ctx.drawImage(img, 0, 0);

  function get(x, y) {
    const p = ctx.getImageData(x, y, 1, 1).data;
    return `rgb(${p[0]},${p[1]},${p[2]})`;
  }
  return {
    w: img.naturalWidth,
    h: img.naturalHeight,
    headerBg: get(400, 20),
    betweenPanels: get(1135, 120),
    panelBg: get(250, 60),
    setupBg: get(1200, 250),
    terminalBg: get(400, 400),
    terminalToolbarBg: get(400, 150),
    selectBorder: get(850, 20),
    pageTopRight: get(1300, 20),
  };
});
console.log('SAMPLES:', samples);
await browser.close();
