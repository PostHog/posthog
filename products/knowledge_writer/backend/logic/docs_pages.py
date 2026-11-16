import re
import json
from collections import Counter

DOCS_SOURCE_EXTENSIONS = (".md", ".mdx")
INDEX_FILE_STEMS = frozenset({"index", "readme"})
ROUTE_GROUP_SEGMENT_PATTERN = re.compile(r"^\(.*\)$")
NAV_LINE_TOKEN_PATTERN = re.compile(
    r"""\s*(?:(?P<punctuation>[\[\]{},])|["']?(?P<key>[A-Za-z_]\w*)["']?\s*:|'(?P<single>[^'\\]*)'|"(?P<double>[^"\\]*)"|(?P<scalar>true|false|-?\d+)(?![\w.]))"""
)
NAV_LINK_KEYS = frozenset({"url", "to", "href", "link"})
NAV_VALUE_OPENERS = frozenset({"[", "{"})
REDIRECT_KEYS = frozenset({"source", "destination", "permanent", "statusCode"})
LITERAL_PATH_PATTERN = re.compile(r"[A-Za-z0-9_\-./]*(?::ext\(\\\.md\)\?)?")
PAGE_PATH_END_PATTERN = r"(?![A-Za-z0-9_\-/])"


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


def without_docs_extension(token: str) -> str:
    for extension in DOCS_SOURCE_EXTENSIONS:
        token = token.removesuffix(extension)
    return token


def is_nav_line(line: str, page_paths: frozenset[str]) -> bool:
    code, position, previous_kind, pending_key = line.rstrip(), 0, "start", None
    while position < len(code):
        token = NAV_LINE_TOKEN_PATTERN.match(code, position)
        if token is None or token.end() == position:
            return False
        position = token.end()
        current_kind = nav_token_kind(token)
        if not can_follow(previous_kind, current_kind):
            return False
        if pending_key in NAV_LINK_KEYS and not links_page(token, page_paths):
            return False
        previous_kind, pending_key = current_kind, token.group("key")
    return pending_key not in NAV_LINK_KEYS


def nav_token_kind(token: re.Match) -> str:
    if token.group("punctuation") is not None:
        return token.group("punctuation")
    if token.group("key") is not None:
        return "key"
    return "value"


def can_follow(previous: str, current: str) -> bool:
    if previous in ("value", "]", "}"):
        return current in (",", "]", "}")
    if previous == "key":
        return current == "value" or current in NAV_VALUE_OPENERS
    return current != ","


def links_page(token: re.Match, page_paths: frozenset[str]) -> bool:
    literal = token.group("single") if token.group("single") is not None else token.group("double")
    return literal is not None and literal.split("#", 1)[0] in page_paths


def names_page(path: object, page_paths: frozenset[str]) -> bool:
    return isinstance(path, str) and any(
        re.match(f"{re.escape(page)}{PAGE_PATH_END_PATTERN}", path) for page in page_paths
    )


def is_page_redirect(redirect: object, page_paths: frozenset[str], docs_url_path: str) -> bool:
    if not isinstance(redirect, dict) or not set(redirect) <= REDIRECT_KEYS:
        return False
    source, destination = redirect.get("source"), redirect.get("destination")
    if not isinstance(source, str) or not isinstance(destination, str):
        return False
    if not source.startswith(docs_url_path) or not destination.startswith(docs_url_path) or "\\" in destination:
        return False
    if LITERAL_PATH_PATTERN.fullmatch(source) is None:
        return False
    return names_page(source, page_paths) or names_page(destination, page_paths)


def are_only_page_redirects_changed(
    base_text: str | None, head_text: str | None, page_paths: frozenset[str], docs_url_path: str
) -> bool:
    base, head = parsed_json_object(base_text), parsed_json_object(head_text)
    if base is None or head is None:
        return False
    if {key: value for key, value in base.items() if key != "redirects"} != {
        key: value for key, value in head.items() if key != "redirects"
    }:
        return False
    base_redirects, head_redirects = base.get("redirects", []), head.get("redirects", [])
    if not isinstance(base_redirects, list) or not isinstance(head_redirects, list):
        return False
    base_rules, head_rules = canonical_rules(base_redirects), canonical_rules(head_redirects)
    removed, added = Counter(base_rules) - Counter(head_rules), Counter(head_rules) - Counter(base_rules)
    if without_rules(base_rules, removed) != without_rules(head_rules, added):
        return False
    return all(is_page_redirect(json.loads(rule), page_paths, docs_url_path) for rule in removed + added)


def canonical_rules(redirects: list) -> list[str]:
    return [json.dumps(redirect, sort_keys=True) for redirect in redirects]


def without_rules(rules: list[str], dropped: Counter[str]) -> list[str]:
    left_to_drop, kept = Counter(dropped), []
    for rule in rules:
        if left_to_drop[rule] > 0:
            left_to_drop[rule] -= 1
            continue
        kept.append(rule)
    return kept


def parsed_json_object(text: str | None) -> dict | None:
    if text is None:
        return None
    try:
        parsed = json.loads(text)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None
