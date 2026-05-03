#!/usr/bin/env python3
"""Inspect JavaScript source maps and PostHog symbol-data containers."""

from __future__ import annotations

import argparse
import json
import re
import struct
import sys
from pathlib import Path
from typing import Any

MAGIC = b"posthog_error_tracking"
DATA_TYPE_SOURCE_AND_MAP = 2
COMPRESSION_NONE = 0
COMPRESSION_ZSTD = 1

CHUNK_ID_RE = re.compile(r"chunkId=([^\s]+)")
SOURCE_MAPPING_URL_RE = re.compile(r"sourceMappingURL=([^\s]+)")
POSTHOG_CHUNK_IDS_RE = re.compile(r"_posthogChunkIds")


def read_u32(data: bytes, offset: int) -> tuple[int, int]:
    return struct.unpack_from("<I", data, offset)[0], offset + 4


def read_u64(data: bytes, offset: int) -> tuple[int, int]:
    return struct.unpack_from("<Q", data, offset)[0], offset + 8


def decode_zstd(data: bytes) -> bytes:
    try:
        import io

        import zstandard
    except ImportError as err:
        raise RuntimeError("zstandard is required to decode compressed v2 symbol data") from err

    # PostHog's Rust writer streams the frame and does not include a content-size in the
    # header, so ZstdDecompressor().decompress(data) refuses it. Use the streaming reader.
    return zstandard.ZstdDecompressor().stream_reader(io.BytesIO(data)).read()


def parse_source_and_map_payload(payload: bytes) -> dict[str, Any]:
    offset = 0
    source_len, offset = read_u64(payload, offset)
    source = payload[offset : offset + source_len].decode("utf-8")
    offset += source_len
    map_len, offset = read_u64(payload, offset)
    source_map = payload[offset : offset + map_len].decode("utf-8")
    offset += map_len
    if offset != len(payload):
        raise ValueError(f"symbol payload has {len(payload) - offset} trailing bytes")
    return {"minified_source": source, "sourcemap": source_map}


def parse_symbol_data(data: bytes) -> dict[str, Any]:
    if not data.startswith(MAGIC):
        raise ValueError("not a PostHog symbol-data container")

    offset = len(MAGIC)
    version, offset = read_u32(data, offset)
    data_type, offset = read_u32(data, offset)
    compression = None

    if version == 1:
        payload = data[offset:]
    elif version == 2:
        compression = data[offset]
        offset += 1
        payload = data[offset:]
        if compression == COMPRESSION_ZSTD:
            payload = decode_zstd(payload)
        elif compression != COMPRESSION_NONE:
            raise ValueError(f"unknown symbol-data compression: {compression}")
    else:
        raise ValueError(f"unsupported symbol-data version: {version}")

    result: dict[str, Any] = {
        "kind": "posthog_symbol_data",
        "version": version,
        "data_type": data_type,
        "compression": compression,
        "compressed_bytes": len(data),
        "payload_bytes": len(payload),
    }

    if data_type == DATA_TYPE_SOURCE_AND_MAP:
        result.update(parse_source_and_map_payload(payload))

    return result


def summarize_sourcemap_text(text: str) -> dict[str, Any]:
    try:
        source_map = json.loads(text)
    except json.JSONDecodeError as err:
        return {
            "kind": "sourcemap",
            "valid_json": False,
            "error": str(err),
            "bytes": len(text.encode("utf-8")),
        }

    mappings = source_map.get("mappings")
    sources = source_map.get("sources")
    sources_content = source_map.get("sourcesContent")
    names = source_map.get("names")

    return {
        "kind": "sourcemap",
        "valid_json": True,
        "bytes": len(text.encode("utf-8")),
        "version": source_map.get("version"),
        "file": source_map.get("file"),
        "chunk_id": source_map.get("chunk_id") or source_map.get("chunkId"),
        "source_root": source_map.get("sourceRoot"),
        "mappings_length": len(mappings) if isinstance(mappings, str) else None,
        "sources_length": len(sources) if isinstance(sources, list) else None,
        "sources_content_length": len(sources_content) if isinstance(sources_content, list) else None,
        "names_length": len(names) if isinstance(names, list) else None,
        "first_sources": sources[:5] if isinstance(sources, list) else None,
        "empty_mappings": mappings == "",
    }


