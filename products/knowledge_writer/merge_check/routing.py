from collections.abc import Iterable
from pathlib import Path

import yaml

PATH_MAP_FILE = Path(__file__).with_name("path_map.yaml")
DOCS_URL_PREFIX = "https://posthog.com/docs/"


def load_path_map() -> dict[str, str]:
    return yaml.safe_load(PATH_MAP_FILE.read_text())


def mapped_sections(touched_paths: Iterable[str], path_map: dict[str, str]) -> list[str]:
    return sorted(
        {section for path in touched_paths for prefix, section in path_map.items() if path.startswith(prefix)}
    )


def section_page_urls(section: str, docs_page_urls: list[str]) -> list[str]:
    section_url = f"{DOCS_URL_PREFIX}{section}"
    return [url for url in docs_page_urls if url == section_url or url.startswith(f"{section_url}/")]
