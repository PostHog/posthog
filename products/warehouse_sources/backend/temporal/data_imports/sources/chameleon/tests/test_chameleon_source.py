from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.chameleon.source import ChameleonSource


class TestChameleonSourceConfig:
    def setup_method(self) -> None:
        self.source = ChameleonSource()

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static endpoint catalog with no I/O, so the public docs can render it.
        assert self.source.lists_tables_without_credentials is True


class TestChameleonCredentials:
    def setup_method(self) -> None:
        self.source = ChameleonSource()

    def test_403_is_non_retryable(self) -> None:
        observed = "403 Client Error: Forbidden for url: https://api.chameleon.io/v3/edit/segments?limit=500"
        assert any(key in observed for key in self.source.get_non_retryable_errors())

    @parameterized.expand(
        [
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://api.chameleon.io/v3/edit/tours"),
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.chameleon.io"),
            ("read_timeout", "HTTPSConnectionPool(host='api.chameleon.io', port=443): Read timed out."),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, observed: str) -> None:
        assert not any(key in observed for key in self.source.get_non_retryable_errors())
