import re

DOCS_SOURCE_EXTENSIONS = (".md", ".mdx")
INDEX_FILE_STEMS = frozenset({"index", "readme"})
ROUTE_GROUP_SEGMENT_PATTERN = re.compile(r"^\(.*\)$")
PAGE_PATH_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_.\-/]+")


def page_segments(source_path: str) -> list[str]:
    return route_segments(source_path.rsplit(".", 1)[0])


def route_segments(page_path: str) -> list[str]:
    segments = [
        segment for segment in page_path.split("/") if segment and not ROUTE_GROUP_SEGMENT_PATTERN.match(segment)
    ]
    if segments and segments[-1].lower() in INDEX_FILE_STEMS:
        return segments[:-1]
    return segments


def docs_page_key(path: str, docs_folder: str) -> str | None:
    if not path.endswith(DOCS_SOURCE_EXTENSIONS) or not path.startswith(f"{docs_folder}/"):
        return None
    page_key = "/".join(route_segments(without_docs_extension(path.removeprefix(f"{docs_folder}/"))))
    return page_key or None


def linked_page_paths(text: str) -> set[str]:
    linked: set[str] = set()
    for token in PAGE_PATH_TOKEN_PATTERN.findall(text):
        segments = route_segments(without_docs_extension(token))
        linked.update("/".join(segments[start:]) for start in range(len(segments)))
    return linked


def without_docs_extension(token: str) -> str:
    for extension in DOCS_SOURCE_EXTENSIONS:
        token = token.removesuffix(extension)
    return token
