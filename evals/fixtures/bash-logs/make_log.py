"""python3 make_log.py <lines> <seed> > data/access.log"""
import random, sys
n, seed = int(sys.argv[1]), int(sys.argv[2])
rng = random.Random(seed)
paths = ["/api/orders/{id}", "/api/orders", "/api/users/{id}/profile", "/static/app.js", "/health", "/api/search?q={q}",
         "/api/orders/{id}/items/{id}", "/login"]
tenants = ["Acme", "acme", "Zeta", "zeta", "beta", "Beta", "_internal", "Omega", "omega", "delta", "Delta", "Kappa",
           "kappa", "mu", "Mu", "nu", "Nu", "Xi", "xi", "pi", "Pi", "rho", "Rho", "Sigma", "sigma", "tau", "Tau"]
days = ["03/Oct/2026", "04/Oct/2026", "05/Oct/2026"]
for i in range(n):
    if rng.random() < 0.002:
        print("garbage line without structure"); continue
    p = rng.choice(paths)
    if rng.random() < 0.7:
        p = "/t/" + rng.choice(tenants) + p
    while "{id}" in p:
        p = p.replace("{id}", str(rng.randint(1, 99999)), 1)
    p = p.replace("{q}", rng.choice(["shoes", "red+hat", "x%20y"]))
    status = rng.choice([200] * 30 + [201, 204, 301, 304, 400, 404, 500, 502, 503])
    ms = int(rng.expovariate(1 / 120))
    day = days[min(2, i * 3 // n)]
    print(f'10.0.{rng.randint(0,255)}.{rng.randint(1,254)} - {rng.choice(["-", "alice", "bob"])} [{day}:{rng.randint(0,23):02d}:{rng.randint(0,59):02d}:{rng.randint(0,59):02d} +0000] "{rng.choice(["GET"]*8+["POST","PUT"])} {p} HTTP/1.1" {status} {rng.randint(0, 200000)} {ms}')
