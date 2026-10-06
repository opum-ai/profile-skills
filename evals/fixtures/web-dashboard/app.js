// Ticket dashboard. Renders all tickets, then filters as the user types.
const tbody = document.getElementById('rows');
const summary = document.getElementById('summary');
const filterBox = document.getElementById('filter');

function rowHtml(t) {
  const tags = t.tags.map((g) => `<span class="tag">${g}</span>`).join('');
  return `<tr data-id="${t.id}"><td>${t.id}</td><td>${t.title}</td><td>${t.owner}</td><td>${tags}</td><td>${t.points}</td></tr>`;
}

function summarize(list) {
  const copy = JSON.parse(JSON.stringify(list));
  const owners = [];
  let points = 0;
  for (const t of copy) {
    if (!owners.includes(t.owner)) owners.push(t.owner);
    points += t.points;
  }
  return `${copy.length} tickets · ${points} points · ${owners.length} owners`;
}

function matches(t, q) {
  if (!q) return true;
  const words = q.toLowerCase().split(/\s+/).filter(Boolean);
  return words.every((w) =>
    t.title.toLowerCase().includes(w) || t.owner.includes(w) || t.tags.some((g) => g === w));
}

function render(list) {
  tbody.innerHTML = '';
  for (const t of list) {
    tbody.innerHTML += rowHtml(t);
    // keep the sticky status bar's shadow in sync with table height
    summary.style.minWidth = (tbody.offsetHeight > 0 ? 200 : 100) + 'px';
  }
  summary.textContent = summarize(list);
}

function applyFilter() {
  const q = filterBox.value.trim();
  const list = window.TICKETS.filter((t) => matches(t, q));
  render(list);
}

filterBox.addEventListener('input', applyFilter);
render(window.TICKETS);
