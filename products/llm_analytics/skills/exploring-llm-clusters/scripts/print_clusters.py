"""Print a summary of clusters from a clustering run result."""

import json
import sys


def load_result_file(path):
    with open(path) as f:
        raw = json.load(f)
    if isinstance(raw, list) and raw and isinstance(raw[0], dict) and raw[0].get("type") == "text":
        raw = json.loads(raw[0]["text"])
    return raw


def parse_result(raw):
    """Extract clusters array and run metadata from various result shapes."""
    meta: dict[str, str | int | float] = {}
    clusters = []

    # Direct clusters array
    if isinstance(raw, list) and raw and isinstance(raw[0], dict) and "cluster_id" in raw[0]:
        return raw, meta

    # SQL result — look for clusters JSON and metadata columns
    if isinstance(raw, dict) and "results" in raw:
        columns = raw.get("columns", [])
        for row in raw["results"]:
            for i, cell in enumerate(row):
                col_name = columns[i] if i < len(columns) else ""
                # Extract run metadata from known columns
                if isinstance(cell, str) and col_name in (
                    "run_id", "level", "job_id", "job_name",
                    "window_start", "window_end", "total_items",
                ):
                    meta[col_name] = cell
                elif isinstance(cell, (int, float)) and col_name == "total_items":
                    meta[col_name] = cell
                # Find the clusters JSON
                if isinstance(cell, str) and cell.startswith("["):
                    try:
                        parsed = json.loads(cell)
                        if isinstance(parsed, list) and parsed and "cluster_id" in parsed[0]:
                            clusters = parsed
                    except (json.JSONDecodeError, TypeError):
                        continue
    return clusters, meta


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python print_clusters.py <result_file_path>")
        sys.exit(1)

    data = load_result_file(sys.argv[1])
    clusters, meta = parse_result(data)

    if not clusters:
        print("No clusters found in file.")
        sys.exit(1)

    clusters.sort(key=lambda c: c.get("size", 0), reverse=True)

    print(f"\n{'='*80}")
    if meta:
        if meta.get("job_name"):
            print(f"  Job: {meta['job_name']}")
        if meta.get("level"):
            print(f"  Level: {meta['level']}")
        if meta.get("run_id"):
            print(f"  Run: {meta['run_id']}")
        if meta.get("job_id"):
            print(f"  Job ID: {meta['job_id']}")
        if meta.get("window_start") or meta.get("window_end"):
            print(f"  Window: {meta.get('window_start', '?')} → {meta.get('window_end', '?')}")
        if meta.get("total_items"):
            print(f"  Items analyzed: {meta['total_items']}")
        print(f"  ---")
    print(f"  {len(clusters)} clusters, {sum(c.get('size', 0) for c in clusters)} total items")
    print(f"{'='*80}")

    for c in clusters:
        cid = c.get("cluster_id", "?")
        label = "(NOISE/OUTLIERS)" if cid == -1 else ""
        title = c.get("title", f"Cluster {cid}")
        size = c.get("size", 0)
        desc = c.get("description", "")

        print(f"\n  Cluster {cid} {label}")
        print(f"  Title: {title}")
        print(f"  Size:  {size} items")
        if desc:
            print(f"  Desc:  {desc[:200]}{'...' if len(desc) > 200 else ''}")

        # Show top 5 traces by rank
        traces = c.get("traces", {})
        ranked = sorted(traces.items(), key=lambda t: t[1].get("rank", 999))[:5]
        if ranked:
            print(f"  Top traces (by centroid proximity):")
            for tid, info in ranked:
                dist = info.get("distance_to_centroid")
                ts = info.get("timestamp", "?")
                dist_str = f"{dist:.4f}" if isinstance(dist, (int, float)) else "?"
                print(f"    #{info.get('rank', '?'):>3}  {tid}  dist={dist_str}  {ts}")
