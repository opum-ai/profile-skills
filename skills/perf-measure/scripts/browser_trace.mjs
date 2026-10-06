#!/usr/bin/env node
// browser_trace.mjs: capture Chromium performance traces + lab vitals for a page, N runs.
//
//   node browser_trace.mjs <url> [--out dir] [--runs 3] [--cpu 4] [--network none|fast4g|slow4g]
//        [--interact actions.mjs] [--viewport 1350x940] [--mobile] [--channel chrome] [--headed]
//        [--wait-ms 1500] [--no-trace]
//
// Needs Playwright (`npm i -D playwright`, or any project that has it; resolved from cwd).
// If Playwright's bundled Chromium is missing it falls back to installed Google Chrome
// (--channel chrome). For each run it writes <out>/run-<i>.trace.json (Chrome trace JSON with
// the V8 CPU profile, readable by `perfkit hotspots`) and prints / writes <out>/metrics.json:
// TTFB, FCP, LCP, CLS, TBT (long tasks from FCP until interactions start), blocking time during
// interactions, long-task count, max interaction latency
// (INP proxy, from Event Timing entries during --interact), JS heap, DOM nodes, transfer bytes.
// Median across runs is reported; use it, not run 1.
//
// --interact module: `export default async function (page) { await page.click('#btn'); ... }`
// Interactions run after load; their Event Timing durations give the INP proxy.
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';

const args = process.argv.slice(2);
const opt = (name, def) => { const i = args.indexOf(`--${name}`); return i >= 0 ? args[i + 1] : def; };
const flag = (name) => args.includes(`--${name}`);
const url = args.find((a, i) => !a.startsWith('--') && !(i > 0 && args[i - 1].startsWith('--') && !['--headed', '--mobile', '--no-trace'].includes(args[i - 1])));
if (!url) { console.error('usage: node browser_trace.mjs <url> [--out dir] [--runs 3] [--cpu 4] [--network fast4g] [--interact file.mjs]'); process.exit(2); }
const out = opt('out', 'perf/browser');
const runs = +opt('runs', '3');
const cpu = +opt('cpu', '4');
const network = opt('network', 'none');
const waitMs = +opt('wait-ms', '1500');
const [vw, vh] = opt('viewport', flag('mobile') ? '412x823' : '1350x940').split('x').map(Number);
fs.mkdirSync(out, { recursive: true });

async function loadPlaywright() {
  const req = createRequire(path.join(process.cwd(), 'noop.js'));
  for (const name of ['playwright', 'playwright-core', '@playwright/test']) {
    try { const m = await import(pathToFileURL(req.resolve(name)).href); return m.chromium ? m : m.default; } catch {}
  }
  console.error('Playwright not found from ' + process.cwd() + '. Install it where you run this: npm i -D playwright');
  process.exit(3);
}

const NETWORK = {
  none: null,
  fast4g: { offline: false, latency: 150, downloadThroughput: (9e6 / 8) * 0.9, uploadThroughput: (1.5e6 / 8) * 0.9 },
  slow4g: { offline: false, latency: 562.5, downloadThroughput: (1.6e6 / 8) * 0.9, uploadThroughput: (750e3 / 8) * 0.9 },
};

// Injected before any page script: buffer the entries we need.
const OBSERVE = () => {
  const s = (window.__perf = { lcp: 0, cls: 0, longtasks: [], events: [], fcp: 0 });
  const po = (type, fn, extra = {}) => { try { new PerformanceObserver((l) => l.getEntries().forEach(fn)).observe({ type, buffered: true, ...extra }); } catch {} };
  po('largest-contentful-paint', (e) => { s.lcp = e.renderTime || e.loadTime || e.startTime; });
  po('layout-shift', (e) => { if (!e.hadRecentInput) s.cls += e.value; });
  po('longtask', (e) => s.longtasks.push({ start: e.startTime, dur: e.duration }));
  po('paint', (e) => { if (e.name === 'first-contentful-paint') s.fcp = e.startTime; });
  po('event', (e) => { if (e.interactionId) s.events.push({ id: e.interactionId, name: e.name, dur: e.duration,
    inputDelay: e.processingStart - e.startTime, processing: e.processingEnd - e.processingStart }); }, { durationThreshold: 16 });
};

const median = (xs) => { const s = xs.filter((x) => x != null).sort((a, b) => a - b); if (!s.length) return null;
  const m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };

