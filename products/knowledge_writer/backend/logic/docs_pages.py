import os
import re
import json
import base64
import string
import subprocess
from bisect import bisect_right
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

DOCS_SOURCE_EXTENSIONS = (".md", ".mdx")
COMPANION_PATHS = frozenset({"vercel.json", "src/navs/index.js"})
PAGE_CHANGING_STATUSES = frozenset({"added", "removed"})
SITE_PATH_PATTERN = re.compile(r"/(?![/\\])[^\s\\\x00-\x1f\x7f]*")
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
    r"@@ -(?P<base_start>\d{1,9})(?:,(?P<base_length>\d{1,9}))? \+(?P<head_start>\d{1,9})(?:,(?P<head_length>\d{1,9}))? @@"
)
NO_FINAL_NEWLINE_MARKER = "\\ No newline at end of file"
OPENING_BRACKETS = frozenset("{[(")
OPENING_BRACKET_BY_CLOSING = {"}": "{", "]": "[", ")": "("}
STRING_QUOTES = frozenset("'\"`")
REDIRECT_KEYS = frozenset({"source", "destination", "permanent", "statusCode"})
LITERAL_PATH_PATTERN = re.compile(r"[A-Za-z0-9_\-./]*(?::ext\(\\\.md\)\?)?")
PAGE_PATH_CONTINUATION_CHARACTERS = frozenset(f"{string.ascii_letters}{string.digits}_-/")


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


def nav_line_links(line: str) -> tuple[str, ...] | None:
    code, position, previous_kind, pending_key = line.rstrip(), 0, "start", None
    links: list[str] = []
    while position < len(code):
        token = NAV_LINE_TOKEN_PATTERN.match(code, position)
        if token is None or token.end() == position:
            return None
        position = token.end()
        current_kind = nav_token_kind(token)
        if not can_follow(previous_kind, current_kind):
            return None
        link = string_literal(token)
        if pending_key in NAV_LINK_KEYS and link is None:
            return None
        if pending_key in NAV_LINK_KEYS and link is not None:
            links.append(link)
        previous_kind, pending_key = current_kind, token.group("key")
    if pending_key in NAV_LINK_KEYS:
        return None
    return tuple(links)


@dataclass(frozen=True, slots=True, kw_only=True)
class NavEntryEdit:
    line_number: int
    line: str
    is_base_line: bool


def nav_entry_edits_outside_pages(
    base_text: str | None, head_text: str | None, patch: str, page_paths: frozenset[str]
) -> tuple[NavEntryEdit, ...] | None:
    if base_text is None or head_text is None:
        return None
    base_nav, head_nav = read_nav_text(base_text, page_paths), read_nav_text(head_text, page_paths)
    hunks = patch_hunks(patch, base_nav.lines, head_nav.lines)
    if hunks is None:
        return None
    edits = (
        hunk_edit_outside_page_entries(hunks, hunk_index, base_nav, head_nav)
        for hunk_index, hunk in enumerate(hunks)
        if hunk[0] != "equal"
    )
    return tuple(dict.fromkeys(edit for edit in edits if edit is not None))


@dataclass(frozen=True, slots=True, kw_only=True)
class NavText:
    text: str
    lines: list[str]
    line_starts: list[int]
    object_by_position: list[int | None]
    array_separator_positions: frozenset[int]
    parent_by_object: dict[int, int | None]
    end_by_object: dict[int, int]
    linked_entry_by_object: dict[int, int | None]
    objects_linking_pages: frozenset[int]


def read_nav_text(text: str, page_paths: frozenset[str]) -> NavText:
    object_by_position, array_separator_positions, parent_by_object, end_by_object = nav_objects(text)
    links = list(NAV_LINK_PAIR_PATTERN.finditer(text))
    objects_with_links = frozenset(owner for link in links if (owner := object_by_position[link.start()]) is not None)
    return NavText(
        text=text,
        lines=text.split("\n"),
        line_starts=[0, *(newline.end() for newline in re.finditer("\n", text)), len(text)],
        object_by_position=object_by_position,
        array_separator_positions=array_separator_positions,
        parent_by_object=parent_by_object,
        end_by_object=end_by_object,
        linked_entry_by_object=linked_entries(parent_by_object, objects_with_links),
        objects_linking_pages=frozenset(
            owner
            for link in links
            if links_page(string_literal(link), page_paths) and (owner := object_by_position[link.start()]) is not None
        ),
    )


