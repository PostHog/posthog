"""Truth-sensitivity of the arm ranking. Writes findings/SENSITIVITY.md.
A fresh     = per-finding 3-skeptic majority (as judged)
B pooled    = registry-matched findings take the majority of ALL fresh votes cast on their cluster in this experiment
C august    = clusters with >=2 August verdicts take August's majority (tie -> fresh); others fresh
D serious   = A, counting only must_fix / should_fix as real
E adjudicated = A with the 14 contested clusters replaced by the 3-adjudicator panel (findings/<S>.truth.adjudicated.json)
F adjudicated serious = E, counting only must_fix / should_fix as real
"""
import json, re
from collections import defaultdict
from pathlib import Path
EXP = Path(__file__).resolve().parent.parent
SETS = [("GC", "glm-high-1bc"), ("GB", "glm-high-2"), ("UA", "luna-low-1"), ("UB", "luna-low-2"), ("SA", "sol-low-1"), ("SB", "sol-low-2")]
ARM = {"glm-high": "GLM 5.3 Flash @ high", "luna-low": "GPT 5.6 Luna @ low", "sol-low": "GPT 5.6 Sol @ low"}
reg = {c["cluster"]: c for c in json.load(open(EXP / "known_clusters.json"))}
data = {}
adj = {}
pool = defaultdict(lambda: [0, 0])
for S, run in SETS:
    f = json.load(open(EXP / "findings" / f"{S}.json")); t = json.load(open(EXP / "findings" / f"{S}.truth.json")); m = json.load(open(EXP / "findings" / f"{S}.match.json"))
    usage = (EXP / "runs" / f"{run}.usage.md").read_text()
    cost = sum(float(x) for x in re.findall(r"\| (?:review|blind-spot|validation|dedup|perspective_selection) \| \S+ \| [\d,]+ \| [\d,]+ \| [\d,]+ \| [\d,]+ \| [\d,]+ \| \$([\d.]+) \| \S+ \|", usage))
    ta = EXP / "findings" / f"{S}.truth.adjudicated.json"
    data[S] = (run, f, t, m, cost)
    adj[S] = json.load(open(ta)) if ta.exists() else None
    for x in f:
        c = m[x["id"]]["cluster"]; src = t[x["id"]]["source"]
        if c is not None and src.startswith("verified"):
            r, n = map(int, src.split(":")[1].split("/")); pool[c][0] += r; pool[c][1] += n
def truth(mode, S, x):
    run, f, t, m, cost = data[S]; tt = t[x["id"]]; c = m[x["id"]]["cluster"]
    if mode == "A": return tt["is_real"]
    if mode in "EF":
        at = adj[S][x["id"]]
        return at["is_real"] and (mode == "E" or at["severity"] in ("must_fix", "should_fix"))
    if mode == "D": return tt["is_real"] and tt["severity"] in ("must_fix", "should_fix")
    if mode == "B":
        if c is None: return tt["is_real"]
        r, n = pool[c]; return r * 2 > n
    if mode == "C":
        k = reg.get(c) if c is not None else None
        if k and k["n_verified"] >= 2 and k["n_real"] * 2 != k["n_verified"]: return k["n_real"] * 2 > k["n_verified"]
        return tt["is_real"]
out = ["# Truth sensitivity of the arm ranking", "", __doc__.strip().replace("\n", "  \n"), ""]
for mode in ("ABCDEF" if all(adj.values()) else "ABCD"):
    out += [f"## {mode}", "", "| arm | real per run | posted real per run | posted noise per run | validator precision | validator recall | $ per real (reviewer side) | $ per posted real |", "| --- | ---: | ---: | ---: | --- | --- | ---: | ---: |"]
    arms = defaultdict(list)
    for S, run in SETS: arms[run.rsplit("-", 1)[0]].append(S)
    for arm, sets in arms.items():
        real = kr = kn = dr = 0; cost = 0.0
        for S in sets:
            run, f, t, m, c = data[S]; cost += c
            for x in f:
                r = truth(mode, S, x); k = x["is_valid"]
                real += r; kr += r and k; kn += (not r) and k; dr += r and not k
        n = len(sets)
        pct = lambda a, b: f"{a}/{b} ({a / b:.0%})" if b else "–"
        out.append(f"| {ARM[arm]} | {real / n:.1f} | {kr / n:.1f} | {kn / n:.1f} | {pct(kr, kr + kn)} | {pct(kr, kr + dr)} | {('$%.2f' % (cost / real)) if real else '–'} | {('$%.2f' % (cost / kr)) if kr else '–'} |")
    out.append("")
text = "\n".join(out); (EXP / "findings" / "SENSITIVITY.md").write_text(text + "\n"); print(text)
