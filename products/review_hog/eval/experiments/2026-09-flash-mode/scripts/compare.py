"""Cross-arm comparison + cluster consistency. Usage: python scripts/compare.py SET=run [SET=run ...]
Prints (and writes findings/COMPARE.md): per-set table, per-arm means, cluster consistency (fresh votes vs August registry).
"""
import json, os, re, sys
from collections import defaultdict
from pathlib import Path
EXP = Path(__file__).resolve().parent.parent
reg = {c["cluster"]: c for c in json.load(open(EXP / "known_clusters.json"))}
ARM = {"glm-high": "GLM 5.3 Flash @ high", "luna-low": "GPT 5.6 Luna @ low", "sol-low": "GPT 5.6 Sol @ low"}
rows, votes_by_cluster, arm_rows = [], defaultdict(list), defaultdict(list)
for spec in sys.argv[1:]:
    S, run = spec.split("=")
    arm = run.rsplit("-", 1)[0]
    findings = json.load(open(EXP / "findings" / f"{S}.json")); truth = json.load(open(EXP / "findings" / f"{S}.{os.environ.get('TRUTH', 'truth')}.json")); match = json.load(open(EXP / "findings" / f"{S}.match.json"))
    dump = (EXP / "runs" / f"{run}.md").read_text(); usage = (EXP / "runs" / f"{run}.usage.md").read_text()
    wall = int(re.search(r"Wall-clock:\*\* (\d+)s", dump).group(1)) / 60
    review_stage = re.search(r"Review stage total[^:]*:\*\* (\d+)m (\d+)s", dump)
    review_min = int(review_stage.group(1)) + int(review_stage.group(2)) / 60 if review_stage else None
    fun = re.search(r"\| (\d+) \| (\d+) \| (\d+) \| (\d+) \| (\d+) \|\n\n- \*\*review units", dump)
    raw, dedup, passed = (int(fun.group(3)), int(fun.group(4)), int(fun.group(5))) if fun else (None,) * 3
    cost = {}
    for line in usage.splitlines():
        m = re.match(r"\| (\S+) \| (\S+) \| ([\d,]+) \| [\d,]+ \| [\d,]+ \| [\d,]+ \| [\d,]+ \| \$([\d.]+) \| (\S+) \|", line)
        if m and m.group(1) not in ("stage", "capture-probe"): cost[m.group(1)] = float(m.group(4))
    total = sum(cost.values())
    kr = kn = dr = dn = 0; reals = set(); real_clusters = set(); new_real = 0; unscored = 0
    for f in findings:
        t = truth.get(f["id"])
        if not t: unscored += 1; continue
        real, kept = bool(t["is_real"]), bool(f["is_valid"])
        kr += kept and real; kn += kept and not real; dr += (not kept) and real; dn += (not kept) and not real
        c = (match.get(f["id"]) or {}).get("cluster")
        if real:
            reals.add(f["id"]); (real_clusters.add(c) if c is not None else None); new_real += c is None
        if c is not None and t.get("source", "").startswith("verified"):
            votes_by_cluster[c].append((S, f["id"], real, t["source"].split(":")[1]))
    sev = defaultdict(int)
    for fid in reals: sev[truth[fid]["severity"]] += 1
    n = len(findings) - unscored
    r = dict(S=S, run=run, arm=arm, wall=wall, review_min=review_min, raw=raw, dedup=dedup, kept=passed, judged=n, real=len(reals),
             real_clusters=len(real_clusters), new_real=new_real, must=sev["must_fix"], should=sev["should_fix"], consider=sev["consider"],
             kr=kr, kn=kn, dr=dr, dn=dn, cost=total, review_cost=cost.get("review", 0) + cost.get("blind-spot", 0), val_cost=cost.get("validation", 0),
             cost_per_real=(total / len(reals)) if reals else None, unscored=unscored)
    rows.append(r); arm_rows[arm].append(r)
pct = lambda a, b: f"{a}/{b} ({a / b:.0%})" if b else "–"
out = ["# Cross-arm comparison (frozen PR 75215, clean room, same model in both seats)", "",
       "| set | arm | wall min | review-stage min | raw→dedup→kept | real (post-dedup) | real clusters | must/should/consider | kept real (precision) | real kept (recall) | not-real dropped | total $ | review $ | validation $ | $ per real |",
       "| --- | --- | ---: | ---: | --- | --- | ---: | --- | --- | --- | --- | ---: | ---: | ---: | ---: |"]
for r in rows:
    out.append(f"| {r['S']} ({r['run']}) | {ARM.get(r['arm'], r['arm'])} | {r['wall']:.0f} | {('%.0f' % r['review_min']) if r['review_min'] is not None else '–'} | {r['raw']}→{r['dedup']}→{r['kept']} | {pct(r['real'], r['judged'])} | {r['real_clusters']} (+{r['new_real']} new) | {r['must']}/{r['should']}/{r['consider']} | {pct(r['kr'], r['kr'] + r['kn'])} | {pct(r['kr'], r['kr'] + r['dr'])} | {pct(r['dn'], r['kn'] + r['dn'])} | ${r['cost']:.2f} | ${r['review_cost']:.2f} | ${r['val_cost']:.2f} | {('$%.2f' % r['cost_per_real']) if r['cost_per_real'] else '–'} |")
out += ["", "## Per-arm means", "", "| arm | runs | wall min | total $ | real per run | real clusters per run | must_fix per run | validator precision | validator recall | $ per real |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | ---: |"]
for arm, rs in arm_rows.items():
    m = lambda k: sum(r[k] for r in rs) / len(rs)
    kr, kn, dr = sum(r["kr"] for r in rs), sum(r["kn"] for r in rs), sum(r["dr"] for r in rs)
    tot_real = sum(r["real"] for r in rs); tot_cost = sum(r["cost"] for r in rs)
    out.append(f"| {ARM.get(arm, arm)} | {len(rs)} | {m('wall'):.0f} | ${m('cost'):.2f} | {m('real'):.1f} | {m('real_clusters'):.1f} | {m('must'):.1f} | {pct(kr, kr + kn)} | {pct(kr, kr + dr)} | {('$%.2f' % (tot_cost / tot_real)) if tot_real else '–'} |")
out += ["", "## Cluster consistency: fresh 3-skeptic verdicts vs the August registry", "", "Only clusters with ≥1 fresh verdict in this experiment. `August` = n_real/n_verified in `known_clusters.json`.", "",
        "| cluster | August | fresh real / fresh total | per-finding votes | issue |", "| ---: | --- | --- | --- | --- |"]
disagree = 0
for c in sorted(votes_by_cluster):
    vs = votes_by_cluster[c]; k = reg[c]; nr = sum(1 for v in vs if v[2])
    if 0 < nr < len(vs): disagree += 1
    out.append(f"| {c} | {k['n_real']}/{k['n_verified']} | {nr}/{len(vs)} | {', '.join(f'{v[1]}={'R' if v[2] else 'n'}({v[3]})' for v in vs)} | {k['issue'][:90].replace('|', '/')} |")
out += ["", f"Clusters where fresh verdicts disagree with each other inside this experiment: {disagree}/{len(votes_by_cluster)}.", ""]
text = "\n".join(out); (EXP / "findings" / ("COMPARE.md" if os.environ.get("TRUTH", "truth") == "truth" else "COMPARE.adjudicated.md")).write_text(text + "\n"); print(text)
