#!/usr/bin/env python3
"""Generate the per-STL parity oracle for the Rust HogVM.

For every case below it builds bytecode for ``print(fn(args))``, runs it through the
*reference* Python HogVM (the compliant implementation per common/hogvm/README.md), and
records the bytecode + captured output into tests/static/stl_oracle.json. The Rust parity
test (tests/stl_parity.rs) replays that exact bytecode and asserts it produces the same
output — so each STL function gets a focused, reference-checked parity test.

Run (needs re2 + pytz; see PARITY_LOOP.md):
    PYTHONPATH=.:common <venv>/bin/python rust/common/hogvm/scripts/gen_stl_oracle.py
"""
import json
import os
import sys

# Opcodes we emit (subset of common/hogvm/typescript/src/operation.ts).
CALL_GLOBAL = 2
TRUE, FALSE, NULL, STRING, INTEGER, FLOAT = 29, 30, 31, 32, 33, 34
DICT, ARRAY = 42, 43


class Call:
    """A nested STL call used as an argument, e.g. C('toDateTime', [1700000000])."""

    def __init__(self, name, args):
        self.name = name
        self.args = args


def emit_value(v, out):
    # bool must be checked before int (bool is an int subclass in Python)
    if v is None:
        out.append(NULL)
    elif v is True:
        out.append(TRUE)
    elif v is False:
        out.append(FALSE)
    elif isinstance(v, Call):
        for a in v.args:
            emit_value(a, out)
        out += [CALL_GLOBAL, v.name, len(v.args)]
    elif isinstance(v, str):
        out += [STRING, v]
    elif isinstance(v, int):
        out += [INTEGER, v]
    elif isinstance(v, float):
        out += [FLOAT, v]
    elif isinstance(v, list):
        for e in v:  # args/elements push left-to-right (compiler v1 order)
            emit_value(e, out)
        out += [ARRAY, len(v)]
    elif isinstance(v, dict):
        for k, val in v.items():
            emit_value(k, out)
            emit_value(val, out)
        out += [DICT, len(v)]
    else:
        raise TypeError(f"unsupported arg type {type(v)}: {v!r}")


def build_program(name, args):
    out = ["_H", 1]
    for a in args:
        emit_value(a, out)
    out += [CALL_GLOBAL, name, len(args)]
    out += [CALL_GLOBAL, "print", 1]
    return out


def C(name, *args):
    return Call(name, list(args))


