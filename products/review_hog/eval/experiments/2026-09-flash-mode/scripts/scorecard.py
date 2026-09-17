"""Scorecard for one set: reviewer-side real rate, validator confusion, coverage, cost per stage/verdict, wall time.
    python scripts/scorecard.py <SET> <run-name>      # writes findings/<SET>.score.md, prints it
Reads findings/<SET>.json (parsed dump), findings/<SET>.truth.json, findings/<SET>.match.json, runs/<run>.usage.md, runs/<run>.md.
"""
import json, os, re, sys
from pathlib import Path
EXP = Path(__file__).resolve().parent.parent
S, run = sys.argv[1], sys.argv[2]
findings = json.load(open(EXP / "findings" / f"{S}.json"))
truth = json.load(open(EXP / "findings" / f"{S}.{os.environ.get('TRUTH', 'truth')}.json"))
match = json.load(open(EXP / "findings" / f"{S}.match.json"))
dump = (EXP / "runs" / f"{run}.md").read_text()
usage = (EXP / "runs" / f"{run}.usage.md").read_text()
wall = re.search(r"Wall-clock:\*\* (\d+)s \(([\d.]+) min\)", dump)
funnel = re.search(r"\| chunks \| review units \| raw issues \| after dedup \| passed validator \|\n\|[-| ]+\|\n\| (\d+) \| (\d+) \| (\d+) \| (\d+) \| (\d+) \|", dump)
chunks, units, raw, dedup, passed = (funnel.groups() if funnel else ("?",) * 5)
# stage-family cost table: | family | model | calls | input | cache read | output | reasoning | $ | effort |
cost = {}
model_by_family = {}
for line in usage.splitlines():
    m = re.match(r"\| (\S+) \| (\S+) \| ([\d,]+) \| [\d,]+ \| [\d,]+ \| [\d,]+ \| [\d,]+ \| \$([\d.]+) \| (\S+) \|", line)
    if m and m.group(1) not in ("stage", "---"):
        fam, model, calls, dollars, effort = m.groups()
        if fam == "capture-probe": continue
        cost[fam] = {"model": model, "calls": int(calls.replace(",", "")), "usd": float(dollars), "effort": effort}
        model_by_family[fam] = model
total_usd = sum(v["usd"] for v in cost.values())
review_usd = sum(v["usd"] for k, v in cost.items() if k in ("review", "blind-spot"))
val = cost.get("validation", {"calls": 0, "usd": 0.0})
kr = kn = dr = dn = 0; unscored = []
real_ids, new_real, real_clusters = [], [], set()
for f in findings:
    t = truth.get(f["id"])
    if not t: unscored.append(f["id"]); continue
    real, kept = bool(t["is_real"]), bool(f["is_valid"])
    kr += kept and real; kn += kept and not real; dr += (not kept) and real; dn += (not kept) and not real
    if real:
        real_ids.append(f["id"])
        c = (match.get(f["id"]) or {}).get("cluster")
        (new_real.append(f["id"]) if c is None else real_clusters.add(c))
n = len(findings); scored = n - len(unscored); reals = len(real_ids); kept_total = kr + kn
verdicts = sum(1 for f in findings if f.get("validator"))
pct = lambda a, b: f"{a}/{b} ({a / b:.0%})" if b else "–"
rows = [
    ("run", run), ("wall-clock", f"{wall.group(1)}s ({wall.group(2)} min)" if wall else "?"),
    ("chunks / review units", f"{chunks} / {units}"), ("raw → dedup → kept (validator)", f"{raw} → {dedup} → {passed}"),
    ("findings judged (post-dedup)", f"{n} ({len(unscored)} unscored)"),
    ("real findings (reviewer side)", pct(reals, scored)), ("real clusters found", f"{len(real_clusters)} {sorted(real_clusters)}"),
    ("new real issues (not in registry)", f"{len(new_real)} {new_real}"),
    ("kept that were real (precision)", pct(kr, kept_total)), ("real findings kept (recall)", pct(kr, kr + dr)),
    ("not-real findings dropped", pct(dn, kn + dn)), ("findings with NO verdict", f"{n - verdicts}"),
    ("review + blind-spot cost", f"${review_usd:.2f} ({cost.get('review', {}).get('calls', 0) + cost.get('blind-spot', {}).get('calls', 0)} calls, {model_by_family.get('review', '?')} @ {cost.get('review', {}).get('effort', '?')})"),
    ("validation cost", f"${val['usd']:.2f} ({val['calls']} calls, {model_by_family.get('validation', '?')})"),
    ("cost per verdict", f"${val['usd'] / verdicts:.3f}" if verdicts else "–"),
    ("one-shots (selection + dedup, Sonnet)", f"${sum(v['usd'] for k, v in cost.items() if k in ('perspective_selection', 'dedup')):.2f}"),
    ("TOTAL gateway cost", f"${total_usd:.2f}"),
]
md = [f"# {S} scorecard — {run} (frozen PR 75215, clean room, inline skills)", "", "| | " + S + " |", "| --- | --- |"]
md += [f"| {k} | {v} |" for k, v in rows]
md += ["", "## Per-finding", "", "| id | cluster | real | kept | severity (truth) | prio (validator→) | title |", "| --- | --- | --- | --- | --- | --- | --- |"]
for f in findings:
    t = truth.get(f["id"]) or {}
    c = (match.get(f["id"]) or {}).get("cluster")
    md.append(f"| {f['id']} | {c if c is not None else '–'} | {'yes' if t.get('is_real') else ('no' if t else '?')} | {'yes' if f['is_valid'] else 'no'} | {t.get('severity') or '–'} | {f.get('validator_priority') or f['priority']} | {f['title'][:90].replace('|', '/')} |")
text = "\n".join(md) + "\n"
(EXP / "findings" / f"{S}.{'score' if os.environ.get('TRUTH', 'truth') == 'truth' else 'score.adjudicated'}.md").write_text(text)
print(text)
