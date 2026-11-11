_TERMINATORS = set(".!?")
_CLOSE = set("\"'”’“‘)]}»«([{")
_CONTINUE = set(",;:-")
_MARKDOWN_CLOSE = _CLOSE | set("*_`~")
_BACKTICK = "`"
_CODE_MASK = "x"
_TITLES = frozenset({"dr", "mr", "mrs", "ms", "prof", "st", "jr", "sr"})


def _continues_sentence(rest: str) -> bool:
    for char in rest:
        if char.isalpha():
            return char.islower()
        if char in _TERMINATORS:
            return False
    return False


def _ends_with_title(text: str, term_start: int) -> bool:
    word_start = term_start
    while word_start > 0 and text[word_start - 1].isalpha():
        word_start -= 1
    starts_word = word_start == 0 or not text[word_start - 1].isalnum()
    return starts_word and text[word_start:term_start].lower() in _TITLES


def _period_continues(text: str, term_start: int, term_end: int, next_index: int) -> bool:
    following = text[next_index] if next_index < len(text) else ""
    preceding = text[term_start - 1] if term_start > 0 else ""
    touching = next_index == term_end
    if touching and (following.isdigit() or (preceding.isalpha() and following.isupper())):
        return True
    if term_end - term_start == 1 and text[term_start] == "." and _ends_with_title(text, term_start):
        return True
    return _continues_sentence(text[next_index:])


def _sentence_breaks(text: str, close: set[str]) -> list[int]:
    breaks: list[int] = []
    index = 0
    while index < len(text):
        if text[index] not in _TERMINATORS:
            index += 1
            continue
        term_start = index
        while index < len(text) and text[index] in _TERMINATORS:
            index += 1
        term_end = index
        while index < len(text) and text[index] in close:
            index += 1
        while index < len(text) and text[index] in " \t\u00a0":
            index += 1
        if index >= len(text):
            break
        if text[index] in _CONTINUE or text[index] in _TERMINATORS:
            continue
        if text[term_end - 1] == "." and _period_continues(text, term_start, term_end, index):
            continue
        breaks.append(index)
    return breaks


def _sentences_at(text: str, breaks: list[int]) -> list[tuple[int, str]]:
    edges = [0, *breaks, len(text)]
    return [(start, text[start:end]) for start, end in zip(edges, edges[1:]) if start < end]


def split_sentences(text: str) -> list[tuple[int, str]]:
    return _sentences_at(text, _sentence_breaks(text, _CLOSE))


def _backtick_run_end(text: str, start: int) -> int:
    end = start
    while end < len(text) and text[end] == _BACKTICK:
        end += 1
    return end


def _closing_run(text: str, start: int, size: int) -> int | None:
    index = start
    while index < len(text):
        if text[index] != _BACKTICK:
            index += 1
            continue
        end = _backtick_run_end(text, index)
        if end - index == size:
            return index
        index = end
    return None


def _without_code_spans(markdown: str) -> str:
    masked = list(markdown)
    index = 0
    while index < len(markdown):
        if markdown[index] != _BACKTICK:
            index += 1
            continue
        opening_end = _backtick_run_end(markdown, index)
        closing = _closing_run(markdown, opening_end, opening_end - index)
        if closing is None:
            index = opening_end
            continue
        masked[opening_end:closing] = [
            _CODE_MASK if char in _TERMINATORS else char for char in markdown[opening_end:closing]
        ]
        index = closing + opening_end - index
    return "".join(masked)


def split_markdown_sentences(markdown: str) -> list[tuple[int, str]]:
    return _sentences_at(markdown, _sentence_breaks(_without_code_spans(markdown), _MARKDOWN_CLOSE))
