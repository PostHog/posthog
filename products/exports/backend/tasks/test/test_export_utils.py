from typing import Any

import pytest
from unittest.mock import patch

from django.test import SimpleTestCase

from products.exports.backend.tasks import exporter_utils

TEST_PREFIX = "Test-Exports"


class TestSiteURLReachability(SimpleTestCase):
    @patch("products.exports.backend.tasks.exporter_utils.logger")
    def test_url_not_reachable_exception(self, logger_mock: Any) -> None:
        test_url = "http://some-bad-url.test"
        with self.settings(SITE_URL=test_url):
            try:
                exporter_utils.log_error_if_site_url_not_reachable()
            except Exception as e:
                raise pytest.fail(f"Should not have raised exception: {e}")

            assert logger_mock.error.call_count == 1
            assert logger_mock.error.call_args[0][0] == "site_url_not_reachable"
            assert logger_mock.error.call_args[1]["site_url"] == test_url
            # A str, so the console renderer does not try to format it as a traceback.
            assert isinstance(logger_mock.error.call_args[1]["error"], str)
            assert "exception" not in logger_mock.error.call_args[1]

    @patch("products.exports.backend.tasks.exporter_utils.logger")
    def test_url_not_reachable_error_status(self, logger_mock: Any) -> None:
        test_url = "http://some-status-bad-url.test"
        with self.settings(SITE_URL=test_url):
            with patch("products.exports.backend.tasks.exporter_utils.requests.get") as mock_request:
                mock_request.return_value.status_code = 500
                try:
                    exporter_utils.log_error_if_site_url_not_reachable()
                except Exception as e:
                    raise pytest.fail(f"Should not have raised exception: {e}")

                assert logger_mock.error.call_count == 1
                assert logger_mock.error.call_args[0][0] == "site_url_not_reachable"
                assert logger_mock.error.call_args[1]["site_url"] == test_url
                assert logger_mock.error.call_args[1]["error"] == "HTTP status code: 500"

    @patch("products.exports.backend.tasks.exporter_utils.logger")
    def test_url_reachable_success(self, logger_mock: Any) -> None:
        test_url = "http://some-good-url.test"
        with self.settings(SITE_URL=test_url):
            with patch("products.exports.backend.tasks.exporter_utils.requests.get") as mock_request:
                mock_request.return_value.status_code = 200
                try:
                    exporter_utils.log_error_if_site_url_not_reachable()
                except Exception as e:
                    raise pytest.fail(f"Should not have raised exception: {e}")

                assert logger_mock.error.call_count == 0
