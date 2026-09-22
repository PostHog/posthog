"""Score a served decision model on a labelled suite, with or without the date-facts preprocessor.

    kev-vllm-eval --base-url http://localhost:8000 --suite transfer-v4-development.jsonl --out eval.json
    kev-vllm-eval --base-url http://localhost:8000 --suite transfer-v4-development.jsonl --date-facts --out eval-df.json

A suite is Kev's frozen format: one record per line with `state`, `questions` keyed by id (each with `type`,
`instructions`, `criteria`, `label`, `src`) and `_meta`. Every question becomes one row: correct when the served
argmax is the label. `--date-facts` applies the preprocessor on this side, so one server answers both arms.
"""

import argparse
import json
import sys
import threading
import time
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from kev_vllm.kev_compat import _DATE, question_keys, with_date_facts

REQUEST_FIELDS = ("type", "instructions", "criteria")


def request_of(record: dict, date_facts: bool) -> dict:
    """The /v1/systemone request for a labelled record: the questions without their labels, the state as is or with the
    day counts appended."""
    state = with_date_facts(record["state"]) if date_facts else record["state"]
    questions = {}
    for qid, q in record["questions"].items():
        question = {k: q[k] for k in REQUEST_FIELDS if k in q}
        if q["type"] == "noul" and question.get("criteria") is None:
            question.pop("criteria", None)
        questions[qid] = question
    return {"state": state, "questions": questions}


def label_index(q: dict) -> int:
    keys = question_keys(q["type"], q.get("criteria"))
    return keys.index(q["label"]) if q["type"] == "choice" else int(q["label"])


def mentions_two_dates(state: Any) -> bool:
    return len(set(_DATE.findall(json.dumps(state)))) >= 2


def score_record(record: dict, probabilities_raw: list[list[float]]) -> list[dict]:
    """One row per question: whether the argmax matched the label, and the labels the report groups by."""
    if len(probabilities_raw) != len(record["questions"]):
        raise ValueError(f"{len(probabilities_raw)} rows back for {len(record['questions'])} questions")
    two_dates = mentions_two_dates(record["state"])
    rows = []
    for (qid, q), probs in zip(record["questions"].items(), probabilities_raw, strict=True):
        predicted = max(range(len(probs)), key=probs.__getitem__)
        rows.append(
            {
                "record": record.get("_meta", {}).get("id"),
                "question": qid,
                "task": q.get("src"),
                "type": q["type"],
                "two_dates": two_dates,
                "correct": predicted == label_index(q),
            }
        )
    return rows


def summarize(rows: list[dict]) -> dict:
    def accuracy(subset: list[dict]) -> dict:
        return (
            {"questions": len(subset), "accuracy": round(sum(r["correct"] for r in subset) / len(subset), 4)}
            if subset
            else {"questions": 0}
        )

    by_task: dict[str, list[dict]] = defaultdict(list)
    by_type: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_task[str(row["task"])].append(row)
        by_type[row["type"]].append(row)
    return {
        "overall": accuracy(rows),
        "states_with_two_dates": accuracy([r for r in rows if r["two_dates"]]),
        "by_type": {k: accuracy(v) for k, v in sorted(by_type.items())},
        "by_task": {k: accuracy(v) for k, v in sorted(by_task.items())},
    }


def post_json(url: str, payload: dict, timeout: int) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected the URL comes from the --base-url flag
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def evaluate(records: list[dict], base_url: str, model: str, date_facts: bool, concurrency: int, timeout: int) -> dict:
    rows: list[dict] = []
    failures: list[dict] = []
    lock = threading.Lock()
    started = time.perf_counter()

    def one(record: dict) -> None:
        payload = {"model": model, "data": request_of(record, date_facts)}
        try:
            response = post_json(f"{base_url.rstrip('/')}/pooling", payload, timeout)
            scored = score_record(record, response["data"]["probabilities_raw"])
        except Exception as error:
            with lock:
                failures.append({"record": record.get("_meta", {}).get("id"), "error": str(error)[:200]})
            return
        with lock:
            rows.extend(scored)

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        list(pool.map(one, records))
    report = summarize(rows)
    report.update(
        {
            "date_facts": date_facts,
            "records": len(records),
            "failed_records": len(failures),
            "failures": failures[:20],
            "seconds": round(time.perf_counter() - started, 1),
        }
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--suite", type=Path, required=True, help="labelled records, one JSON object per line")
    parser.add_argument("--model", default="kev-4b")
    parser.add_argument("--date-facts", action="store_true", help="append day counts between absolute dates to every state")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--concurrency", type=int, default=32)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--out", type=Path, help="write the full report here; the summary always prints")
    args = parser.parse_args()
    with args.suite.open() as f:
        records = [json.loads(line) for line in f if line.strip()]
    if args.limit:
        records = records[: args.limit]
    report = evaluate(records, args.base_url, args.model, args.date_facts, args.concurrency, args.timeout)
    if args.out:
        args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {k: report[k] for k in ("date_facts", "records", "failed_records", "seconds", "overall", "states_with_two_dates", "by_type")},
            indent=2,
        ),
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
