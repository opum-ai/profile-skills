import { readFileSync } from 'node:fs';
import { fetchManifest, type Manifest } from './registry.ts';

export interface Pkg { name: string; version: string; deps: string[] }
export interface Workspace { packages: Pkg[] }
export interface Resolution { order: string[]; levels: Record<string, number>; manifests: Manifest[]; totalSize: number }

export function loadWorkspace(path: string): Workspace {
  return JSON.parse(readFileSync(path, 'utf8'));
}

// Binary min-heap of names: the ready set, ordered alphabetically by code unit (same as Array#sort default).
class NameHeap {
  private a: string[] = [];
  get size() { return this.a.length; }
  push(x: string) {
    const a = this.a; a.push(x);
    let i = a.length - 1;
    while (i > 0) { const p = (i - 1) >> 1; if (a[p] <= a[i]) break; [a[p], a[i]] = [a[i], a[p]]; i = p; }
  }
  pop(): string {
    const a = this.a; const top = a[0]; const last = a.pop()!;
    if (a.length) {
      a[0] = last; let i = 0;
      for (;;) {
        const l = 2 * i + 1, r = l + 1; let m = i;
        if (l < a.length && a[l] < a[m]) m = l;
        if (r < a.length && a[r] < a[m]) m = r;
        if (m === i) break;
        [a[m], a[i]] = [a[i], a[m]]; i = m;
      }
    }
    return top;
  }
}

// Deterministic topological order: among ready packages, always take the alphabetically first.
export function installOrder(ws: Workspace): string[] {
  const pending = new Map<string, number>();      // name -> unmet dependency count
  const dependents = new Map<string, string[]>();
  for (const p of ws.packages) {
    const uniq = new Set(p.deps);
    pending.set(p.name, uniq.size);
    for (const d of uniq) {
      let list = dependents.get(d);
      if (!list) dependents.set(d, (list = []));
      list.push(p.name);
    }
  }
  const ready = new NameHeap();
  for (const [name, n] of pending) if (n === 0) ready.push(name);
  const order: string[] = [];
  while (ready.size) {
    const next = ready.pop();
    order.push(next);
    pending.delete(next);
    for (const dep of dependents.get(next) ?? []) {
      const left = pending.get(dep)! - 1;
      pending.set(dep, left);
      if (left === 0) ready.push(dep);
    }
  }
  if (pending.size) throw new Error(`dependency cycle among: ${[...pending.keys()].sort().join(', ')}`);
  return order;
}

export function levels(ws: Workspace, order: string[]): Record<string, number> {
  const byName = new Map(ws.packages.map((p) => [p.name, p] as const));
  const out: Record<string, number> = {};
  for (const name of order) {
    const pkg = byName.get(name)!;
    let lvl = 0;
    for (const d of pkg.deps) lvl = Math.max(lvl, out[d] + 1);
    out[name] = lvl;
  }
  return out;
}

async function mapLimit<T, R>(items: T[], limit: number, fn: (x: T) => Promise<R>): Promise<R[]> {
  const out = new Array<R>(items.length);
  let next = 0;
  const worker = async () => { while (next < items.length) { const i = next++; out[i] = await fn(items[i]); } };
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, worker));
  return out;
}

export async function resolve(ws: Workspace): Promise<Resolution> {
  const known = new Set(ws.packages.map((p) => p.name));
  for (const p of ws.packages) for (const d of p.deps) {
    if (!known.has(d)) throw new Error(`${p.name} depends on unknown package ${d}`);
  }
  const order = installOrder(ws);
  const byName = new Map(ws.packages.map((p) => [p.name, p] as const));
  const manifests = await mapLimit(order, 16, (name) => {
    const pkg = byName.get(name)!;
    return fetchManifest(pkg.name, pkg.version);
  });
  let totalSize = 0;
  for (const m of manifests) totalSize += m.size;
  return { order, levels: levels(ws, order), manifests, totalSize };
}
