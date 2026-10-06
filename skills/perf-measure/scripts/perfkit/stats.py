"""Small, dependency-free statistics for benchmark comparison.

Everything here is deliberately robust rather than parametric: benchmark samples are
skewed (a long right tail from GC, scheduling and cache misses), so we summarise with the
median and IQR, compare with Mann-Whitney U, and put a bootstrap confidence interval on
the ratio of medians. Results are deterministic for a given seed.
"""
import math
import random
from typing import Dict, List, Sequence, Tuple


def quantile(xs: Sequence[float], q: float) -> float:
    """Linear-interpolated quantile (type 7, the numpy default)."""
    if not xs:
        raise ValueError("quantile of empty sample")
    s = sorted(xs)
    if len(s) == 1:
        return float(s[0])
    pos = (len(s) - 1) * q
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def median(xs: Sequence[float]) -> float:
    return quantile(xs, 0.5)


def summary(xs: Sequence[float]) -> Dict[str, float]:
    n = len(xs)
    mean = sum(xs) / n
    var = sum((x - mean) ** 2 for x in xs) / (n - 1) if n > 1 else 0.0
    sd = math.sqrt(var)
    q1, med, q3 = quantile(xs, 0.25), quantile(xs, 0.5), quantile(xs, 0.75)
    return {
        "n": n,
        "min": float(min(xs)),
        "q1": q1,
        "median": med,
        "q3": q3,
        "max": float(max(xs)),
        "p95": quantile(xs, 0.95),
        "mean": mean,
        "stdev": sd,
        "cv": sd / mean if mean else 0.0,
        "iqr_rel": (q3 - q1) / med if med else 0.0,
    }


def _norm_sf(z: float) -> float:
    return 0.5 * math.erfc(z / math.sqrt(2))


def mann_whitney(a: Sequence[float], b: Sequence[float]) -> Tuple[float, float]:
    """Two-sided Mann-Whitney U test (normal approximation, tie-corrected, continuity-corrected).

    Returns (U for sample a, p-value). Adequate for n >= ~8 per side, which is the floor the
    skills recommend anyway; below that the p-value is conservative-ish and should not be trusted.
    """
    n1, n2 = len(a), len(b)
    pooled = sorted([(v, 0) for v in a] + [(v, 1) for v in b])
    ranks = [0.0] * len(pooled)
    tie_term = 0.0
    i = 0
    while i < len(pooled):
        j = i
        while j + 1 < len(pooled) and pooled[j + 1][0] == pooled[i][0]:
            j += 1
        r = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[k] = r
        t = j - i + 1
        tie_term += t ** 3 - t
        i = j + 1
    r1 = sum(r for r, (_, g) in zip(ranks, pooled) if g == 0)
    u1 = r1 - n1 * (n1 + 1) / 2.0
    mu = n1 * n2 / 2.0
    n = n1 + n2
    sigma2 = n1 * n2 / 12.0 * ((n + 1) - tie_term / (n * (n - 1))) if n > 1 else 0.0
    if sigma2 <= 0:
        return u1, 1.0
    z = (abs(u1 - mu) - 0.5) / math.sqrt(sigma2)
    return u1, min(1.0, 2.0 * _norm_sf(max(z, 0.0)))


def cliffs_delta(a: Sequence[float], b: Sequence[float]) -> float:
    """P(b > a) - P(b < a). -1 means every b is smaller (b faster), +1 every b larger."""
    gt = lt = 0
    for x in a:
        for y in b:
            if y > x:
                gt += 1
            elif y < x:
                lt += 1
    return (gt - lt) / float(len(a) * len(b))


def bootstrap_ratio_ci(a: Sequence[float], b: Sequence[float], conf: float = 0.95,
                       iters: int = 4000, seed: int = 0, stat=median) -> Tuple[float, float, float]:
    """Percentile-bootstrap CI for stat(b) / stat(a). Returns (point, lo, hi)."""
    rng = random.Random(seed)
    point = stat(b) / stat(a)
    na, nb = len(a), len(b)
    ratios: List[float] = []
    for _ in range(iters):
        sa = [a[rng.randrange(na)] for _ in range(na)]
        sb = [b[rng.randrange(nb)] for _ in range(nb)]
        den = stat(sa)
        if den:
            ratios.append(stat(sb) / den)
    ratios.sort()
    alpha = (1 - conf) / 2
    return point, quantile(ratios, alpha), quantile(ratios, 1 - alpha)


