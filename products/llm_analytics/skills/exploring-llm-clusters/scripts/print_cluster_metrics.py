"""Print per-cluster aggregate metrics (cost, latency, tokens, errors, sentiment).

Reads from the baked-in `metrics` field that the clustering workflow attaches to
each cluster object. If the field is absent (older runs), this script prints a
message pointing at references/cluster-metrics-sql.md for the on-demand query.

Sorts clusters by total_cost desc; falls back to size desc when costs are missing.
"""

import json
import sys

from print_clusters import load_result_file, parse_result


def fmt_num(v, fmt=".4f", suffix=""):
    if v is None:
        return "-"
    try:
        return f"{v:{fmt}}{suffix}"
    except (ValueError, TypeError):
        return str(v)


def main():
    if len(sys.argv) < 2:
        print("Usage: python print_cluster_metrics.py <result_file_path>")
        sys.exit(1)

    data = load_result_file(sys.argv[1])
    clusters, meta, _ = parse_result(data)
    if not clusters:
        print("No clusters found in file.")
        sys.exit(1)

    has_metrics = any(isinstance(c.get("metrics"), dict) for c in clusters)
    if not has_metrics:
        print("No baked-in `metrics` field on any cluster.")
        print("This run predates the aggregates activity.")
        print("Run the SQL in references/cluster-metrics-sql.md to compute on-demand.")
        sys.exit(0)

    def sort_key(c):
        m = c.get("metrics") or {}
        total = m.get("total_cost")
        return (-(total if total is not None else -1), -c.get("size", 0))

    clusters = sorted(clusters, key=sort_key)

    bar = "=" * 100
    print(f"\n{bar}")
    if meta.get("run_id"):
        print(f"  Run: {meta['run_id']}")
    if meta.get("level"):
        print(f"  Level: {meta['level']}")
    print(bar)
    hdr = f"  {'CID':>4}  {'size':>5}  {'total$':>8}  {'avg$':>8}  {'avg_lat':>8}  {'avg_tok':>8}  {'err_rate':>8}  sentiment  title"
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))

    for c in clusters:
        cid = c.get("cluster_id", "?")
        m = c.get("metrics") or {}
        sentiment = m.get("sentiment") or {}
        sent_str = "-"
        if isinstance(sentiment, dict) and sentiment.get("label"):
            score = sentiment.get("score")
            score_str = f"{score:.2f}" if isinstance(score, (int, float)) else "?"
            sent_str = f"{sentiment['label'][:3]}({score_str})"

        title = (c.get("title") or "").replace("\n", " ")
        if len(title) > 40:
            title = title[:37] + "..."

        err_rate = m.get("error_rate")
        err_str = f"{err_rate*100:.1f}%" if isinstance(err_rate, (int, float)) else "-"

        print(
            f"  {str(cid):>4}  "
            f"{c.get('size', 0):>5}  "
            f"{fmt_num(m.get('total_cost'), '.2f'):>8}  "
            f"{fmt_num(m.get('avg_cost'), '.4f'):>8}  "
            f"{fmt_num(m.get('avg_latency'), '.2f', 's'):>8}  "
            f"{fmt_num(m.get('avg_tokens'), '.0f'):>8}  "
            f"{err_str:>8}  "
            f"{sent_str:>9}  "
            f"{title}"
        )


if __name__ == "__main__":
    main()
