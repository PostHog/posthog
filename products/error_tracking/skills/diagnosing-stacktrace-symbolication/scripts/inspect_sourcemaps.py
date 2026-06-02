#!/usr/bin/env python3
"""Summarize JavaScript source maps and emitted JS chunks for PostHog symbolication debugging.

JavaScript-only. Hermes, Proguard, and dSYM symbolication are handled by other tools — see the
parent skill (../SKILL.md) and the per-platform references for those.

Operates on plain `.js` / `.map` files only. To inspect a PostHog symbol-data container downloaded
from the API, extract it first with `posthog-cli symbol-sets extract <file> -o <dir>` (or
`npx @posthog/cli ...` / `bunx @posthog/cli ...`) and point this script at the resulting directory.
"""

from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from pathlib import Path
from typing import Any

POSTHOG_SYMBOL_DATA_MAGIC = b"posthog_error_tracking"
JAVASCRIPT_SUFFIXES = {".js", ".mjs", ".cjs"}
MAX_INLINE_VALUE_LENGTH = 240

CHUNK_ID_RE = re.compile(r"chunkId=([^\s]+)")
SOURCE_MAPPING_URL_RE = re.compile(r"sourceMappingURL=([^\s]+)")
POSTHOG_CHUNK_IDS_RE = re.compile(r"_posthogChunkIds")


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
    debug_id = source_map.get("debug_id") or source_map.get("debugId")

    return {
        "kind": "sourcemap",
        "valid_json": True,
        "bytes": len(text.encode("utf-8")),
        "version": source_map.get("version"),
        "file": source_map.get("file"),
        "chunk_id": source_map.get("chunk_id") or source_map.get("chunkId") or debug_id,
        "debug_id": debug_id,
        "source_root": source_map.get("sourceRoot"),
        "mappings_length": len(mappings) if isinstance(mappings, str) else None,
        "sources_length": len(sources) if isinstance(sources, list) else None,
        "sources_content_length": len(sources_content) if isinstance(sources_content, list) else None,
        "names_length": len(names) if isinstance(names, list) else None,
        "first_sources": sources[:5] if isinstance(sources, list) else None,
        "empty_mappings": not mappings,
    }


def truncate(value: str, limit: int = MAX_INLINE_VALUE_LENGTH) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def summarize_js_text(text: str) -> dict[str, Any]:
    chunk_ids = CHUNK_ID_RE.findall(text)
    source_mapping_urls = SOURCE_MAPPING_URL_RE.findall(text)
    return {
        "kind": "javascript",
        "bytes": len(text.encode("utf-8")),
        "chunk_ids": chunk_ids[:10],
        "chunk_id_count": len(chunk_ids),
        "has_posthog_chunk_id_map": bool(POSTHOG_CHUNK_IDS_RE.search(text)),
        "source_mapping_urls": [truncate(url) for url in source_mapping_urls[:10]],
        "source_mapping_url_count": len(source_mapping_urls),
    }


def inspect_path(path: Path) -> list[dict[str, Any]]:
    data = path.read_bytes()
    base: dict[str, Any] = {"path": str(path), "bytes": len(data)}

    if data.startswith(POSTHOG_SYMBOL_DATA_MAGIC):
        return [
            {
                **base,
                "error": (
                    "PostHog symbol-data container — extract first with "
                    "`posthog-cli symbol-sets extract <file> -o <dir>` "
                    "(or `npx @posthog/cli ...` / `bunx @posthog/cli ...`), "
                    "then re-run this script against the extracted .js / .js.map files."
                ),
            }
        ]

    text = data.decode("utf-8", errors="replace")
    stripped = text.lstrip()
    if path.suffix == ".map" or stripped.startswith("{"):
        return [{**base, **summarize_sourcemap_text(text)}]
    return [{**base, **summarize_js_text(text)}]


def print_json(value: dict[str, Any]) -> None:
    print(json.dumps(value, sort_keys=True))


def is_interesting_path(path: Path) -> bool:
    return path.suffix == ".map" or path.suffix in JAVASCRIPT_SUFFIXES


def expand_input_path(path: Path) -> list[Path]:
    path_string = str(path)
    if glob.has_magic(path_string):
        matches = [Path(match) for match in glob.glob(path_string, recursive=True)]
        expanded = sorted(match for match in matches if match.is_file() and is_interesting_path(match))
        return expanded or [path]

    if path.is_dir():
        return sorted(child for child in path.rglob("*") if child.is_file() and is_interesting_path(child))

    return [path]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="JS/map files, directories, or globs. Extract symbol-data containers with posthog-cli first.",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    args = parser.parse_args()

    exit_code = 0
    paths = [expanded for path in args.paths for expanded in expand_input_path(path)]
    for path in paths:
        try:
            summaries = inspect_path(path)
        except Exception as err:
            summaries = [{"path": str(path), "error": str(err)}]
            exit_code = 1

        for summary in summaries:
            if "error" in summary:
                exit_code = 1
            if args.pretty:
                print(json.dumps(summary, indent=2, sort_keys=True))
            else:
                print_json(summary)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
