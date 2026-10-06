import { readFileSync } from 'node:fs';
import { fetchManifest, type Manifest } from './registry.ts';

export interface Pkg { name: string; version: string; deps: string[] }
export interface Workspace { packages: Pkg[] }
export interface Resolution { order: string[]; levels: Record<string, number>; manifests: Manifest[]; totalSize: number }

export function loadWorkspace(path: string): Workspace {
  return JSON.parse(readFileSync(path, 'utf8'));
}

function clone<T>(x: T): T { return JSON.parse(JSON.stringify(x)); }

// Deterministic topological order: among ready packages, always take the alphabetically first.
export function installOrder(ws: Workspace): string[] {
  let graph = clone(ws.packages);
  const order: string[] = [];
  while (graph.length > 0) {
    const ready = graph.filter((p) => p.deps.every((d) => order.includes(d))).map((p) => p.name).sort();
    if (ready.length === 0) throw new Error(`dependency cycle among: ${graph.map((p) => p.name).sort().join(', ')}`);
    const next = ready[0];
    order.push(next);
    graph = clone(graph.filter((p) => p.name !== next));
  }
  return order;
}

export function levels(ws: Workspace, order: string[]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const name of order) {
    const pkg = ws.packages.find((p) => p.name === name)!;
    let lvl = 0;
    for (const d of pkg.deps) lvl = Math.max(lvl, out[d] + 1);
    out[name] = lvl;
  }
  return out;
}

export async function resolve(ws: Workspace): Promise<Resolution> {
  const known = ws.packages.map((p) => p.name);
  for (const p of ws.packages) for (const d of p.deps) {
    if (!known.includes(d)) throw new Error(`${p.name} depends on unknown package ${d}`);
  }
  const order = installOrder(ws);
  const manifests: Manifest[] = [];
  for (const name of order) {
    const pkg = ws.packages.find((p) => p.name === name)!;
    manifests.push(await fetchManifest(pkg.name, pkg.version));
  }
  let totalSize = 0;
  for (const m of manifests) totalSize += m.size;
  return { order, levels: levels(ws, order), manifests, totalSize };
}