# A representative, deterministic case per STL function: (function, [args], match-mode).
# match-mode "exact" asserts byte-identical output; "smoke" only asserts the Rust VM runs it
# without error (for non-deterministic functions like now()/randomFloat()).
DT = lambda: C("toDateTime", "2021-01-01 12:34:56")  # noqa: E731 - reused datetime arg
CASES = {
    # strings
    "concat": [(["a", "b", "c"], "exact"), ([1, None, "x"], "exact")],
    "lower": [(["HeLLo"], "exact")],
    "upper": [(["HeLLo"], "exact")],
    "reverse": [(["abc"], "exact")],
    "trim": [(["  hi  "], "exact")],
    "trimLeft": [(["  hi  "], "exact")],
    "trimRight": [(["  hi  "], "exact")],
    "substring": [(["hello world", 1, 5], "exact")],
    "replaceOne": [(["hello", "l", "L"], "exact")],
    "replaceAll": [(["hello", "l", "L"], "exact")],
    "splitByString": [(["," , "a,b,c"], "exact")],
    "startsWith": [(["hello", "he"], "exact")],
    "position": [(["hello", "l"], "exact")],
    "positionCaseInsensitive": [(["heLLo", "l"], "exact")],
    "encodeURLComponent": [(["a b&c=d"], "exact")],
    "decodeURLComponent": [(["a%20b%26c"], "exact")],
    "base64Encode": [(["hello"], "exact")],
    "base64Decode": [(["aGVsbG8="], "exact")],
    "tryDecodeURLComponent": [(["a%20b"], "exact")],
    # collections / generic
    "length": [(["hello"], "exact"), ([[1, 2, 3]], "exact")],
    "empty": [([""], "exact"), ([[]], "exact"), ([0], "exact")],
    "notEmpty": [(["x"], "exact"), ([[]], "exact")],
    "keys": [([{"a": 1, "b": 2}], "exact")],
    "values": [([{"a": 1, "b": 2}], "exact")],
    "has": [([[1, 2, 3], 2], "exact")],
    "indexOf": [([[10, 20, 30], 20], "exact")],
    "arrayPushBack": [([[1, 2], 3], "exact")],
    "arrayPushFront": [([[1, 2], 0], "exact")],
    "arrayPopBack": [([[1, 2, 3]], "exact")],
    "arrayPopFront": [([[1, 2, 3]], "exact")],
    "arraySort": [([[3, 1, 2]], "exact")],
    "arrayReverse": [([[1, 2, 3]], "exact")],
    "arrayReverseSort": [([[1, 3, 2]], "exact")],
    "arrayStringConcat": [([[1, 2, 3], "-"], "exact")],
    "tuple": [([1, "a", True], "exact")],
    "range": [([5], "exact"), ([2, 6], "exact")],
    # numbers / coercion
    "round": [([2.5], "exact"), ([2.4], "exact")],
    "floor": [([2.9], "exact")],
    "min2": [([3, 5], "exact")],
    "max2": [([3, 5], "exact")],
    "toInt": [(["42"], "exact"), ([3.9], "exact")],
    "toFloat": [(["3.14"], "exact")],
    "toString": [([42], "exact"), ([True], "exact"), ([[1, "2", 3]], "exact"), ([None], "exact")],
    "typeof": [([1], "exact"), (["x"], "exact"), ([[1]], "exact"), ([{"a": 1}], "exact"), ([None], "exact")],
    # null handling
    "ifNull": [([None, "x"], "exact"), (["y", "x"], "exact")],
    "coalesce": [([None, None, 3], "exact")],
    "assumeNotNull": [([5], "exact")],
    "isNull": [([None], "exact"), ([1], "exact")],
    "isNotNull": [([None], "exact"), ([1], "exact")],
    # json
    "jsonStringify": [([{"a": 1, "b": [2, 3]}], "exact")],
    "jsonParse": [(['{"a":1,"b":[2,3]}'], "exact")],
    "isValidJSON": [(['{"a":1}'], "exact"), (["nope"], "exact")],
    "JSONHas": [([{"a": 1}, "a"], "exact"), ([{"a": 1}, "z"], "exact")],
    "JSONLength": [([{"a": 1, "b": 2}], "exact")],
    "JSONExtractString": [(['{"a":"x"}', "a"], "exact")],
    "JSONExtractInt": [(['{"a":7}', "a"], "exact")],
    "JSONExtractFloat": [(['{"a":1.5}', "a"], "exact")],
    "JSONExtractBool": [(['{"a":true}', "a"], "exact")],
    "JSONExtract": [(['{"a":{"b":7}}', "a", "b"], "exact")],
    "JSONExtractArrayRaw": [(["[1,2,3]"], "exact")],
    # regex / search
    "match": [(["fish", "fi"], "exact")],
    "extractRegex": [(["abc123", r"\d+"], "exact")],
    "multiSearchAnyCaseInsensitive": [(["Hello World", ["foo", "world"]], "exact")],
    # crypto (deterministic)
    "md5Hex": [(["hello"], "exact")],
    "md5": [(["hello", "hex"], "exact")],
    "sha256Hex": [(["hello"], "exact")],
    "sha256": [(["hello", "hex"], "exact")],
    "sha256HmacChain": [([["key", "data"]], "exact")],
    "sha256HmacChainHex": [([["key", "data"]], "exact")],
    "toUUID": [(["123e4567-e89b-12d3-a456-426614174000"], "exact")],
    # net
    "isIPAddressInRange": [(["192.168.1.5", "192.168.1.0/24"], "exact"), (["10.0.0.1", "192.168.1.0/24"], "exact")],
    # dates (deterministic inputs)
    "toDateTime": [(["2021-01-01 12:34:56"], "exact"), ([1700000000], "exact")],
    "toDate": [(["2021-06-15"], "exact")],
    "fromUnixTimestamp": [([1700000000], "exact")],
    "toUnixTimestamp": [([DT()], "exact")],
    "toYear": [([DT()], "exact")],
    "toMonth": [([DT()], "exact")],
    "toStartOfDay": [([DT()], "exact")],
    "toStartOfMonth": [([DT()], "exact")],
    "formatDateTime": [([DT(), "%Y-%m-%d"], "exact")],
    "dateDiff": [(["day", DT(), C("toDateTime", "2021-01-05 12:34:56")], "exact")],
    "dateAdd": [(["day", 3, DT()], "exact")],
    "addDays": [([DT(), 3], "exact")],
    "dateTrunc": [(["day", DT()], "exact")],
    "toStartOfHour": [([DT()], "exact")],
    "toStartOfWeek": [([DT()], "exact")],
    "toTimeZone": [([DT(), "America/New_York"], "exact")],
    "toYYYYMM": [([DT()], "exact")],
    "toUnixTimestampMilli": [([DT()], "exact")],
    "fromUnixTimestampMilli": [([1700000000123], "exact")],
    "toIntervalDay": [([3], "exact")],
    "toIntervalHour": [([2], "exact")],
    "toIntervalMinute": [([30], "exact")],
    "toIntervalMonth": [([1], "exact")],
    "sortableSemver": [(["1.20.3"], "exact")],
    # exceptions (constructors -> printable error objects)
    "Error": [(["boom"], "exact")],
    "HogError": [(["MyError", "boom"], "exact")],
    "RetryError": [(["retry me"], "exact")],
    "NotImplementedError": [(["nope"], "exact")],
    # non-deterministic -> smoke only
    "now": [([], "smoke")],
    "today": [([], "smoke")],
    "randomFloat": [([], "smoke")],
    "generateUUIDv4": [([], "smoke")],
}