const pw = await loadPlaywright();
let browser;
const channel = opt('channel', undefined);
try { browser = await pw.chromium.launch({ headless: !flag('headed'), channel }); }
catch (e) {
  if (channel) throw e;
  console.error('bundled Chromium unavailable, trying installed Chrome (--channel chrome)');
  browser = await pw.chromium.launch({ headless: !flag('headed'), channel: 'chrome' });
}
const interact = opt('interact') ? (await import(pathToFileURL(path.resolve(opt('interact'))).href)).default : null;
const results = [];
for (let i = 1; i <= runs; i++) {
  const ctx = await browser.newContext({ viewport: { width: vw, height: vh }, deviceScaleFactor: flag('mobile') ? 2.6 : 1, isMobile: flag('mobile') });
  const page = await ctx.newPage();
  await page.addInitScript(OBSERVE);
  const cdp = await ctx.newCDPSession(page);
  await cdp.send('Network.enable');
  await cdp.send('Network.setCacheDisabled', { cacheDisabled: true });
  if (cpu > 1) await cdp.send('Emulation.setCPUThrottlingRate', { rate: cpu });
  if (NETWORK[network]) await cdp.send('Network.emulateNetworkConditions', NETWORK[network]);
  let bytes = 0;
  cdp.on('Network.loadingFinished', (e) => { bytes += e.encodedDataLength || 0; });
  const tracePath = path.join(out, `run-${i}.trace.json`);
  if (!flag('no-trace')) {
    await browser.startTracing(page, { path: tracePath, screenshots: false, categories: [
      'devtools.timeline', 'disabled-by-default-devtools.timeline', 'disabled-by-default-devtools.timeline.frame',
      'v8.execute', 'disabled-by-default-v8.cpu_profiler', 'blink.user_timing', 'loading', 'latencyInfo', 'toplevel'] });
  }
  const t0 = Date.now();
  await page.goto(url, { waitUntil: 'load', timeout: 120000 });
  await page.waitForTimeout(waitMs);
  const interactStart = await page.evaluate(() => performance.now());
  if (interact) { await interact(page); await page.waitForTimeout(500); }
  const m = await page.evaluate((interactStart) => {
    const nav = performance.getEntriesByType('navigation')[0] || {};
    const s = window.__perf;
    // TBT: long tasks between FCP and the start of scripted interactions (load-time blocking only)
    const tbt = s.longtasks.filter((t) => t.start >= s.fcp && t.start < interactStart).reduce((a, t) => a + Math.max(0, t.dur - 50), 0);
    const interactionBlocking = s.longtasks.filter((t) => t.start >= interactStart).reduce((a, t) => a + Math.max(0, t.dur - 50), 0);
    const byId = {}; for (const e of s.events) byId[e.id] = Math.max(byId[e.id] || 0, e.dur);
    const worst = s.events.slice().sort((a, b) => b.dur - a.dur)[0] || null;
    return { ttfb: nav.responseStart, domContentLoaded: nav.domContentLoadedEventEnd, load: nav.loadEventEnd,
      fcp: s.fcp, lcp: s.lcp, cls: +s.cls.toFixed(4), tbt, interactionBlocking, longTasks: s.longtasks.length,
      longestTask: Math.max(0, ...s.longtasks.map((t) => t.dur)),
      interactions: Object.keys(byId).length, maxInteraction: Object.keys(byId).length ? Math.max(...Object.values(byId)) : null,
      worstInteraction: worst, domNodes: document.getElementsByTagName('*').length,
      jsHeapMB: performance.memory ? +(performance.memory.usedJSHeapSize / 1048576).toFixed(1) : null };
  }, interactStart);
  if (!flag('no-trace')) await browser.stopTracing();
  m.transferKB = +(bytes / 1024).toFixed(1);
  m.wallMs = Date.now() - t0;
  results.push(m);
  console.error(`run ${i}: LCP ${m.lcp?.toFixed(0)} ms  TBT ${m.tbt.toFixed(0)} ms  CLS ${m.cls}  long tasks ${m.longTasks}` +
    (m.interactions ? `  max interaction ${m.maxInteraction?.toFixed(0)} ms` : ''));
  await ctx.close();
}
await browser.close();
const keys = ['ttfb', 'fcp', 'lcp', 'cls', 'tbt', 'interactionBlocking', 'longTasks', 'longestTask', 'maxInteraction', 'domNodes', 'jsHeapMB', 'transferKB'];
const med = Object.fromEntries(keys.map((k) => [k, median(results.map((r) => r[k]))]));
const doc = { url, runs, cpuThrottle: cpu, network, viewport: `${vw}x${vh}`, chrome: browser.version?.() ?? null, median: med, perRun: results,
  note: 'lab metrics; maxInteraction is an INP proxy only when --interact drives real interactions; tbt = load-time blocking (FCP..interactions); interactionBlocking = blocking during --interact' };
fs.writeFileSync(path.join(out, 'metrics.json'), JSON.stringify(doc, null, 2));
// flat metrics for perfkit gate budgets: {"web.lcp_ms": .., ...}
fs.writeFileSync(path.join(out, 'metrics.flat.json'), JSON.stringify({ web: { lcp_ms: med.lcp, fcp_ms: med.fcp, cls: med.cls,
  tbt_ms: med.tbt, max_interaction_ms: med.maxInteraction, transfer_kb: med.transferKB, dom_nodes: med.domNodes } }, null, 2));
console.log(JSON.stringify({ median: med }, null, 2));
console.error(`wrote ${out}/metrics.json and ${runs} trace(s); next: python3 <perfkit.py> hotspots ${out}/run-1.trace.json`);