def patch_hunks(
    patch: str, base_lines: list[str], head_lines: list[str]
) -> list[tuple[str, int, int, int, int]] | None:
    hunks: list[tuple[str, int, int, int, int]] = []
    base_cursor, head_cursor = 0, 0
    base_end, head_end = content_line_count(base_lines), content_line_count(head_lines)
    previous_marker = ""
    is_base_marked, is_head_marked = False, False
    for patch_line in patch.removesuffix("\n").split("\n") if patch else []:
        if patch_line == NO_FINAL_NEWLINE_MARKER:
            marks_base, marks_head = previous_marker in (" ", "-"), previous_marker in (" ", "+")
            if not (marks_base or marks_head):
                return None
            if marks_base and (is_base_marked or base_cursor != base_end):
                return None
            if marks_head and (is_head_marked or head_cursor != head_end):
                return None
            is_base_marked, is_head_marked = is_base_marked or marks_base, is_head_marked or marks_head
            previous_marker = NO_FINAL_NEWLINE_MARKER
            continue
        header = HUNK_HEADER_PATTERN.match(patch_line)
        marker, content = patch_line[:1], patch_line[1:]
        previous_marker = "@" if header is not None else marker
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
    if not is_unchanged_run(base_lines, base_cursor, base_end, head_lines, head_cursor, head_end):
        return None
    if not are_final_newlines_described(
        base_lines,
        head_lines,
        is_tail_unchanged=base_cursor < base_end,
        is_base_marked=is_base_marked,
        is_head_marked=is_head_marked,
    ):
        return None
    extend_hunks(hunks, is_change=False, base_end=base_end, head_end=head_end)
    return hunks


def are_final_newlines_described(
    base_lines: list[str], head_lines: list[str], *, is_tail_unchanged: bool, is_base_marked: bool, is_head_marked: bool
) -> bool:
    if is_tail_unchanged:
        return lacks_final_newline(base_lines) == lacks_final_newline(head_lines)
    return (is_base_marked, is_head_marked) == (lacks_final_newline(base_lines), lacks_final_newline(head_lines))


def lacks_final_newline(lines: list[str]) -> bool:
    return lines[-1] != "" if lines else False


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


def linked_entries(
    parent_by_object: dict[int, int | None], objects_with_links: frozenset[int]
) -> dict[int, int | None]:
    linked_entry_by_object: dict[int, int | None] = {}
    for nav_object, parent in parent_by_object.items():
        inherited = linked_entry_by_object[parent] if parent is not None else None
        linked_entry_by_object[nav_object] = nav_object if nav_object in objects_with_links else inherited
    return linked_entry_by_object


def hunk_edit_outside_page_entries(
    hunks: Sequence[tuple[str, int, int, int, int]], hunk_index: int, base_nav: NavText, head_nav: NavText
) -> NavEntryEdit | None:
    tag, base_start, base_end, head_start, head_end = hunks[hunk_index]
    if tag == "replace":
        return first_edit_outside_page_entries(
            head_nav, head_start, head_end, is_replacement=True, is_base=False
        ) or first_edit_outside_page_entries(base_nav, base_start, base_end, is_replacement=True, is_base=True)
    is_deletion = tag == "delete"
    nav, start, end = (base_nav, base_start, base_end) if is_deletion else (head_nav, head_start, head_end)
    previous_hunk = hunks[hunk_index - 1] if hunk_index > 0 else ("equal", 0, 0, 0, 0)
    next_hunk = (
        hunks[hunk_index + 1] if hunk_index + 1 < len(hunks) else ("equal", 0, len(nav.lines), 0, len(nav.lines))
    )
    lowest_start = previous_hunk[1] if is_deletion else previous_hunk[3]
    highest_end = next_hunk[2] if is_deletion else next_hunk[4]
    slid_starts = slid_line_starts(nav.lines, start, end, lowest_start, highest_end)
    if is_any_window_inside_page_entries(nav, slid_starts, end - start):
        return None
    return first_edit_outside_page_entries(nav, start, end, is_replacement=False, is_base=is_deletion)


