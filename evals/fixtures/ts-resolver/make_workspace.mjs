// node make_workspace.mjs <n> <seed> > fixtures/ws.json : random DAG of n packages
const [n, seed] = process.argv.slice(2).map(Number);
let s = seed >>> 0; const rnd = () => ((s = (Math.imul(s, 1664525) + 1013904223) >>> 0) / 4294967296);
const names = Array.from({ length: n }, (_, i) => `pkg-${(i * 2654435761 % 1e6).toString(36)}-${i}`);
const packages = names.map((name, i) => {
  const deps = new Set();
  const k = i === 0 ? 0 : Math.floor(rnd() * Math.min(6, i));
  for (let j = 0; j < k; j++) deps.add(names[Math.floor(rnd() * i)]);
  return { name, version: `${1 + Math.floor(rnd() * 5)}.${Math.floor(rnd() * 20)}.${Math.floor(rnd() * 10)}`, deps: [...deps] };
});
for (let i = packages.length - 1; i > 0; i--) { const j = Math.floor(rnd() * (i + 1)); [packages[i], packages[j]] = [packages[j], packages[i]]; }
console.log(JSON.stringify({ packages }));
