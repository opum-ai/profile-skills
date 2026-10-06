// node make_data.mjs <n> <seed> > data.js
const [n, seed] = process.argv.slice(2).map(Number);
let s = seed >>> 0; const rnd = () => ((s = (Math.imul(s, 1664525) + 1013904223) >>> 0) / 4294967296);
const tags = ['red', 'green', 'blue', 'urgent', 'backlog', 'billing', 'infra', 'mobile', 'web', 'api'];
const owners = ['ana', 'ben', 'chen', 'dev', 'eli', 'fay', 'gus', 'hal'];
const rows = Array.from({ length: n }, (_, i) => ({
  id: i + 1,
  title: `Ticket ${i + 1}: ${['fix', 'add', 'remove', 'refactor', 'investigate'][Math.floor(rnd() * 5)]} ${['login', 'cart', 'search', 'export', 'billing', 'profile'][Math.floor(rnd() * 6)]} ${Math.floor(rnd() * 1000)}`,
  owner: owners[Math.floor(rnd() * owners.length)],
  tags: tags.filter(() => rnd() < 0.25),
  points: 1 + Math.floor(rnd() * 13),
}));
console.log(`window.TICKETS = ${JSON.stringify(rows)};`);