def slid_line_starts(lines: list[str], start: int, end: int, lowest_start: int, highest_end: int) -> range:
    upper_start, upper_end = start, end
    while upper_start > lowest_start and lines[upper_start - 1] == lines[upper_end - 1]:
        upper_start, upper_end = upper_start - 1, upper_end - 1
    lower_start, lower_end = start, end
    while lower_end < highest_end and lines[lower_start] == lines[lower_end]:
        lower_start, lower_end = lower_start + 1, lower_end + 1
    return range(upper_start, lower_start + 1)


@dataclass(slots=True, kw_only=True)
class EntryWindow:
    nav: NavText
    is_replacement: bool
    start: int
    end: int
    edited_count_by_object: Counter[int | None]
    outside_object_count: int = 0

    def include_next_line(self) -> None:
        self.move(edited_object_counts(self.nav, self.end), start=self.start, end=self.end + 1, sign=1)

    def drop_first_line(self) -> None:
        self.move(edited_object_counts(self.nav, self.start), start=self.start + 1, end=self.end, sign=-1)

    def move(self, touched: Counter[int | None], *, start: int, end: int, sign: int) -> None:
        outside_before = sum(self.is_outside(edited_object) for edited_object in touched)
        self.start, self.end = start, end
        for edited_object, count in touched.items():
            self.edited_count_by_object[edited_object] += sign * count
        outside_after = sum(self.is_outside(edited_object) for edited_object in touched)
        self.outside_object_count += outside_after - outside_before

    def is_outside(self, edited_object: int | None) -> bool:
        if self.edited_count_by_object[edited_object] <= 0:
            return False
        return not is_page_entry_edit(self.nav, edited_object, self.start, self.end, is_replacement=self.is_replacement)


def is_any_window_inside_page_entries(nav: NavText, slid_starts: range, line_count: int) -> bool:
    window = EntryWindow(
        nav=nav, is_replacement=False, start=slid_starts.start, end=slid_starts.start, edited_count_by_object=Counter()
    )
    for _ in range(line_count):
        window.include_next_line()
    if window.outside_object_count == 0:
        return True
    for _ in slid_starts[1:]:
        window.include_next_line()
        window.drop_first_line()
        if window.outside_object_count == 0:
            return True
    return False


def edited_object_counts(nav: NavText, line_index: int) -> Counter[int | None]:
    return Counter(
        nav.object_by_position[position]
        for position in range(nav.line_starts[line_index], nav.line_starts[line_index + 1])
        if is_edited_position(nav, position)
    )


def is_edited_position(nav: NavText, position: int) -> bool:
    return not nav.text[position].isspace() and position not in nav.array_separator_positions


def first_edit_outside_page_entries(
    nav: NavText, start: int, end: int, *, is_replacement: bool, is_base: bool
) -> NavEntryEdit | None:
    outside_position = next(
        (
            position
            for position in range(nav.line_starts[start], nav.line_starts[end])
            if is_edited_position(nav, position)
            and not is_page_entry_edit(nav, nav.object_by_position[position], start, end, is_replacement=is_replacement)
        ),
        None,
    )
    if outside_position is None:
        return None
    line_index = bisect_right(nav.line_starts, outside_position) - 1
    return NavEntryEdit(line_number=line_index + 1, line=nav.lines[line_index].strip(), is_base_line=is_base)


def is_page_entry_edit(nav: NavText, edited_object: int | None, start: int, end: int, *, is_replacement: bool) -> bool:
    if edited_object is None:
        return False
    linked_entry = nav.linked_entry_by_object[edited_object]
    if linked_entry in nav.objects_linking_pages:
        return True
    if linked_entry == edited_object or (linked_entry is not None and is_replacement):
        return False
    return nav.line_starts[start] <= edited_object and nav.end_by_object[edited_object] < nav.line_starts[end]


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


