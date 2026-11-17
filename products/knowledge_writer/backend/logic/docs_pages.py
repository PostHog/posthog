import re
import json
from collections import Counter
from collections.abc import Sequence

from posthog.dataclasses import frozen

DOCS_SOURCE_EXTENSIONS = (".md", ".mdx")
INDEX_FILE_STEMS = frozenset({"index", "readme"})
ROUTE_GROUP_SEGMENT_PATTERN = re.compile(r"^\(.*\)$")
NAV_LINE_TOKEN_PATTERN = re.compile(
    r"""\s*(?:(?P<punctuation>[\[\]{},])|["']?(?P<key>[A-Za-z_]\w*)["']?\s*:|'(?P<single>[^'\\]*)'|"(?P<double>[^"\\]*)"|(?P<scalar>true|false|-?\d+)(?![\w.]))"""
)
NAV_LINK_KEYS = frozenset({"url", "to", "href", "link"})
NAV_VALUE_OPENERS = frozenset({"[", "{"})
NAV_LINK_PAIR_PATTERN = re.compile(
    rf"""(?<![\w$])["']?(?:{"|".join(map(re.escape, sorted(NAV_LINK_KEYS)))})["']?\s*:\s*(?:'(?P<single>[^'\\]*)'|"(?P<double>[^"\\]*)")"""
)
HUNK_HEADER_PATTERN = re.compile(
    r"@@ -(?P<base_start>\d+)(?:,(?P<base_length>\d+))? \+(?P<head_start>\d+)(?:,(?P<head_length>\d+))? @@"
)
OPENING_BRACKETS = frozenset("{[(")
OPENING_BRACKET_BY_CLOSING = {"}": "{", "]": "[", ")": "("}
STRING_QUOTES = frozenset("'\"`")
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


def are_only_page_entries_changed(
    base_text: str | None, head_text: str | None, patch: str, page_paths: frozenset[str]
) -> bool:
    if base_text is None or head_text is None:
        return False
    base_nav, head_nav = read_nav_text(base_text, page_paths), read_nav_text(head_text, page_paths)
    hunks = patch_hunks(patch, base_nav.lines, head_nav.lines)
    if hunks is None:
        return False
    return all(
        is_hunk_inside_page_entries(hunks, hunk_index, base_nav, head_nav)
        for hunk_index, hunk in enumerate(hunks)
        if hunk[0] != "equal"
    )


@frozen
class NavText:
    text: str
    lines: list[str]
    line_starts: list[int]
    object_by_position: list[int | None]
    array_separator_positions: frozenset[int]
    parent_by_object: dict[int, int | None]
    end_by_object: dict[int, int]
    objects_with_links: frozenset[int]
    objects_linking_pages: frozenset[int]


def read_nav_text(text: str, page_paths: frozenset[str]) -> NavText:
    object_by_position, array_separator_positions, parent_by_object, end_by_object = nav_objects(text)
    links = list(NAV_LINK_PAIR_PATTERN.finditer(text))
    return NavText(
        text=text,
        lines=text.split("\n"),
        line_starts=[0, *(newline.end() for newline in re.finditer("\n", text)), len(text)],
        object_by_position=object_by_position,
        array_separator_positions=array_separator_positions,
        parent_by_object=parent_by_object,
        end_by_object=end_by_object,
        objects_with_links=frozenset(
            owner for link in links if (owner := object_by_position[link.start()]) is not None
        ),
        objects_linking_pages=frozenset(
            owner
            for link in links
            if links_page(link, page_paths) and (owner := object_by_position[link.start()]) is not None
        ),
    )


