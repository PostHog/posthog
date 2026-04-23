"""Print a summary of clusters from a clustering run result.

Handles result shapes from execute-sql (rows + columns) and raw cluster arrays.
Shows title/description, size, top-ranked items, and a one-line metrics preview
when the event carries baked-in aggregates.
"""

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
    params: dict = {}
    clusters: list = []

    if isinstance(raw, list) and raw and isinstance(raw[0], dict) and "cluster_id" in raw[0]:
        return raw, meta, params

    if isinstance(raw, dict) and "results" in raw:
        columns = raw.get("columns", [])
        for row in raw["results"]:
            for i, cell in enumerate(row):
                col_name = columns[i] if i < len(columns) else ""
                if col_name in (
                    "run_id", "level", "job_id", "job_name",
                    "window_start", "window_end", "total_items",
                ) and isinstance(cell, (str, int, float)):
                    meta[col_name] = cell
                if col_name == "params" and isinstance(cell, str):
                    try:
                        params = json.loads(cell)
                    except (json.JSONDecodeError, TypeError):
                        pass
                if col_name == "clusters" and isinstance(cell, str):
                    try:
                        parsed = json.loads(cell)
                        if isinstance(parsed, list) and parsed and "cluster_id" in parsed[0]:
                            clusters = parsed
                    except (json.JSONDecodeError, TypeError):
                        pass
                # Fallback: scan any string cell that looks like the clusters array
                if not clusters and isinstance(cell, str) and cell.startswith("["):
                    try:
                        parsed = json.loads(cell)
                        if isinstance(parsed, list) and parsed and "cluster_id" in parsed[0]:
                            clusters = parsed
                    except (json.JSONDecodeError, TypeError):
                        continue
    return clusters, meta, params


def fmt_metrics_line(m):
    if not isinstance(m, dict):
        return ""
    parts = []
    if m.get("avg_cost") is not None:
        parts.append(f"avg_cost=${m['avg_cost']:.4f}")
    if m.get("total_cost") is not None:
        parts.append(f"total=${m['total_cost']:.2f}")
    if m.get("avg_latency") is not None:
        parts.append(f"avg_lat={m['avg_latency']:.2f}s")
    if m.get("avg_tokens") is not None:
        parts.append(f"avg_tok={int(m['avg_tokens'])}")
    if m.get("error_rate") is not None:
        parts.append(f"err={m['error_rate']*100:.1f}%")
    sentiment = m.get("sentiment")
    if isinstance(sentiment, dict) and sentiment.get("label"):
        parts.append(f"sent={sentiment['label']}({sentiment.get('score', 0):.2f})")
    return "  ".join(parts)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python print_clusters.py <result_file_path>")
        sys.exit(1)

    data = load_result_file(sys.argv[1])
    clusters, meta, params = parse_result(data)

    if not clusters:
        print("No clusters found in file.")
        sys.exit(1)

    clusters.sort(key=lambda c: c.get("size", 0), reverse=True)

    bar = "=" * 80
    print(f"\n{bar}")
    if meta.get("job_name"):
        print(f"  Job:     {meta['job_name']}")
    if meta.get("level"):
        print(f"  Level:   {meta['level']}")
    if meta.get("run_id"):
        print(f"  Run:     {meta['run_id']}")
    if meta.get("window_start") or meta.get("window_end"):
        print(f"  Window:  {meta.get('window_start', '?')} → {meta.get('window_end', '?')}")
    if meta.get("total_items") is not None:
        print(f"  Items:   {meta['total_items']} analyzed")
    if params:
        method = params.get("clustering_method", "?")
        ndim = params.get("dimensionality_reduction_ndims")
        norm = params.get("embedding_normalization")
        print(f"  Params:  method={method} ndim={ndim} norm={norm}")
    print(f"  ---")
    print(f"  {len(clusters)} clusters, {sum(c.get('size', 0) for c in clusters)} total items")
    print(bar)

    for c in clusters:
        cid = c.get("cluster_id", "?")
        label = " (NOISE/OUTLIERS)" if cid == -1 else ""
        title = c.get("title", f"Cluster {cid}")
        size = c.get("size", 0)
        desc = c.get("description", "")

        print(f"\n  Cluster {cid}{label}")
        print(f"  Title: {title}")
        print(f"  Size:  {size} items")
        if desc:
            snippet = desc[:300]
            print(f"  Desc:  {snippet}{'...' if len(desc) > 300 else ''}")

        metrics_line = fmt_metrics_line(c.get("metrics"))
        if metrics_line:
            print(f"  Metrics: {metrics_line}")

        traces = c.get("traces", {})
        ranked = sorted(traces.items(), key=lambda t: t[1].get("rank", 999))[:5]
        if ranked:
            print(f"  Top items (by centroid proximity):")
            for tid, info in ranked:
                dist = info.get("distance_to_centroid")
                ts = info.get("timestamp", "?")
                dist_str = f"{dist:.4f}" if isinstance(dist, (int, float)) else "?"
                trace_id = info.get("trace_id", tid)
                gen_id = info.get("generation_id")
                marker = f"gen={gen_id} trace={trace_id}" if gen_id else f"trace={trace_id}"
                print(f"    #{info.get('rank', '?'):>3}  {marker}  dist={dist_str}  {ts}")
