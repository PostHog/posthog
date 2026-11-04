import re

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.errors import (
    INVALID_CONFIG_ERROR,
    ObjectStorageError,
)

GLOB_CHARACTERS = frozenset("*?{")
# Characters ClickHouse does not document as glob syntax, but that other glob dialects use. A path
# that holds them could mean either thing, so it is refused instead of read one way.
_AMBIGUOUS_CHARACTERS = frozenset("[]}")
_NUMERIC_RANGE = re.compile(r"(\d+)\.\.(\d+)")
# The matcher tracks one state per open wildcard, so its work grows with how many a pattern holds.
# Object keys are at most 1,024 bytes, and real patterns need a handful of wildcards.
MAX_PATTERN_LENGTH = 1024
MAX_WILDCARDS = 64


@frozen
class _Literal:
    character: str


@frozen
class _Question:
    pass


@frozen
class _Star:
    cross_folders: bool


@frozen
class _Alternatives:
    options: tuple[str, ...]


@frozen
class _NumericRange:
    low: int
    high: int
    width: int | None
    max_width: int


_Token = _Literal | _Question | _Star | _Alternatives | _NumericRange


@frozen
class _AlternativeState:
    token: int
    alternative: int
    offset: int


@frozen
class _NumericState:
    token: int
    digits: str


_State = int | _AlternativeState | _NumericState


@frozen
class ClickHouseGlob:
    """A path glob with the ClickHouse `s3()` semantics, matched against a whole path.

    `*` matches any characters except `/`, `**` matches any characters including `/`, `?` matches
    one character except `/`, `{a,b}` matches one of the literal alternatives, and `{N..M}` matches
    a whole number from N to M.
    """

    pattern: str
    tokens: tuple[_Token, ...]

    def _epsilon_closure(self, states: set[_State]) -> set[_State]:
        pending = [state for state in states if isinstance(state, int)]
        # Empty alternatives can reach the same token through several paths.
        visited = set(pending)
        while pending:
            index = pending.pop()
            if index == len(self.tokens):
                continue
            token = self.tokens[index]
            can_skip = False
            if isinstance(token, _Star):
                can_skip = True
            elif isinstance(token, _Alternatives):
                states.remove(index)
                for alternative, option in enumerate(token.options):
                    if option:
                        states.add(_AlternativeState(token=index, alternative=alternative, offset=0))
                    else:
                        can_skip = True
            elif isinstance(token, _NumericRange):
                states.remove(index)
                states.add(_NumericState(token=index, digits=""))
            if can_skip and index + 1 not in visited:
                visited.add(index + 1)
                states.add(index + 1)
                pending.append(index + 1)
        return states

    def matches(self, path: str) -> bool:
        states = self._epsilon_closure({0})
        for character in path:
            following: set[_State] = set()
            for state in states:
                if isinstance(state, int):
                    if state == len(self.tokens):
                        continue
                    token = self.tokens[state]
                    if isinstance(token, _Literal):
                        if character == token.character:
                            following.add(state + 1)
                    elif isinstance(token, _Question):
                        if character != "/":
                            following.add(state + 1)
                    elif isinstance(token, _Star):
                        if token.cross_folders or character != "/":
                            following.add(state)
                elif isinstance(state, _AlternativeState):
                    token = self.tokens[state.token]
                    assert isinstance(token, _Alternatives)
                    option = token.options[state.alternative]
                    if character == option[state.offset]:
                        if state.offset + 1 == len(option):
                            following.add(state.token + 1)
                        else:
                            following.add(
                                _AlternativeState(
                                    token=state.token, alternative=state.alternative, offset=state.offset + 1
                                )
                            )
                else:
                    token = self.tokens[state.token]
                    assert isinstance(token, _NumericRange)
                    if not character.isdecimal():
                        continue
                    digits = state.digits + character
                    value = int(digits)
                    if token.low <= value <= token.high and (token.width is None or len(digits) == token.width):
                        following.add(state.token + 1)
                    if len(digits) < token.max_width and (token.width is not None or value != 0):
                        following.add(_NumericState(token=state.token, digits=digits))
            if not following:
                return False
            states = self._epsilon_closure(following)
        return len(self.tokens) in states


def has_glob(path: str) -> bool:
    return any(character in GLOB_CHARACTERS for character in path)


def glob_key_prefix(pattern: str) -> str:
    """Return the literal key prefix before the first glob character."""
    for index, character in enumerate(pattern):
        if character in GLOB_CHARACTERS:
            return pattern[:index]
    return pattern


def glob_listing_prefix(pattern: str) -> str:
    """The folder that holds every path the glob can match: the segments before the first glob."""
    literal: list[str] = []
    segments = pattern.split("/")
    for index, segment in enumerate(segments):
        if has_glob(segment):
            return "/".join(literal)
        if index < len(segments) - 1:
            literal.append(segment)
    # No glob at all: the pattern names one file, and a listing of that path finds it.
    return pattern


def _invalid(pattern: str, detail: str) -> ObjectStorageError:
    return ObjectStorageError(f"{INVALID_CONFIG_ERROR}: the file pattern '{pattern}' {detail}.")


def compile_clickhouse_glob(pattern: str) -> ClickHouseGlob:
    if len(pattern) > MAX_PATTERN_LENGTH:
        raise _invalid(pattern[:64] + "...", f"is longer than {MAX_PATTERN_LENGTH:,} characters")
    tokens: list[_Token] = []
    wildcards = 0
    index = 0
    while index < len(pattern):
        character = pattern[index]
        if character == "*":
            # A run of stars matches what its widest star matches, so it is one token.
            end = index
            while end < len(pattern) and pattern[end] == "*":
                end += 1
            tokens.append(_Star(cross_folders=end - index > 1))
            wildcards += 1
            index = end
            continue
        elif character == "?":
            tokens.append(_Question())
            wildcards += 1
        elif character == "{":
            end = pattern.find("}", index)
            if end == -1:
                raise _invalid(pattern, "has a '{' with no closing '}'")
            body = pattern[index + 1 : end]
            if not body or any(nested in GLOB_CHARACTERS or nested in _AMBIGUOUS_CHARACTERS for nested in body):
                raise _invalid(pattern, "has a '{...}' group PostHog can't read")
            numeric = _NUMERIC_RANGE.fullmatch(body)
            if numeric is not None:
                start, stop = numeric.group(1), numeric.group(2)
                low, high = sorted((int(start), int(stop)))
                padded = (len(start) > 1 and start.startswith("0")) or (len(stop) > 1 and stop.startswith("0"))
                width = max(len(start), len(stop)) if padded else None
                tokens.append(_NumericRange(low=low, high=high, width=width, max_width=width or len(str(high))))
                wildcards += 1
            else:
                options = tuple(body.split(","))
                tokens.append(_Alternatives(options=options))
                wildcards += len(options)
            index = end + 1
            continue
        elif character in _AMBIGUOUS_CHARACTERS:
            raise _invalid(pattern, f"has a '{character}' that PostHog can't read as a file pattern")
        else:
            tokens.append(_Literal(character=character))
        index += 1
    if wildcards > MAX_WILDCARDS:
        raise _invalid(pattern, f"has more than {MAX_WILDCARDS} wildcards and alternatives")
    return ClickHouseGlob(pattern=pattern, tokens=tuple(tokens))
