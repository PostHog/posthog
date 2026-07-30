import functools
from typing import Any, Union

from jsonpath_ng import JSONPath
from jsonpath_ng.ext import parse as jsonpath_parse

TJsonPath = Union[str, JSONPath]


# jsonpath_ng builds a fresh PLY LR parser table on every parse() call (~10ms each), and the
# same handful of path strings (results_path, next_url_path, ...) are re-compiled for every
# page of every request. Compiled expressions are immutable, so cache by source string.
@functools.lru_cache(maxsize=1024)
def _compile_path_cached(path: str) -> JSONPath:
    return jsonpath_parse(path)


def compile_path(path: TJsonPath) -> JSONPath:
    if isinstance(path, JSONPath):
        return path
    return _compile_path_cached(path)


def find_values(path: TJsonPath, data: dict[str, Any]) -> list[Any]:
    compiled = compile_path(path)
    return [match.value for match in compiled.find(data)]