def string_literal(token: re.Match) -> str | None:
    return token.group("single") if token.group("single") is not None else token.group("double")


def links_page(literal: str | None, page_paths: frozenset[str]) -> bool:
    return literal is not None and literal.split("#", 1)[0] in page_paths


def names_page(path: object, page_paths: frozenset[str], longest_page_path_length: int) -> bool:
    if not isinstance(path, str):
        return False
    prefix_ends = range(min(len(path), longest_page_path_length) + 1)
    return any(
        path[:prefix_end] in page_paths
        for prefix_end in prefix_ends
        if prefix_end == len(path) or path[prefix_end] not in PAGE_PATH_CONTINUATION_CHARACTERS
    )


def is_literal_site_redirect(redirect: object, docs_url_path: str) -> bool:
    if not isinstance(redirect, dict) or not set(redirect) <= REDIRECT_KEYS:
        return False
    source, destination = redirect.get("source"), redirect.get("destination")
    if not isinstance(source, str) or not isinstance(destination, str):
        return False
    if not source.startswith(docs_url_path) or not destination.startswith(docs_url_path) or "\\" in destination:
        return False
    return LITERAL_PATH_PATTERN.fullmatch(source) is not None


def removed_redirects_naming_no_page(
    base_text: str | None,
    head_text: str | None,
    page_paths: frozenset[str],
    removed_page_paths: frozenset[str],
    docs_url_path: str,
) -> tuple[dict, ...] | None:
    base, head = parsed_json_object(base_text), parsed_json_object(head_text)
    if base is None or head is None:
        return None
    if {key: value for key, value in base.items() if key != "redirects"} != {
        key: value for key, value in head.items() if key != "redirects"
    }:
        return None
    base_redirects, head_redirects = base.get("redirects", []), head.get("redirects", [])
    if not isinstance(base_redirects, list) or not isinstance(head_redirects, list):
        return None
    base_rules, head_rules = canonical_rules(base_redirects), canonical_rules(head_redirects)
    removed, added = Counter(base_rules) - Counter(head_rules), Counter(head_rules) - Counter(base_rules)
    if without_rules(base_rules, removed) != without_rules(head_rules, added):
        return None
    removed_redirects = [json.loads(rule) for rule in removed.elements()]
    added_redirects = [json.loads(rule) for rule in added.elements()]
    if not all(
        is_literal_site_redirect(redirect, docs_url_path) for redirect in [*removed_redirects, *added_redirects]
    ):
        return None
    longest_page_path_length = max(map(len, page_paths), default=0)
    if not all(
        names_page(redirect["source"], removed_page_paths, longest_page_path_length) for redirect in added_redirects
    ):
        return None
    return tuple(
        redirect
        for redirect in removed_redirects
        if not names_page(redirect["source"], page_paths, longest_page_path_length)
        and not names_page(redirect["destination"], page_paths, longest_page_path_length)
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


@dataclass(frozen=True, slots=True, kw_only=True)
class CompanionCheck:
    refusal: str | None
    flags: tuple[str, ...]
    refused_path: str | None = None


def companion_refused(refused_path: str) -> CompanionCheck:
    return CompanionCheck(refusal="changed_paths_outside_docs", flags=(), refused_path=refused_path)


def companion_check(
    changed_files: list[dict],
    docs_folders: tuple[str, ...],
    docs_url_path: str,
    base_texts: Mapping[str, str | None],
    head_texts: Mapping[str, str | None],
) -> CompanionCheck:
    companion_files = [
        changed_file for changed_file in changed_files if not is_docs_path(changed_file["filename"], docs_folders)
    ]
    if not companion_files:
        return CompanionCheck(refusal=None, flags=())
    unlisted_companion = next(
        (changed_file for changed_file in companion_files if not is_listed_companion(changed_file)), None
    )
    if unlisted_companion is not None:
        return companion_refused(unlisted_companion["filename"])
    page_paths = frozenset(f"{docs_url_path}{page_key}" for page_key in changed_page_keys(changed_files, docs_folders))
    removed_page_paths = frozenset(
        f"{docs_url_path}{page_key}"
        for page_key in changed_page_keys(changed_files, docs_folders, statuses=frozenset({"removed"}))
    )
    flags = (
        []
        if page_paths
        else [
            f"{changed_file['filename']}: edited, but this change adds or removes no page"
            for changed_file in companion_files
        ]
    )
    for changed_file in companion_files:
        filename = changed_file["filename"]
        base_text, head_text = base_texts.get(filename), head_texts.get(filename)
        file_flags = (
            redirect_flags(filename, base_text, head_text, page_paths, removed_page_paths, docs_url_path)
            if filename.endswith(".json")
            else nav_flags(filename, base_text, head_text, changed_file["patch"], page_paths)
        )
        if file_flags is None:
            return companion_refused(filename)
        flags.extend(file_flags)
    return CompanionCheck(refusal=None, flags=tuple(dict.fromkeys(flags)))


def nav_flags(
    filename: str, base_text: str | None, head_text: str | None, patch: str, page_paths: frozenset[str]
) -> list[str] | None:
    links_by_line = [nav_line_links(line) for line in changed_lines(patch)]
    if any(links is None for links in links_by_line):
        return None
    if not all(is_site_path(link) for links in links_by_line for link in links or ()):
        return None
    edits = nav_entry_edits_outside_pages(base_text, head_text, patch, page_paths)
    if edits is None:
        return None
    unchanged_page_links = dict.fromkeys(
        link for links in links_by_line for link in links or () if not links_page(link, page_paths)
    )
    return [
        *(
            f"{filename}: changes a link to {link}, which is not a page this change adds or removes"
            for link in unchanged_page_links
        ),
        *(nav_entry_flag(filename, edit) for edit in edits),
    ]


def is_site_path(link: str) -> bool:
    return SITE_PATH_PATTERN.fullmatch(link) is not None


def nav_entry_flag(filename: str, edit: NavEntryEdit) -> str:
    when = " before this change" if edit.is_base_line else ""
    return f"{filename} line {edit.line_number}{when}: edits a nav entry that links no page this change adds or removes: {edit.line}"


def redirect_flags(
    filename: str,
    base_text: str | None,
    head_text: str | None,
    page_paths: frozenset[str],
    removed_page_paths: frozenset[str],
    docs_url_path: str,
) -> list[str] | None:
    removed_redirects = removed_redirects_naming_no_page(
        base_text, head_text, page_paths, removed_page_paths, docs_url_path
    )
    if removed_redirects is None:
        return None
    return [
        f"{filename}: removes the redirect from {redirect['source']} to {redirect['destination']}, which names no page this change adds or removes"
        for redirect in removed_redirects
    ]


def is_docs_path(path: str, docs_paths: tuple[str, ...]) -> bool:
    return any(path == docs_path or path.startswith(f"{docs_path}/") for docs_path in docs_paths)


def changed_page_keys(
    changed_files: list[dict], docs_paths: tuple[str, ...], *, statuses: frozenset[str] = PAGE_CHANGING_STATUSES
) -> frozenset[str]:
    return frozenset(
        page_key
        for changed_file in changed_files
        if changed_file.get("status") in statuses
        for docs_path in docs_paths
        if (page_key := docs_page_key(changed_file["filename"], docs_path)) is not None
    )


def is_listed_companion(changed_file: dict) -> bool:
    return (
        changed_file["filename"] in COMPANION_PATHS
        and changed_file.get("status") == "modified"
        and isinstance(changed_file.get("patch"), str)
    )


def changed_lines(patch: str) -> list[str]:
    return [line[1:] for line in patch.split("\n") if line[:1] in ("+", "-")]


REGULAR_FILE_MODE = 0o100644
SYMLINK_MODE = 0o120000
SUBMODULE_MODE = 0o160000


class PatchMismatch(ValueError):
    pass


def is_editable_base_mode(base_mode: int | None) -> bool:
    return base_mode is None or base_mode == REGULAR_FILE_MODE


def changed_file_status(*, is_in_base: bool, is_deleted: bool) -> str:
    if is_deleted:
        return "removed"
    return "modified" if is_in_base else "added"


def changed_file_entry(
    filename: str, status: str, base_text: str | None, head_text: str | None, shipped_patch: str | None
) -> dict:
    return {"filename": filename, "status": status, "patch": file_patch(status, base_text, head_text, shipped_patch)}


def file_patch(status: str, base_text: str | None, head_text: str | None, shipped_patch: str | None) -> str | None:
    if base_text is None or head_text is None:
        return None
    if status == "added":
        return whole_file_patch(head_text, marker="+")
    if status == "removed":
        return whole_file_patch(base_text, marker="-")
    if shipped_patch is None or patch_hunks(shipped_patch, base_text.split("\n"), head_text.split("\n")) is None:
        raise PatchMismatch(status)
    return shipped_patch.removesuffix("\n")


def whole_file_patch(text: str, *, marker: str) -> str:
    if not text:
        return ""
    lines = text.removesuffix("\n").split("\n")
    line_span = "1" if len(lines) == 1 else f"1,{len(lines)}"
    header = f"@@ -0,0 +{line_span} @@" if marker == "+" else f"@@ -{line_span} +0,0 @@"
    body = "\n".join(f"{marker}{line}" for line in lines)
    if text.endswith("\n"):
        return f"{header}\n{body}"
    return f"{header}\n{body}\n{NO_FINAL_NEWLINE_MARKER}"


def decoded_text(content: bytes) -> str | None:
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return None


@dataclass(frozen=True, slots=True, kw_only=True)
class SandboxChangeSettings:
    base_sha: str
    docs_folders: tuple[str, ...]
    docs_url_path: str
    max_path_bytes: int
    max_change_bytes: int
    manifest_path: str


@dataclass(slots=True, kw_only=True)
class SandboxChange:
    problems: list[str]
    written: dict[str, str]
    deleted: list[str]
    patches: dict[str, str]
    changed_files: list[dict]
    base_texts: dict[str, str | None]
    head_texts: dict[str, str | None]


def sandbox_change_check(settings: SandboxChangeSettings) -> int:
    if os.path.lexists(settings.manifest_path):
        os.remove(settings.manifest_path)
    subprocess.run(["git", "add", "-A"], check=True)
    listed = git_output("diff", "--cached", "--raw", "-z", "--no-renames", settings.base_sha).split(b"\0")
    change = SandboxChange(
        problems=[], written={}, deleted=[], patches={}, changed_files=[], base_texts={}, head_texts={}
    )
    for raw_entry, path in zip(listed[0::2], listed[1::2]):
        read_staged_path(change, settings, raw_entry, path)
    companion = companion_check(
        change.changed_files, settings.docs_folders, settings.docs_url_path, change.base_texts, change.head_texts
    )
    for warning in companion.flags:
        show_agent(f"warning: {warning}")
    if companion.refused_path is not None:
        change.problems.append(companion_problem(companion.refused_path, change.changed_files, settings))
    manifest = json.dumps({"written": change.written, "deleted": change.deleted, "patches": change.patches})
    manifest_bytes = len(manifest.encode())
    if manifest_bytes > settings.max_change_bytes:
        change.problems.append(
            f"the change is {manifest_bytes} bytes, over the {settings.max_change_bytes} byte limit, make it smaller"
        )
    if change.problems:
        show_agent("\n".join(change.problems))
        return 1
    with open(settings.manifest_path, "w") as manifest_file:
        manifest_file.write(manifest)
    show_agent(f"Wrote {settings.manifest_path}")
    return 0


def show_agent(line: str) -> None:
    print(line)  # noqa: T201 — the sandbox agent reads the check's stdout


def git_output(*arguments: str) -> bytes:
    return subprocess.run(["git", *arguments], check=True, capture_output=True).stdout


def read_staged_path(change: SandboxChange, settings: SandboxChangeSettings, raw_entry: bytes, path: bytes) -> None:
    name = path.decode("utf-8", "replace")
    old_mode_field, new_mode_field, old_blob, new_blob = raw_entry.lstrip(b":").split()[:4]
    base_mode, new_mode = int(old_mode_field, 8) or None, int(new_mode_field, 8)
    is_companion = name in COMPANION_PATHS
    if len(path) > settings.max_path_bytes:
        change.problems.append(f"{name}: the path is longer than {settings.max_path_bytes} bytes, use a shorter name")
    if name.encode() != path:
        change.problems.append(f"{name}: the path is not UTF-8, rename it")
    if not is_companion and not is_docs_path(name, settings.docs_folders):
        docs_folders_named = ", ".join(f"{folder}/" for folder in settings.docs_folders)
        change.problems.append(
            f"{name}: only files under {docs_folders_named} and the files {', '.join(sorted(COMPANION_PATHS))} "
            "can change, undo this change"
        )
        return
    if not is_companion and not name.endswith(DOCS_SOURCE_EXTENSIONS):
        change.problems.append(
            f"{name}: only {' and '.join(DOCS_SOURCE_EXTENSIONS)} files can change under the docs folders"
        )
        return
    if not is_editable_base_mode(base_mode):
        change.problems.append(
            f"{name}: at the base commit this path is a symlink, submodule or executable file, "
            "which cannot be edited or deleted, undo this change"
        )
        return
    if new_mode == SYMLINK_MODE:
        change.problems.append(f"{name}: symlinks cannot be part of the change, write a regular file instead")
        return
    if new_mode == SUBMODULE_MODE:
        change.problems.append(f"{name}: submodules cannot be part of the change, remove it")
        return
    is_deleted = new_mode == 0
    head_text = "" if is_deleted else staged_head_text(change, name, new_blob.decode())
    if head_text is None:
        return
    base_text = "" if base_mode is None else decoded_text(git_output("cat-file", "blob", old_blob.decode()))
    if base_mode is not None:
        change.base_texts[name] = base_text
    status = changed_file_status(is_in_base=base_mode is not None, is_deleted=is_deleted)
    shipped_patch = staged_patch(change, settings.base_sha, name) if status == "modified" else None
    try:
        change.changed_files.append(changed_file_entry(name, status, base_text, head_text, shipped_patch))
    except PatchMismatch:
        change.problems.append(f"{name}: the publish check cannot read git's diff of this file, undo this change")


def staged_head_text(change: SandboxChange, name: str, blob: str) -> str | None:
    content = git_output("cat-file", "blob", blob)
    head_text = change.head_texts[name] = decoded_text(content)
    if head_text is None:
        change.problems.append(f"{name}: the file is not UTF-8 text, save it as UTF-8")
        return None
    change.written[name] = base64.b64encode(content).decode()
    return head_text


def staged_patch(change: SandboxChange, base_sha: str, name: str) -> str | None:
    diff_lines = git_output(
        "--literal-pathspecs",
        "diff",
        "--cached",
        "--no-color",
        "--no-ext-diff",
        "--no-textconv",
        "--text",
        base_sha,
        "--",
        name,
    ).splitlines(keepends=True)
    first_hunk = next((index for index, line in enumerate(diff_lines) if line.startswith(b"@@")), len(diff_lines))
    patch = decoded_text(b"".join(diff_lines[first_hunk:]))
    if patch is not None:
        change.patches[name] = patch
    return patch


def companion_problem(refused_path: str, changed_files: list[dict], settings: SandboxChangeSettings) -> str:
    refused_status = next(entry["status"] for entry in changed_files if entry["filename"] == refused_path)
    if refused_status != "modified":
        return f"{refused_path}: this file can only be edited, not added or removed, undo this change"
    if refused_path.endswith(".json"):
        return (
            f"{refused_path}: the publish check refuses this edit. Only add or remove whole redirects, "
            f"each a literal source and destination starting with {settings.docs_url_path}, keep the other "
            "redirects in their order and every other key unchanged, and start each added redirect from a page "
            "this change removes or renames. Fix or undo it"
        )
    return (
        f"{refused_path}: the publish check refuses this edit. Each changed line must be plain data "
        "(keys, quoted strings, numbers, true, false, brackets and commas) and each link a site path "
        "starting with /. Fix or undo it"
    )