def runs_needed(a: Sequence[float], b: Sequence[float], min_effect: float, conf: float = 0.95) -> int:
    """Rough per-arm sample size so a CI on the median ratio is narrower than min_effect.

    Uses the pooled relative spread (IQR/1.349 ~ sigma for a normal) and the asymptotic
    standard error of a median (1.2533 * sigma / sqrt(n)). It is a planning aid, not a power
    analysis: treat it as "at least this many".
    """
    z = 1.959964 if conf == 0.95 else abs(_inv_norm((1 - conf) / 2))
    rel = []
    for xs in (a, b):
        med = median(xs)
        if med:
            rel.append((quantile(xs, 0.75) - quantile(xs, 0.25)) / 1.349 / med)
    sigma = max(rel) if rel else 0.0
    if sigma == 0 or min_effect <= 0:
        return max(len(a), len(b))
    # half-width of the ratio CI ~ z * sqrt(2) * 1.2533 * sigma / sqrt(n); want it < min_effect / 2
    n = (2 * z * math.sqrt(2) * 1.2533 * sigma / min_effect) ** 2
    return int(math.ceil(max(n, 5)))


def _inv_norm(p: float) -> float:
    # Acklam's approximation, good to ~1e-9; only used for non-default confidence levels.
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow = 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > 1 - plow:
        return -_inv_norm(1 - p)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


def wilcoxon_signed_rank(d: Sequence[float]) -> float:
    """Two-sided Wilcoxon signed-rank p-value (normal approximation, tie- and continuity-corrected)."""
    nz = [x for x in d if x != 0]
    n = len(nz)
    if n == 0:
        return 1.0
    order = sorted(range(n), key=lambda i: abs(nz[i]))
    ranks = [0.0] * n
    tie_term = 0.0
    i = 0
    while i < n:
        j = i
        while j + 1 < n and abs(nz[order[j + 1]]) == abs(nz[order[i]]):
            j += 1
        r = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = r
        t = j - i + 1
        tie_term += t ** 3 - t
        i = j + 1
    w_plus = sum(r for r, x in zip(ranks, nz) if x > 0)
    mu = n * (n + 1) / 4.0
    sigma2 = n * (n + 1) * (2 * n + 1) / 24.0 - tie_term / 48.0
    if sigma2 <= 0:
        return 1.0
    z = (abs(w_plus - mu) - 0.5) / math.sqrt(sigma2)
    return min(1.0, 2.0 * _norm_sf(max(z, 0.0)))


def paired_ratio_ci(a: Sequence[float], b: Sequence[float], conf: float = 0.95, iters: int = 4000,
                    seed: int = 0) -> Tuple[float, float, float]:
    """CI on exp(median(log(b_i / a_i))) over pairs (a_i, b_i) measured in the same interleaved block."""
    rng = random.Random(seed)
    logs = [math.log(y / x) for x, y in zip(a, b) if x > 0 and y > 0]
    point = math.exp(median(logs))
    n = len(logs)
    boots = sorted(math.exp(median([logs[rng.randrange(n)] for _ in range(n)])) for _ in range(iters))
    alpha = (1 - conf) / 2
    return point, quantile(boots, alpha), quantile(boots, 1 - alpha)


