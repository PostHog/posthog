#!/usr/bin/env python3
"""Generate the ingestion-batch perf workload + a correctness oracle.

The workload models a non-trivial per-event Hog function: read the event's numeric series,
run it through several arraySort/arrayReverse passes (real O(n log n) CPU per event), and
combine with a scalar. It uses only ops the Rust VM already implements, so all three perf
modes (pure Node, pure Rust, Rust-from-Node FFI) run the identical bytecode.

Events are produced by a deterministic formula (below) so every harness/language generates the
*same* events without shipping a big fixture. This script emits:
  - tests/static/perf_program.json    the compiled program bytecode
  - tests/static/perf_oracle.json     reference results for the first N events (correctness check)

Run (needs re2 + pytz):
  PYTHONPATH=.:common <venv>/bin/python rust/common/hogvm/scripts/gen_perf_workload.py
"""
import json
import os
import sys

CALL_GLOBAL = 2
GET_GLOBAL = 1
PLUS = 6
STRING, INTEGER, ARRAY = 32, 33, 43

# Must stay in lockstep with the Rust harness (benches/ingestion.rs) and the Node harness.
SERIES_LEN = 128
SORT_PASSES = 8
ORACLE_EVENTS = 16


def make_event(e):
    """Deterministic event generator — replicate exactly in every harness."""
    series = [((e * 131 + i * 977) % 1000) for i in range(SERIES_LEN)]
    k = e % 257
    return {"series": series, "k": k}


class Global:
    def __init__(self, chain):
        self.chain = chain


class Call:
    def __init__(self, name, args):
        self.name = name
        self.args = args


def emit(node, out):
    if isinstance(node, Global):
        for key in reversed(node.chain):  # leaf pushed first (compiler order)
            out += [STRING, key]
        out += [GET_GLOBAL, len(node.chain)]
    elif isinstance(node, Call):
        for a in node.args:
            emit(a, out)
        out += [CALL_GLOBAL, node.name, len(node.args)]
    elif isinstance(node, int):
        out += [INTEGER, node]
    else:
        raise TypeError(node)


def build_program():
    series = Global(["series"])
    for _ in range(SORT_PASSES):
        series = Call("arraySort", [Call("arrayReverse", [series])])
    expr = Call("length", [series])  # length(...) + k
    out = ["_H", 1]
    emit(expr, out)
    emit(Global(["k"]), out)
    out += [PLUS]
    return out


def main():
    sys.path.insert(0, os.getcwd())
    from common.hogvm.python.execute import execute_bytecode

    program = build_program()

    oracle = []
    for e in range(ORACLE_EVENTS):
        res = execute_bytecode(program, globals=make_event(e))
        oracle.append(res.result)

    static = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "tests", "static"))
    os.makedirs(static, exist_ok=True)
    with open(os.path.join(static, "perf_program.json"), "w") as f:
        json.dump(program, f)
        f.write("\n")
    with open(os.path.join(static, "perf_oracle.json"), "w") as f:
        json.dump(
            {"series_len": SERIES_LEN, "sort_passes": SORT_PASSES, "oracle_events": ORACLE_EVENTS, "results": oracle},
            f,
            indent=2,
        )
        f.write("\n")

    print(f"program: {len(program)} tokens, {SORT_PASSES} sort passes over {SERIES_LEN}-element series")
    print(f"oracle results (first {ORACLE_EVENTS} events): {oracle}")


if __name__ == "__main__":
    main()
