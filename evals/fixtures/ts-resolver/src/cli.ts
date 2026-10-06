import { loadWorkspace, resolve } from './graph.ts';

const file = process.argv[2];
if (!file) { console.error('usage: node src/cli.ts <workspace.json>'); process.exit(2); }
const r = await resolve(loadWorkspace(file));
const depth = Math.max(0, ...Object.values(r.levels));
console.log(`packages: ${r.order.length}  depth: ${depth}  total size: ${r.totalSize}`);
for (const m of r.manifests) console.log(`${String(r.levels[m.name]).padStart(3)} ${m.name}@${m.version} ${m.integrity}`);