def compare(a: Sequence[float], b: Sequence[float], *, min_effect: float = 0.02, alpha: float = 0.05,
            conf: float = 0.95, seed: int = 0, lower_is_better: bool = True, max_cv: float = 0.10,
            paired: bool = False) -> Dict:
    """Compare baseline a with candidate b and return a verdict with the evidence behind it.

    Verdicts (lower_is_better=True, i.e. times):
      improved     CI of median(b)/median(a) lies entirely below 1 - min_effect... or entirely below 1
                   with the point estimate past the threshold, and Mann-Whitney p < alpha
      regressed    the mirror image above 1 + min_effect
      equivalent   CI lies entirely inside [1 - min_effect, 1 + min_effect]
      inconclusive anything else; `runs_needed` says roughly how many runs per arm would decide it
    """
    if len(a) < 2 or len(b) < 2:
        raise ValueError("need at least 2 samples per arm (10+ recommended)")
    sa, sb = summary(a), summary(b)
    paired = paired and len(a) == len(b)
    if paired:
        # Each (a_i, b_i) came from the same interleaved block: analysing per-block ratios cancels drift
        # (thermal, background load) that an unpaired test has to absorb as noise.
        point, lo, hi = paired_ratio_ci(a, b, conf=conf, seed=seed)
        p = wilcoxon_signed_rank([math.log(y / x) for x, y in zip(a, b) if x > 0 and y > 0])
    else:
        point, lo, hi = bootstrap_ratio_ci(a, b, conf=conf, seed=seed)
        _, p = mann_whitney(a, b)
    delta = cliffs_delta(a, b)
    lo_t, hi_t = 1 - min_effect, 1 + min_effect
    better_ci, worse_ci = (hi < 1.0, lo > 1.0) if lower_is_better else (lo > 1.0, hi < 1.0)
    better_pt = point <= lo_t if lower_is_better else point >= hi_t
    worse_pt = point >= hi_t if lower_is_better else point <= lo_t
    if better_ci and better_pt and p < alpha:
        verdict = "improved"
    elif worse_ci and worse_pt and p < alpha:
        verdict = "regressed"
    elif lo >= lo_t and hi <= hi_t:
        verdict = "equivalent"
    elif (better_ci or worse_ci) and p < alpha:
        verdict = "below-threshold"  # real but smaller than min_effect
    else:
        verdict = "inconclusive"
    warnings = []
    for label, s in (("baseline", sa), ("candidate", sb)):
        if s["n"] < 10:
            warnings.append(f"{label}: only {s['n']} samples; 10+ per arm recommended")
        if s["iqr_rel"] > max_cv:
            warnings.append(f"{label}: noisy (IQR/median {s['iqr_rel']:.1%} > {max_cv:.0%}); "
                            "quiet the machine, lengthen each run, or add runs")
    speedup = (1.0 / point) if (lower_is_better and point) else point
    out = {
        "verdict": verdict,
        "ratio": point,
        "ratio_ci": [lo, hi],
        "confidence": conf,
        "speedup": speedup,
        "change_pct": (point - 1.0) * 100.0,
        "p_value": p,
        "test": "wilcoxon-signed-rank (paired blocks)" if paired else "mann-whitney-u",
        "paired": paired,
        "cliffs_delta": delta,
        "min_effect": min_effect,
        "alpha": alpha,
        "lower_is_better": lower_is_better,
        "baseline": sa,
        "candidate": sb,
        "warnings": warnings,
    }
    if verdict == "inconclusive":
        out["runs_needed"] = runs_needed(a, b, min_effect, conf)
    return out


def loglog_fit(sizes: Sequence[float], times: Sequence[float]) -> Dict[str, float]:
    """Least-squares fit of log(time) = k*log(size) + c. k is the empirical complexity exponent."""
    xs = [math.log(s) for s in sizes]
    ys = [math.log(t) for t in times]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    k = sxy / sxx if sxx else float("nan")
    c = my - k * mx
    ss_tot = sum((y - my) ** 2 for y in ys)
    ss_res = sum((y - (k * x + c)) ** 2 for x, y in zip(xs, ys))
    r2 = 1 - ss_res / ss_tot if ss_tot else 1.0
    return {"exponent": k, "intercept": c, "r2": r2}


def classify_exponent(k: float) -> str:
    if k != k:  # NaN
        return "unknown"
    if k < 0.3:
        return "~O(1) / dominated by fixed cost"
    if k < 0.8:
        return "sub-linear (or fixed cost still dominates at these sizes)"
    if k < 1.25:
        return "~O(n) or O(n log n)"
    if k < 1.75:
        return "super-linear (~n^1.5); check for hidden nested work"
    if k < 2.5:
        return "~O(n^2): quadratic"
    return "~O(n^3) or worse"
