// Simulated package registry client. In production this is an HTTP call to the internal registry
// (~2 ms per request). The registry allows at most 16 concurrent requests per client; request 17
// gets HTTP 429 and the deploy fails, so never have more than 16 fetches in flight.
// (REGISTRY_STATS=<file> records the peak number of in-flight requests; used by the integration harness.)
import { writeFileSync } from 'node:fs';

export interface Manifest { name: string; version: string; integrity: string; size: number }

const LIMIT = 16;
let inFlight = 0;
let maxInFlight = 0;
if (process.env.REGISTRY_STATS) {
  const path = process.env.REGISTRY_STATS;
  process.on('exit', () => { writeFileSync(path, JSON.stringify({ maxInFlight })); });
}

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

export async function fetchManifest(name: string, version: string): Promise<Manifest> {
  if (inFlight >= LIMIT) throw new Error(`registry: 429 Too Many Requests (more than ${LIMIT} concurrent requests)`);
  inFlight++;
  maxInFlight = Math.max(maxInFlight, inFlight);
  try {
    await sleep(2);
    let h = 2166136261;
    const s = `${name}@${version}`;
    for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619) >>> 0; }
    return { name, version, integrity: `sha1-${h.toString(16).padStart(8, '0')}`, size: (h % 90000) + 1000 };
  } finally {
    inFlight--;
  }
}
