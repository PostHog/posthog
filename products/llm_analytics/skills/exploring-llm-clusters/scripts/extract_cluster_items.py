"""Extract the items of one cluster in rank order (closest-to-centroid first).

Usage:
    CLUSTER_ID=0 python3 extract_cluster_items.py <result_file>
    CLUSTER_ID=-1 python3 extract_cluster_items.py <result_file>   # noise cluster
    CLUSTER_ID=0 LIMIT=10 python3 extract_cluster_items.py <file>

Prints:
    <rank>  <item_key>  trace=<trace_id> [gen=<gen_id>]  dist=<d>  ts=<iso>

For trace-level clusters, item_key == trace_id.
For generation-level clusters, item_key is the $ai_generation event UUID; the
parent trace is reported as trace=<trace_id>.

The "noise" cluster (CLUSTER_ID=-1) is sorted so that rank 0 = most anomalous
(highest minimum distance to any centroid).
"""

import os
import sys

from print_clusters import load_result_file, parse_result


def main():
    if len(sys.argv) < 2:
        print("Usage: CLUSTER_ID=<id> python3 extract_cluster_items.py <result_file>")
        sys.exit(1)

    cluster_id_env = os.environ.get("CLUSTER_ID")
    if cluster_id_env is None:
        print("Set CLUSTER_ID env var (e.g. CLUSTER_ID=0, or -1 for noise)")
        sys.exit(1)

    try:
        target_id = int(cluster_id_env)
    except ValueError:
        print(f"CLUSTER_ID must be an integer, got {cluster_id_env!r}")
        sys.exit(1)

    limit = int(os.environ.get("LIMIT", "0"))  # 0 = all

    data = load_result_file(sys.argv[1])
    clusters, _, _ = parse_result(data)
    if not clusters:
        print("No clusters in file.")
        sys.exit(1)

    match = next((c for c in clusters if c.get("cluster_id") == target_id), None)
    if match is None:
        ids = sorted({c.get("cluster_id") for c in clusters})
        print(f"No cluster with id={target_id}. Available: {ids}")
        sys.exit(1)

    traces = match.get("traces", {})
    ranked = sorted(traces.items(), key=lambda t: t[1].get("rank", 999))
    if limit:
        ranked = ranked[:limit]

    bar = "=" * 80
    print(f"\n{bar}")
    print(f"  Cluster {target_id}: {match.get('title', '?')}")
    print(f"  Size: {match.get('size', '?')} | showing {len(ranked)} items")
    print(bar)

    for key, info in ranked:
        rank = info.get("rank", "?")
        dist = info.get("distance_to_centroid")
        dist_str = f"{dist:.4f}" if isinstance(dist, (int, float)) else "?"
        trace_id = info.get("trace_id", key)
        gen_id = info.get("generation_id")
        ts = info.get("timestamp", "?")
        tag = f"gen={gen_id} trace={trace_id}" if gen_id else f"trace={trace_id}"
        print(f"  #{rank:>4}  {tag}  dist={dist_str}  ts={ts}")


if __name__ == "__main__":
    main()