def summarize_js_text(text: str) -> dict[str, Any]:
    chunk_ids = CHUNK_ID_RE.findall(text)
    source_mapping_urls = SOURCE_MAPPING_URL_RE.findall(text)
    return {
        "kind": "javascript",
        "bytes": len(text.encode("utf-8")),
        "chunk_ids": chunk_ids[:10],
        "chunk_id_count": len(chunk_ids),
        "has_posthog_chunk_id_map": bool(POSTHOG_CHUNK_IDS_RE.search(text)),
        "source_mapping_urls": source_mapping_urls[:10],
        "source_mapping_url_count": len(source_mapping_urls),
    }


def inspect_path(path: Path) -> list[dict[str, Any]]:
    data = path.read_bytes()
    base: dict[str, Any] = {"path": str(path), "bytes": len(data)}

    if data.startswith(MAGIC):
        symbol_data = parse_symbol_data(data)
        header = {k: v for k, v in symbol_data.items() if k not in ("minified_source", "sourcemap")}
        summaries = [{**base, **header}]
        if "minified_source" in symbol_data:
            summaries.append(
                {
                    **base,
                    "embedded": "minified_source",
                    **summarize_js_text(symbol_data["minified_source"]),
                }
            )
        if "sourcemap" in symbol_data:
            summaries.append(
                {
                    **base,
                    "embedded": "sourcemap",
                    **summarize_sourcemap_text(symbol_data["sourcemap"]),
                }
            )
        return summaries

    text = data.decode("utf-8", errors="replace")
    stripped = text.lstrip()
    if path.suffix == ".map" or stripped.startswith("{"):
        return [{**base, **summarize_sourcemap_text(text)}]
    return [{**base, **summarize_js_text(text)}]


def build_v1_symbol_data(source: str, source_map: str) -> bytes:
    payload = (
        len(source.encode("utf-8")).to_bytes(8, "little")
        + source.encode("utf-8")
        + len(source_map.encode("utf-8")).to_bytes(8, "little")
        + source_map.encode("utf-8")
    )
    return MAGIC + (1).to_bytes(4, "little") + DATA_TYPE_SOURCE_AND_MAP.to_bytes(4, "little") + payload


def run_self_test() -> int:
    source = 'console.log("hello");\n//# chunkId=chunk_123\n//# sourceMappingURL=app.js.map\n'
    source_map = json.dumps(
        {
            "version": 3,
            "file": "app.js",
            "sources": ["src/app.ts"],
            "sourcesContent": ['console.log("hello");'],
            "names": ["console"],
            "mappings": "AAAA",
        }
    )
    symbol_data = parse_symbol_data(build_v1_symbol_data(source, source_map))
    header = {k: v for k, v in symbol_data.items() if k not in ("minified_source", "sourcemap")}
    print_json({"self_test": "symbol_header", **header})
    print_json({"self_test": "embedded_source", **summarize_js_text(symbol_data["minified_source"])})
    print_json({"self_test": "embedded_sourcemap", **summarize_sourcemap_text(symbol_data["sourcemap"])})
    return 0


def print_json(value: dict[str, Any]) -> None:
    print(json.dumps(value, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path, help="JS, .map, or PostHog symbol-data files")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    parser.add_argument("--self-test", action="store_true", help="Run an in-memory smoke test")
    args = parser.parse_args()

    if args.self_test:
        return run_self_test()

    if not args.paths:
        parser.error("provide at least one path, or use --self-test")

    exit_code = 0
    for path in args.paths:
        try:
            summaries = inspect_path(path)
        except Exception as err:
            summaries = [{"path": str(path), "error": str(err)}]
            exit_code = 1

        for summary in summaries:
            if args.pretty:
                print(json.dumps(summary, indent=2, sort_keys=True))
            else:
                print_json(summary)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
