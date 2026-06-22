#!/usr/bin/env python3
"""Decode and analyse a session-recording export zip.

An export (see the `exporting-session-recordings` skill) bundles the recording's
raw v2 storage blocks under `data/` plus ClickHouse metadata. The blocks are the
RAW S3 objects: each is snappy-compressed, written at its byte offset and
zero-padded (the exporter fetches with decompress=False). Inside, once
snappy-decompressed, each block is JSONL of `["windowId", {event}]` rows; events
tagged `cv: "2024-10"` have their heavy DOM fields individually gzip-compressed
and stored as binary-in-JSON strings (fflate `strFromU8(gzipSync(...), true)`).

So fully decoding is two layers: snappy (whole block) then gzip (per field).

Usage:
    python decode_recording_export.py <export.zip|dir> [--report] [--dump-jsonl OUT.jsonl]

Requires a snappy codec: `python-snappy` (preferred) or `cramjam`.
"""

from __future__ import annotations

import argparse
import collections
import gzip
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Callable, Iterator

EVENT_TYPES = {0: "DomContentLoaded", 1: "Load", 2: "FullSnapshot", 3: "Incremental", 4: "Meta", 5: "Custom", 6: "Plugin"}
INCREMENTAL_SOURCES = {
    0: "Mutation",
    1: "MouseMove",
    2: "MouseInteraction",
    3: "Scroll",
    4: "ViewportResize",
    5: "Input",
    6: "TouchMove",
    7: "MediaInteraction",
    8: "StyleSheetRule",
    9: "CanvasMutation",
    10: "Font",
    11: "Log",
    12: "Drag",
    13: "StyleDeclaration",
    14: "Selection",
    15: "AdoptedStyleSheet",
}
COMPRESSED_MUTATION_FIELDS = ("adds", "attributes", "texts", "removes")
TAG_RE = re.compile(rb'"tagName":"([^"]+)"')
ATTR_KEY_RE = re.compile(rb'"([a-zA-Z_:-]+)":')


def _load_snappy() -> Callable[[bytes], bytes]:
    try:
        import snappy  # noqa: PLC0415 — optional codec, resolved at runtime

        return snappy.decompress
    except ImportError:
        pass
    try:
        import cramjam  # noqa: PLC0415 — fallback codec, resolved at runtime

        return lambda b: bytes(cramjam.snappy.decompress(b))
    except ImportError as err:
        raise SystemExit("Need a snappy codec. Install with `pip install python-snappy` (or `cramjam`).") from err


def _strip_null_padding(raw: bytes) -> bytes:
    start = 0
    while start < len(raw) and raw[start] == 0:
        start += 1
    end = len(raw)
    while end > start and raw[end - 1] == 0:
        end -= 1
    return raw[start:end]


def iter_block_text(source: Path, snappy_decompress: Callable[[bytes], bytes]) -> Iterator[str]:
    """Yield the snappy-decompressed UTF-8 text of every data block in the export."""
    if source.is_dir():
        block_paths = sorted((source / "data").glob("*")) if (source / "data").is_dir() else sorted(source.glob("*"))
        readers = [(p.name, p.read_bytes) for p in block_paths if p.is_file()]
    else:
        with zipfile.ZipFile(source) as zf:
            names = [n for n in zf.namelist() if n.startswith("data/") and not n.endswith("/")]
            readers = [(n, (lambda n=n: zipfile.ZipFile(source).read(n))) for n in names]

    for name, read in readers:
        block = _strip_null_padding(read())
        if not block:
            continue
        try:
            yield snappy_decompress(block).decode("utf-8", "replace")
        except Exception as err:  # noqa: BLE001 — a single bad block shouldn't abort the run
            print(f"  ! skipped block {name}: {err}", file=sys.stderr)


def iter_records(block_text: str) -> Iterator[dict]:
    """Yield the event dict from each `["windowId", {event}]` JSONL row."""
    for line in block_text.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, list) and len(row) == 2 and isinstance(row[1], dict):
            yield row[1]


def gunzip_field(field: str) -> bytes:
    """Reverse fflate `strFromU8(gzipSync(...), true)`: each char is one gzip byte."""
    return gzip.decompress(bytes(ord(c) & 0xFF for c in field))


class Report:
    def __init__(self) -> None:
        self.records = 0
        self.gz_ok = 0
        self.gz_fail = 0
        self.dom_bytes: collections.Counter[str] = collections.Counter()
        self.dom_n: collections.Counter[str] = collections.Counter()
        self.tags: collections.Counter[str] = collections.Counter()
        self.attrs: collections.Counter[str] = collections.Counter()
        self.net_body_bytes = 0
        self.net_bodies = 0
        self.net_bytes_by_content_type: collections.Counter[str] = collections.Counter()

    def add_dom(self, label: str, decompressed: bytes, collect_tags: bool, collect_attrs: bool) -> None:
        self.dom_bytes[label] += len(decompressed)
        self.dom_n[label] += 1
        if collect_tags:
            for tag in TAG_RE.findall(decompressed):
                self.tags[tag.decode("utf-8", "replace").lower()] += 1
        if collect_attrs:
            for attr in ATTR_KEY_RE.findall(decompressed):
                self.attrs[attr.decode()] += 1