def patch_hunks(
    patch: str, base_lines: list[str], head_lines: list[str]
) -> list[tuple[str, int, int, int, int]] | None:
    hunks: list[tuple[str, int, int, int, int]] = []
    base_cursor, head_cursor = 0, 0
    for patch_line in patch.split("\n") if patch else []:
        header = HUNK_HEADER_PATTERN.match(patch_line)
        marker, content = patch_line[:1], patch_line[1:]
        if header is not None:
            base_start = hunk_start(header["base_start"], header["base_length"])
            head_start = hunk_start(header["head_start"], header["head_length"])
            if not is_unchanged_run(base_lines, base_cursor, base_start, head_lines, head_cursor, head_start):
                return None
            base_cursor, head_cursor = base_start, head_start
            extend_hunks(hunks, is_change=False, base_end=base_cursor, head_end=head_cursor)
            continue
        is_base_line = marker in (" ", "-")
        is_head_line = marker in (" ", "+")
        if not (is_base_line or is_head_line):
            return None
        if is_base_line and (base_cursor >= len(base_lines) or base_lines[base_cursor] != content):
            return None
        if is_head_line and (head_cursor >= len(head_lines) or head_lines[head_cursor] != content):
            return None
        base_cursor, head_cursor = base_cursor + is_base_line, head_cursor + is_head_line
        extend_hunks(hunks, is_change=marker != " ", base_end=base_cursor, head_end=head_cursor)
    base_end, head_end = content_line_count(base_lines), content_line_count(head_lines)
    if not is_unchanged_run(base_lines, base_cursor, base_end, head_lines, head_cursor, head_end):
        return None
    extend_hunks(hunks, is_change=False, base_end=base_end, head_end=head_end)
    return hunks


def hunk_start(start: str, length: str | None) -> int:
    return int(start) if length == "0" else int(start) - 1


def content_line_count(lines: list[str]) -> int:
    return len(lines) - 1 if lines and lines[-1] == "" else len(lines)


def is_unchanged_run(
    base_lines: list[str], base_start: int, base_end: int, head_lines: list[str], head_start: int, head_end: int
) -> bool:
    if base_start > base_end or base_end - base_start != head_end - head_start:
        return False
    return base_lines[base_start:base_end] == head_lines[head_start:head_end]


def extend_hunks(hunks: list[tuple[str, int, int, int, int]], *, is_change: bool, base_end: int, head_end: int) -> None:
    previous = hunks[-1] if hunks else ("equal", 0, 0, 0, 0)
    base_start, head_start = previous[2], previous[4]
    if hunks and (previous[0] != "equal") == is_change:
        hunks.pop()
        base_start, head_start = previous[1], previous[3]
    if base_end == base_start and head_end == head_start:
        return
    tag = hunk_tag(is_change, base_end - base_start, head_end - head_start)
    hunks.append((tag, base_start, base_end, head_start, head_end))


def hunk_tag(is_change: bool, base_line_count: int, head_line_count: int) -> str:
    if not is_change:
        return "equal"
    if base_line_count and head_line_count:
        return "replace"
    return "delete" if base_line_count else "insert"


def is_hunk_inside_page_entries(
    hunks: Sequence[tuple[str, int, int, int, int]], hunk_index: int, base_nav: NavText, head_nav: NavText
) -> bool:
    tag, base_start, base_end, head_start, head_end = hunks[hunk_index]
    if tag == "replace":
        return are_lines_inside_page_entries(
            base_nav, base_start, base_end, is_replacement=True
        ) and are_lines_inside_page_entries(head_nav, head_start, head_end, is_replacement=True)
    is_deletion = tag == "delete"
    nav, start, end = (base_nav, base_start, base_end) if is_deletion else (head_nav, head_start, head_end)
    previous_hunk = hunks[hunk_index - 1] if hunk_index > 0 else ("equal", 0, 0, 0, 0)
    next_hunk = (
        hunks[hunk_index + 1] if hunk_index + 1 < len(hunks) else ("equal", 0, len(nav.lines), 0, len(nav.lines))
    )
    lowest_start = previous_hunk[1] if is_deletion else previous_hunk[3]
    highest_end = next_hunk[2] if is_deletion else next_hunk[4]
    return any(
        are_lines_inside_page_entries(nav, slid_start, slid_end, is_replacement=False)
        for slid_start, slid_end in slid_line_ranges(nav.lines, start, end, lowest_start, highest_end)
    )


def slid_line_ranges(
    lines: list[str], start: int, end: int, lowest_start: int, highest_end: int
) -> list[tuple[int, int]]:
    ranges = [(start, end)]
    upper_start, upper_end = start, end
    while upper_start > lowest_start and lines[upper_start - 1] == lines[upper_end - 1]:
        upper_start, upper_end = upper_start - 1, upper_end - 1
        ranges.append((upper_start, upper_end))
    lower_start, lower_end = start, end
    while lower_end < highest_end and lines[lower_start] == lines[lower_end]:
        lower_start, lower_end = lower_start + 1, lower_end + 1
        ranges.append((lower_start, lower_end))
    return ranges


