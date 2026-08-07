import pytest

from jsonpath_ng.exceptions import JSONPathError

from posthog.temporal.common.errors import NonReportableError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.jsonpath_utils import (
    InvalidJSONPathError,
    compile_path,
)


class TestCompilePath:
    @pytest.mark.parametrize("path", [".data", "", "$.["])
    def test_unparseable_path_raises_readable_non_reportable_error(self, path):
        # A malformed selector must fail with a stable, matchable message instead of jsonpath_ng's
        # context-free "Parse error at 1:0", and stay out of error tracking (NonReportableError) so a
        # legacy stored manifest doesn't mint a fresh issue on every retry.
        with pytest.raises(InvalidJSONPathError) as exc:
            compile_path(path)
        assert isinstance(exc.value, JSONPathError)
        assert isinstance(exc.value, NonReportableError)
        assert str(exc.value).startswith("Invalid JSONPath in manifest")
        assert repr(path) in str(exc.value)

    def test_valid_path_compiles(self):
        compiled = compile_path("data.items")
        # Re-passing a compiled path is a no-op passthrough, not a re-parse.
        assert compile_path(compiled) is compiled