def analyse(source: Path) -> Report:
    snappy_decompress = _load_snappy()
    report = Report()
    for block_text in iter_block_text(source, snappy_decompress):
        for event in iter_records(block_text):
            report.records += 1
            cv = event.get("cv")
            data = event.get("data")
            event_type = event.get("type")

            if cv == "2024-10" and event_type == 2 and isinstance(data, str):
                _decode_into(report, "FullSnapshot", data, collect_tags=True, collect_attrs=False)
            elif cv == "2024-10" and event_type == 3 and isinstance(data, dict):
                for field in COMPRESSED_MUTATION_FIELDS:
                    value = data.get(field)
                    if isinstance(value, str):
                        _decode_into(
                            report,
                            f"mutation.{field}",
                            value,
                            collect_tags=(field == "adds"),
                            collect_attrs=(field == "attributes"),
                        )
            elif event_type == 6 and isinstance(data, dict):
                _measure_network(report, data)
    return report


def _decode_into(report: Report, label: str, field: str, collect_tags: bool, collect_attrs: bool) -> None:
    try:
        decompressed = gunzip_field(field)
    except Exception:  # noqa: BLE001 — count and move on; one field shouldn't abort
        report.gz_fail += 1
        return
    report.gz_ok += 1
    report.add_dom(label, decompressed, collect_tags, collect_attrs)


def _measure_network(report: Report, data: dict) -> None:
    payload = data.get("payload")
    requests = payload.get("requests") if isinstance(payload, dict) else None
    for request in requests or []:
        content_type = "unknown"
        headers = request.get("responseHeaders") or {}
        if isinstance(headers, dict):
            for header, value in headers.items():
                if header.lower() == "content-type" and isinstance(value, str):
                    content_type = value.split(";")[0].strip()
        for key in ("requestBody", "responseBody"):
            body = request.get(key)
            if isinstance(body, str):
                report.net_body_bytes += len(body)
                report.net_bodies += 1
                report.net_bytes_by_content_type[content_type] += len(body)


def print_report(report: Report) -> None:
    dom_total = sum(report.dom_bytes.values())
    print(f"records parsed: {report.records:,}   gzip fields ok={report.gz_ok:,} fail={report.gz_fail:,}\n")
    print(f"=== decompressed DOM payload: {dom_total:,} bytes ({dom_total / 1024 / 1024:.1f} MiB) ===")
    for label, by in report.dom_bytes.most_common():
        share = 100 * by / dom_total if dom_total else 0
        print(f"  {label:20} n={report.dom_n[label]:7,}  {by:14,} ({by / 1024 / 1024:7.1f} MiB, {share:4.1f}%)")

    net_total = report.net_body_bytes
    print(f"\n=== network bodies: {net_total:,} bytes ({net_total / 1024 / 1024:.1f} MiB) across {report.net_bodies:,} bodies ===")
    print("  (these are stored UN-gzipped in the JSONL, unlike DOM fields — compare decoded sizes, not raw bytes)")
    for ct, by in report.net_bytes_by_content_type.most_common(10):
        share = 100 * by / net_total if net_total else 0
        print(f"    {by / 1024 / 1024:8.1f} MiB ({share:4.1f}%)  {ct}")

    print("\n=== top tagNames (FullSnapshot + adds) ===")
    for tag, n in report.tags.most_common(20):
        print(f"  {n:9,}  {tag}")

    print("\n=== top mutated attribute keys ===")
    for attr, n in report.attrs.most_common(20):
        print(f"  {n:9,}  {attr}")


def dump_jsonl(source: Path, out_path: Path) -> None:
    """Write fully-decoded events (DOM fields un-gzipped, inlined) to a JSONL file."""
    snappy_decompress = _load_snappy()
    written = 0
    with out_path.open("w") as out:
        for block_text in iter_block_text(source, snappy_decompress):
            for event in iter_records(block_text):
                cv = event.get("cv")
                data = event.get("data")
                if cv == "2024-10" and event.get("type") == 2 and isinstance(data, str):
                    try:
                        event["data"] = json.loads(gunzip_field(data))
                        event.pop("cv", None)
                    except Exception:  # noqa: BLE001
                        pass
                elif cv == "2024-10" and event.get("type") == 3 and isinstance(data, dict):
                    for field in COMPRESSED_MUTATION_FIELDS:
                        value = data.get(field)
                        if isinstance(value, str):
                            try:
                                data[field] = json.loads(gunzip_field(value))
                            except Exception:  # noqa: BLE001
                                pass
                    event.pop("cv", None)
                out.write(json.dumps(event, separators=(",", ":")))
                out.write("\n")
                written += 1
    print(f"wrote {written:,} decoded events to {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Decode and analyse a session-recording export zip.")
    parser.add_argument("source", type=Path, help="path to export-<id>.zip or an extracted export directory")
    parser.add_argument("--report", action="store_true", help="print the size/composition report (default)")
    parser.add_argument("--dump-jsonl", type=Path, metavar="OUT", help="write fully-decoded events to a JSONL file")
    args = parser.parse_args()

    if not args.source.exists():
        raise SystemExit(f"no such path: {args.source}")

    if args.dump_jsonl:
        dump_jsonl(args.source, args.dump_jsonl)
    if args.report or not args.dump_jsonl:
        print_report(analyse(args.source))


if __name__ == "__main__":
    main()