def are_lines_inside_page_entries(nav: NavText, start: int, end: int, *, is_replacement: bool) -> bool:
    first_position, last_position = nav.line_starts[start], nav.line_starts[end]
    edited_objects = {
        nav.object_by_position[position]
        for position in range(first_position, last_position)
        if not nav.text[position].isspace() and position not in nav.array_separator_positions
    }
    return all(
        edited_object is not None
        and is_page_entry_edit(nav, edited_object, first_position, last_position, is_replacement=is_replacement)
        for edited_object in edited_objects
    )


def nearest_linked_entry(nav: NavText, nav_object: int) -> int | None:
    entry: int | None = nav_object
    while entry is not None and entry not in nav.objects_with_links:
        entry = nav.parent_by_object[entry]
    return entry


def is_page_entry_edit(
    nav: NavText, edited_object: int, first_position: int, last_position: int, *, is_replacement: bool
) -> bool:
    linked_entry = nearest_linked_entry(nav, edited_object)
    if linked_entry in nav.objects_linking_pages:
        return True
    if linked_entry == edited_object or (linked_entry is not None and is_replacement):
        return False
    return first_position <= edited_object and nav.end_by_object[edited_object] < last_position


def nav_objects(text: str) -> tuple[list[int | None], frozenset[int], dict[int, int | None], dict[int, int]]:
    object_by_position: list[int | None] = []
    array_separator_positions: set[int] = set()
    parent_by_object: dict[int, int | None] = {}
    end_by_object: dict[int, int] = {}
    open_brackets: list[tuple[str, int]] = []
    open_objects: list[int] = []
    position = 0
    while position < len(text):
        character = text[position]
        if character == "{":
            parent_by_object[position] = open_objects[-1] if open_objects else None
            end_by_object[position] = len(text)
            open_objects.append(position)
        if character in OPENING_BRACKETS:
            open_brackets.append((character, position))
        innermost = open_brackets[-1] if open_brackets else None
        if character == "," and innermost is not None and innermost[0] != "{":
            array_separator_positions.add(position)
        span_end = literal_end(text, position)
        object_by_position.extend([open_objects[-1] if open_objects else None] * (span_end - position))
        if innermost is not None and innermost[0] == OPENING_BRACKET_BY_CLOSING.get(character):
            close_bracket(innermost, open_brackets, open_objects, end_by_object, position)
        position = span_end
    return object_by_position, frozenset(array_separator_positions), parent_by_object, end_by_object


def close_bracket(
    innermost: tuple[str, int],
    open_brackets: list[tuple[str, int]],
    open_objects: list[int],
    end_by_object: dict[int, int],
    position: int,
) -> None:
    open_brackets.pop()
    if innermost[0] != "{":
        return
    end_by_object[innermost[1]] = position
    open_objects.pop()


def literal_end(text: str, position: int) -> int:
    character = text[position]
    if character in STRING_QUOTES:
        return string_end(text, position)
    if text.startswith("//", position):
        line_end = text.find("\n", position)
        return len(text) if line_end == -1 else line_end
    if text.startswith("/*", position):
        comment_end = text.find("*/", position + 2)
        return len(text) if comment_end == -1 else comment_end + 2
    return position + 1


def string_end(text: str, position: int) -> int:
    quote, cursor = text[position], position + 1
    while cursor < len(text) and text[cursor] != quote:
        cursor += 2 if text[cursor] == "\\" else 1
    return min(cursor + 1, len(text))


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


def is_page_redirect(
    redirect: object, named_page_paths: frozenset[str], source_page_paths: frozenset[str], docs_url_path: str
) -> bool:
    if not isinstance(redirect, dict) or not set(redirect) <= REDIRECT_KEYS:
        return False
    source, destination = redirect.get("source"), redirect.get("destination")
    if not isinstance(source, str) or not isinstance(destination, str):
        return False
    if not source.startswith(docs_url_path) or not destination.startswith(docs_url_path) or "\\" in destination:
        return False
    if LITERAL_PATH_PATTERN.fullmatch(source) is None:
        return False
    return names_page(source, source_page_paths) or names_page(destination, named_page_paths)


def are_only_page_redirects_changed(
    base_text: str | None,
    head_text: str | None,
    page_paths: frozenset[str],
    removed_page_paths: frozenset[str],
    docs_url_path: str,
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
    return all(
        is_page_redirect(json.loads(rule), page_paths, page_paths, docs_url_path) for rule in removed.elements()
    ) and all(
        is_page_redirect(json.loads(rule), frozenset(), removed_page_paths, docs_url_path) for rule in added.elements()
    )


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
