import functools
from typing import Any, Union

from jsonpath_ng import JSONPath
from jsonpath_ng.exceptions import JSONPathError
from jsonpath_ng.ext import parse as jsonpath_parse

from posthog.temporal.common.errors import NonReportableError

TJsonPath = Union[str, JSONPath]


class InvalidJSONPathError(JSONPathError, NonReportableError):
    """A manifest JSONPath (``data_selector``, a paginator path, an incremental ``cursor_path``)
    that jsonpath_ng can't parse.

    Subclasses ``JSONPathError`` so the create/update-time manifest validators that already catch
    that base keep catching it, and ``NonReportableError`` so a legacy stored manifest — one saved
    before those validators compiled these fields — fails the sync with a readable message naming
    the bad expression instead of surfacing jsonpath_ng's context-free ``Parse error at 1:0`` as
    fresh error-tracking noise. The message carries a stable prefix so a source's
    ``get_non_retryable_errors`` can match it and stop the sync retrying a deterministic failure.
    """


# jsonpath_ng builds a fresh PLY LR parser table on every parse() call (~10ms each), and the
# same handful of path strings (results_path, next_url_path, ...) are re-compiled for every
# page of every request. Compiled expressions are immutable, so cache by source string.
@functools.lru_cache(maxsize=1024)
def _compile_path_cached(path: str) -> JSONPath:
    return jsonpath_parse(path)


def compile_path(path: TJsonPath) -> JSONPath:
    if isinstance(path, JSONPath):
        return path
    try:
        return _compile_path_cached(path)
    except JSONPathError as exc:
        raise InvalidJSONPathError(f"Invalid JSONPath in manifest: {path!r} could not be parsed — {exc}") from exc


def find_values(path: TJsonPath, data: dict[str, Any]) -> list[Any]:
    compiled = compile_path(path)
    return [match.value for match in compiled.find(data)]
