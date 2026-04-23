"""Side-by-side comparison of two clustering runs.

Compares by cluster title (fuzzy-matched as case-insensitive substring containment
after normalisation) and reports:

  - stable clusters (similar titles, with size delta)
  - clusters only in A (disappeared)
  - clusters only in B (appeared)
  - total item count delta and noise cluster size delta

Usage:
    python3 diff_runs.py <run_a.json> <run_b.json>
"""

import sys

from print_clusters import load_result_file, parse_result


def _normalize(s: str) -> str:
    return " ".join((s or "").lower().split())


def _title_match(a: str, b: str) -> bool:
    a_n, b_n = _normalize(a), _normalize(b)
    if not a_n or not b_n:
        return False
    if a_n == b_n:
        return True
    # Substring match either direction — catches minor wording drift in LLM labels
    if len(a_n) > 6 and len(b_n) > 6 and (a_n in b_n or b_n in a_n):
        return True
    return False


def main():
    if len(sys.argv) < 3:
        print("Usage: python3 diff_runs.py <run_a.json> <run_b.json>")
        sys.exit(1)

    clusters_a, meta_a, _ = parse_result(load_result_file(sys.argv[1]))
    clusters_b, meta_b, _ = parse_result(load_result_file(sys.argv[2]))

    if not clusters_a or not clusters_b:
        print("Both files must contain a clusters array.")
        sys.exit(1)

    bar = "=" * 80
    print(f"\n{bar}")
    print(f"  RUN A: {meta_a.get('run_id', sys.argv[1])}")
    print(f"         items: {meta_a.get('total_items', '?')}  clusters: {len(clusters_a)}")
    print(f"  RUN B: {meta_b.get('run_id', sys.argv[2])}")
    print(f"         items: {meta_b.get('total_items', '?')}  clusters: {len(clusters_b)}")
    print(bar)

    # Skip noise for title matching — compare separately at the end
    regular_a = [c for c in clusters_a if c.get("cluster_id", -1) != -1]
    regular_b = [c for c in clusters_b if c.get("cluster_id", -1) != -1]

    matched_b_ids: set[int] = set()
    stable: list[tuple[dict, dict]] = []
    only_in_a: list[dict] = []

    for ca in regular_a:
        partner = None
        for cb in regular_b:
            if cb.get("cluster_id") in matched_b_ids:
                continue
            if _title_match(ca.get("title", ""), cb.get("title", "")):
                partner = cb
                break
        if partner is not None:
            stable.append((ca, partner))
            matched_b_ids.add(partner.get("cluster_id"))
        else:
            only_in_a.append(ca)

    only_in_b = [c for c in regular_b if c.get("cluster_id") not in matched_b_ids]

    print("\n  STABLE CLUSTERS (title match)")
    if not stable:
        print("    (none)")
    for ca, cb in sorted(stable, key=lambda p: -p[1].get("size", 0)):
        delta = cb.get("size", 0) - ca.get("size", 0)
        title = (cb.get("title") or ca.get("title") or "?")[:60]
        print(f"    {ca.get('size', 0):>5} → {cb.get('size', 0):>5}  ({delta:+d})  {title}")

    print("\n  ONLY IN A (disappeared)")
    if not only_in_a:
        print("    (none)")
    for c in sorted(only_in_a, key=lambda c: -c.get("size", 0)):
        print(f"    -{c.get('size', 0):>4}  {(c.get('title') or '?')[:70]}")

    print("\n  ONLY IN B (appeared)")
    if not only_in_b:
        print("    (none)")
    for c in sorted(only_in_b, key=lambda c: -c.get("size", 0)):
        print(f"    +{c.get('size', 0):>4}  {(c.get('title') or '?')[:70]}")

    noise_a = next((c for c in clusters_a if c.get("cluster_id") == -1), None)
    noise_b = next((c for c in clusters_b if c.get("cluster_id") == -1), None)
    if noise_a or noise_b:
        size_a = noise_a.get("size", 0) if noise_a else 0
        size_b = noise_b.get("size", 0) if noise_b else 0
        delta = size_b - size_a
        print(f"\n  NOISE: {size_a} → {size_b}  ({delta:+d})")


if __name__ == "__main__":
    main()
