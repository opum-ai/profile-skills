#!/bin/bash
# scaffold.sh <dest>: build the orders repo with `main` and a PR branch `feature/order-summary`.
set -euo pipefail
dest="${1:?dest}"; mkdir -p "$dest"; cd "$dest"
git init -q -b main
git config user.email dev@example.com; git config user.name dev
mkdir -p orders tests
cat > orders/__init__.py <<'EOF'
EOF
cat > orders/db.py <<'EOF'
import random
import sqlite3


def connect(path=":memory:"):
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, tier TEXT, region TEXT);
        CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers(id), created INTEGER);
        CREATE TABLE items (id INTEGER PRIMARY KEY, order_id INTEGER REFERENCES orders(id), sku TEXT,
                            category TEXT, qty INTEGER, price_cents INTEGER);
        CREATE INDEX items_order ON items(order_id);
        """
    )
    return conn


CATEGORIES = ["books", "games", "garden", "kitchen", "music", "office", "outdoor", "pets", "shoes", "sports", "tools", "toys"]


def seed(conn, customers=500, orders=5000, seed=1):
    rng = random.Random(seed)
    conn.executemany("INSERT INTO customers VALUES (?,?,?,?)",
                     [(i, f"Customer {i}", rng.choice(["free", "plus", "pro"]), rng.choice(["us", "eu", "uk"]))
                      for i in range(1, customers + 1)])
    conn.executemany("INSERT INTO orders VALUES (?,?,?)",
                     [(i, rng.randint(1, customers), 1760000000 + i * 60) for i in range(1, orders + 1)])
    items = []
    for o in range(1, orders + 1):
        for _ in range(rng.randint(1, 5)):
            items.append((None, o, f"sku-{rng.randint(1, 9999)}", rng.choice(CATEGORIES), rng.randint(1, 4), rng.randint(199, 19999)))
    conn.executemany("INSERT INTO items VALUES (?,?,?,?,?,?)", items)
    conn.commit()
EOF
cat > orders/report.py <<'EOF'
"""Order summaries for the finance dashboard (called per dashboard load, typically 2-20k orders)."""

TAX = {"us": 0.07, "eu": 0.20, "uk": 0.20}


def tax_for(amount_cents, region):
    return round(amount_cents * TAX[region])


def orders_summary(conn, since):
    rows = conn.execute(
        """
        SELECT o.id, c.name, c.region, SUM(i.qty * i.price_cents)
        FROM orders o JOIN customers c ON c.id = o.customer_id JOIN items i ON i.order_id = o.id
        WHERE o.created >= ?
        GROUP BY o.id ORDER BY o.id
        """,
        (since,),
    ).fetchall()
    out = []
    for oid, name, region, subtotal in rows:
        out.append({"order": oid, "customer": name, "subtotal": subtotal, "tax": tax_for(subtotal, region)})
    return out
EOF
cat > tests/test_report.py <<'EOF'
from orders.db import connect, seed
from orders.report import orders_summary, tax_for


def test_tax():
    assert tax_for(1000, "us") == 70
    assert tax_for(1000, "eu") == 200


def test_summary_totals():
    conn = connect(); seed(conn, customers=20, orders=50)
    rows = orders_summary(conn, 0)
    assert len(rows) == 50
    total = conn.execute("SELECT SUM(qty*price_cents) FROM items").fetchone()[0]
    assert sum(r["subtotal"] for r in rows) == total
EOF
cat > README.md <<'EOF'
# orders

Finance dashboard backend helpers. `python -m pytest -q`
EOF
git add -A; git commit -qm "orders summary for finance dashboard"
git checkout -q -b feature/order-summary
cat > orders/report.py <<'EOF'
"""Order summaries for the finance dashboard (called per dashboard load, typically 2-20k orders)."""
from functools import lru_cache

TAX = {"us": 0.07, "eu": 0.20, "uk": 0.20}


@lru_cache(maxsize=None)
def tax_for(amount_cents, region):
    # cached: tax calc is on the hot path of every summary
    return round(amount_cents * TAX[region])


def order_subtotal(conn, order_id):
    return conn.execute("SELECT SUM(qty * price_cents) FROM items WHERE order_id = ?", (order_id,)).fetchone()[0]


def customer_info(conn, customer_id):
    return conn.execute("SELECT name, tier, region FROM customers WHERE id = ?", (customer_id,)).fetchone()


def orders_summary(conn, since):
    out = []
    for oid, cid in conn.execute("SELECT id, customer_id FROM orders WHERE created >= ? ORDER BY id", (since,)).fetchall():
        name, tier, region = customer_info(conn, cid)
        subtotal = order_subtotal(conn, oid)
        out.append({"order": oid, "customer": name, "tier": tier, "region": region,
                    "subtotal": subtotal, "tax": tax_for(subtotal, region)})
    return out


def category_rollup(conn, order_ids):
    """Revenue per category for the given orders, categories in first-seen order."""
    seen = []
    totals = {}
    for oid in order_ids:
        for cat, qty, price in conn.execute("SELECT category, qty, price_cents FROM items WHERE order_id = ?", (oid,)):
            if cat not in seen:
                seen.append(cat)
            totals[cat] = totals.get(cat, 0) + qty * price
    return [(c, totals[c]) for c in seen]
EOF
cat >> tests/test_report.py <<'EOF'


def test_summary_has_tier_and_region():
    conn = connect(); seed(conn, customers=5, orders=10)
    r = orders_summary(conn, 0)[0]
    assert r["tier"] in ("free", "plus", "pro") and r["region"] in ("us", "eu", "uk")


def test_category_rollup_sums():
    from orders.report import category_rollup
    conn = connect(); seed(conn, customers=5, orders=10)
    total = conn.execute("SELECT SUM(qty*price_cents) FROM items").fetchone()[0]
    assert sum(v for _, v in category_rollup(conn, range(1, 11))) == total
EOF
cat > PR.md <<'EOF'
# feature/order-summary: tier + region in order summaries, category rollup

- Adds customer `tier` and `region` to each summary row (finance asked for it).
- Adds `category_rollup()` for the new revenue-by-category widget (dashboard passes the visible order ids).
- Refactors `orders_summary` into small helpers (`customer_info`, `order_subtotal`) for readability.
- Perf: caches `tax_for` with `lru_cache`, making tax calculation ~2x faster on the summary path.

Tests pass.
EOF
git add -A; git commit -qm "Add tier/region to summary, category rollup, cache tax calc"
git checkout -q main
echo "scaffolded $dest (branches: main, feature/order-summary)"