def main():
    sys.path.insert(0, os.getcwd())
    from common.hogvm.python.execute import execute_bytecode
    from common.hogvm.python.stl import STL  # authoritative native function list
    from common.hogvm.python.stl.bytecode import BYTECODE_STL  # hog-bytecode STL functions

    all_stl = set(STL.keys()) | set(BYTECODE_STL.keys())

    entries = []
    ref_errors = []
    for name, cases in CASES.items():
        for label_idx, (args, match) in enumerate(cases):
            bytecode = build_program(name, args)
            label = f"{name}#{label_idx}"
            try:
                res = execute_bytecode(bytecode)
                expected = "\n".join(res.stdout)
                entries.append(
                    {"fn": name, "label": label, "match": match, "bytecode": bytecode, "expected": expected}
                )
            except Exception as e:  # a reference error means a bad case to fix, not a parity result
                ref_errors.append((label, f"{type(e).__name__}: {e}"))

    covered = {e["fn"] for e in entries}
    uncovered = sorted(all_stl - covered - {"sleep", "print"})  # sleep/print are infra
    out_path = os.path.join(os.path.dirname(__file__), "..", "tests", "static", "stl_oracle.json")
    out_path = os.path.normpath(out_path)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump({"entries": entries, "uncovered": uncovered}, f, indent=2)
        f.write("\n")

    print(f"wrote {len(entries)} cases for {len(covered)} STL functions -> {out_path}")
    print(f"STL functions total: {len(all_stl)} | covered: {len(covered)} | uncovered: {len(uncovered)}")
    if ref_errors:
        print(f"\n!! {len(ref_errors)} cases the REFERENCE rejected (fix these cases):")
        for label, err in ref_errors:
            print(f"   {label}: {err}")
    if uncovered:
        print(f"\nuncovered (no case yet): {', '.join(uncovered)}")


if __name__ == "__main__":
    main()
