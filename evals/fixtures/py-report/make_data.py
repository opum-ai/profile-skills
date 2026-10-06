"""Generate a synthetic events CSV: python make_data.py <rows> <seed> > data/events.csv"""
import random
import sys

rows, seed = int(sys.argv[1]), int(sys.argv[2])
rng = random.Random(seed)
codes = ["us-east", "us-west", "eu-central", "eu-west", "ap-south", "ap-northeast", "sa-east", "xx-test"]
kinds = ["purchase"] * 5 + ["refund"] + ["signup"] * 2 + ["view"] * 8
users = max(10, rows // 4)
print("event_id,user_id,region_code,kind,amount_cents,ts")
emitted = []
for i in range(rows):
    if emitted and rng.random() < 0.08:  # at-least-once redelivery
        print(rng.choice(emitted))
        continue
    kind = rng.choice(kinds)
    amount = rng.randint(100, 50000) if kind in ("purchase", "refund") else 0
    line = f"ev{seed}-{i},u{rng.randint(1, users)},{rng.choice(codes)},{kind},{amount},{1760000000 + i}"
    emitted.append(line)
    print(line)
