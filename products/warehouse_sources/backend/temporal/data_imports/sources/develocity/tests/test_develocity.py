import json
import socket
from collections.abc import Iterable
from http import HTTPStatus
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

from unittest import TestCase
from unittest.mock import MagicMock, call, patch

from parameterized import parameterized
from requests import HTTPError, Response, Session

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.develocity.develocity import (
    DevelocityResumeConfig,
    develocity_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.develocity.source import DevelocitySource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.develocity import (
    DevelocitySourceConfig,
)

REST_CLIENT = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client"
MIXINS = "products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins"


def response(body: object, status: int = 200) -> Response:
    result = Response()
    result.status_code = status
    result.reason = HTTPStatus(status).phrase
    result.url = "https://develocity.example.com/api/builds"
    result.headers["Content-Type"] = "application/json"
    result._content = json.dumps(body).encode()
    return result


def build(build_id: str, available_at: int) -> dict[str, object]:
    return {
        "id": build_id,
        "availableAt": available_at,
        "buildToolType": "gradle",
        "buildToolVersion": "9.0",
        "buildAgentVersion": "4.0",
    }


def source_items(source: SourceResponse) -> Iterable[Any]:
    return cast(Iterable[Any], source.items())


class TestDevelocity(TestCase):
    def setUp(self) -> None:
        self.config = DevelocitySourceConfig(
            instance_url="https://develocity.example.com", access_key="test-access-key"
        )
        self.inputs = SourceInputs(
            schema_name="builds",
            schema_id="schema-test",
            source_id="source-test",
            team_id=123,
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            db_incremental_field_earliest_value=None,
            incremental_field="availableAt",
            incremental_field_type=None,
            job_id="job-test",
            logger=MagicMock(),
            reset_pipeline=False,
        )
        self.manager = MagicMock(spec=ResumableSourceManager)
        self.manager.can_resume.return_value = False
        self.session = MagicMock(spec=Session)
        self.session.headers = {}
        self.session.prepare_request.side_effect = Session().prepare_request
        for patcher in (
            patch(f"{REST_CLIENT}.make_tracked_session", return_value=self.session),
            patch(f"{MIXINS}.is_cloud", return_value=True),
            patch(f"{MIXINS}.get_instance_region", return_value="US"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        dns = patch(
            f"{MIXINS}.socket.getaddrinfo",
            return_value=[(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("8.8.8.8", 443))],
        )
        self.dns = dns.start()
        self.addCleanup(dns.stop)

    def requests(self) -> list[dict[str, list[str]]]:
        return [parse_qs(urlsplit(sent.args[0].url).query) for sent in self.session.send.call_args_list]

    @parameterized.expand(
        [
            ("builds", None, []),
            (
                "gradle_builds",
                "buildTool:gradle",
                ["gradle-attributes", "gradle-build-cache-performance", "gradle-test-performance"],
            ),
            (
                "maven_builds",
                "buildTool:maven",
                ["maven-attributes", "maven-build-cache-performance", "maven-test-performance"],
            ),
        ]
    )
    def test_request_models_and_short_page_pagination(self, name: str, query: str | None, models: list[str]) -> None:
        self.inputs.schema_name = name
        first = build("build-one", 1000)
        first["models"] = {"gradleAttributes": {"model": {"buildDuration": 200}}}
        second = build("build-two", 1000)
        self.session.send.side_effect = [response([first]), response([second]), response([])]

        source = develocity_source(self.config, self.inputs, self.manager)
        rows = [row for page in source_items(source) for row in page]

        assert rows == [first, second]
        params = self.requests()
        assert len(params) == 3
        assert "fromBuild" not in params[0]
        assert params[1]["fromBuild"] == ["build-one"]
        assert params[2]["fromBuild"] == ["build-two"]
        for sent, query_params in zip(self.session.send.call_args_list, params):
            assert urlsplit(sent.args[0].url).path == "/api/builds"
            assert sent.args[0].headers["Authorization"] == "Bearer test-access-key"
            assert sent.kwargs["allow_redirects"] is False
            assert sent.kwargs["timeout"] == 60
            assert query_params["fromInstant"] == ["0"]
            assert query_params["reverse"] == ["false"]
            assert query_params["maxBuilds"] == ["100"]
            assert query_params.get("query") == ([query] if query else None)
            assert query_params.get("models", []) == models
        assert source.sort_mode == "asc"
        assert self.manager.save_state.call_args_list == [
            call(DevelocityResumeConfig(cursor="build-one")),
            call(DevelocityResumeConfig(cursor="build-two")),
        ]

    @parameterized.expand(
        [
            (True, 1000, "999"),
            (True, "1000", "999"),
            (True, 0, "0"),
            (True, None, "0"),
            (False, 1000, "0"),
            (False, None, "0"),
        ]
    )
    def test_incremental_and_full_refresh(self, incremental: bool, last_value: int | str | None, expected: str) -> None:
        self.inputs.should_use_incremental_field = incremental
        self.inputs.db_incremental_field_last_value = last_value
        self.session.send.return_value = response([])
        assert list(source_items(develocity_source(self.config, self.inputs, self.manager))) == []
        assert self.requests()[0]["fromInstant"] == [expected]
        self.manager.save_state.assert_not_called()

    @parameterized.expand([(True, "saved-build"), (True, None), (False, "ignored-build")])
    def test_resume_cursor(self, can_resume: bool, cursor: str | None) -> None:
        self.manager.can_resume.return_value = can_resume
        self.manager.load_state.return_value = DevelocityResumeConfig(cursor=cursor) if cursor else None
        self.session.send.side_effect = [response([build("next-build", 2000)]), response([])]
        list(source_items(develocity_source(self.config, self.inputs, self.manager)))
        expected = [cursor] if can_resume and cursor else None
        assert self.requests()[0].get("fromBuild") == expected
        assert self.requests()[1]["fromBuild"] == ["next-build"]
        self.manager.save_state.assert_called_once_with(DevelocityResumeConfig(cursor="next-build"))
        self.manager.commit.assert_not_called()

    @parameterized.expand([(False,), (True,)])
    def test_repeated_cursor_fails(self, resume: bool) -> None:
        self.manager.can_resume.return_value = resume
        self.manager.load_state.return_value = DevelocityResumeConfig(cursor="same-build")
        self.session.send.return_value = response([build("same-build", 1000)])
        with self.assertRaisesRegex(ValueError, "pagination is not advancing"):
            list(source_items(develocity_source(self.config, self.inputs, self.manager)))
        assert self.session.send.call_count == (1 if resume else 2)

    @parameterized.expand(
        [
            (200, None, True, None),
            (200, "gradle_builds", True, None),
            (401, None, False, "invalid or expired"),
            (401, "builds", False, "invalid or expired"),
            (403, None, True, None),
            (403, "maven_builds", False, "Access build data via the API"),
        ]
    )
    def test_credential_probe(self, status: int, schema: str | None, valid: bool, message: str | None) -> None:
        self.session.send.return_value = response([] if status == 200 else {}, status)
        actual_valid, actual_message = validate_credentials(self.config, 123, schema)
        assert actual_valid is valid
        if message:
            assert actual_message is not None and message in actual_message
        else:
            assert actual_message is None
        self.session.send.assert_called_once()
        assert self.requests()[0] == {"maxBuilds": ["1"], "maxWaitSecs": ["1"], "reverse": ["true"]}
        sent = self.session.send.call_args.args[0]
        assert sent.headers["Authorization"] == "Bearer test-access-key"

    @parameterized.expand([(401, "invalid or expired"), (403, "Access build data via the API")])
    def test_sync_auth_errors_match_user_message(self, status: int, message: str) -> None:
        self.session.send.return_value = response({}, status)
        with self.assertRaises(HTTPError) as raised:
            list(source_items(develocity_source(self.config, self.inputs, self.manager)))
        mapped = [
            value
            for key, value in DevelocitySource().get_non_retryable_errors().items()
            if key in str(raised.exception)
        ]
        assert len(mapped) == 1 and mapped[0] is not None and message in mapped[0]
        self.session.send.assert_called_once()

    @parameterized.expand([(429,), (500,), (503,)])
    def test_probe_transient_errors_remain_retryable(self, status: int) -> None:
        self.session.send.return_value = response({}, status)
        with self.assertRaises(RESTClientRetryableError):
            validate_credentials(self.config, 123)
        self.session.send.assert_called_once()

    def test_other_client_error_propagates(self) -> None:
        self.session.send.return_value = response({}, 404)
        with self.assertRaises(HTTPError):
            validate_credentials(self.config, 123)

    @parameterized.expand(
        [
            ("http://develocity.example.com",),
            ("develocity.example.com",),
            ("https://user:secret@develocity.example.com",),
            ("https://develocity.example.com/api",),
            ("https://develocity.example.com?key=value",),
            ("https://develocity.example.com#fragment",),
            ("https://develocity.example.com:bad",),
            ("https://develocity.example.com:99999",),
            ("https://develocity.example.com:0",),
            ("https://develocity.example.com\n",),
            ("https://develocity.example.com\\path",),
            ("https://[broken",),
        ]
    )
    def test_invalid_url_sends_no_credentials(self, instance_url: str) -> None:
        self.config.instance_url = instance_url
        valid, message = validate_credentials(self.config, 123)
        assert not valid and message is not None and "HTTPS Develocity instance URL" in message
        with self.assertRaises(ValueError):
            develocity_source(self.config, self.inputs, self.manager)
        self.session.send.assert_not_called()

    @parameterized.expand([("127.0.0.1",), ("10.0.0.1",), ("169.254.169.254",), ("::1",)])
    def test_private_dns_answer_is_rejected(self, address: str) -> None:
        self.dns.return_value = [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, 443))]
        valid, message = validate_credentials(self.config, 123)
        assert not valid and message
        with self.assertRaises(ValueError):
            develocity_source(self.config, self.inputs, self.manager)
        self.session.send.assert_not_called()

    @parameterized.expand(
        [
            ("https://develocity.example.com/", "https://develocity.example.com/api/builds"),
            ("https://develocity.example.com:8443", "https://develocity.example.com:8443/api/builds"),
        ]
    )
    def test_instance_url_normalization(self, instance_url: str, expected: str) -> None:
        self.config.instance_url = instance_url
        self.session.send.return_value = response([])
        list(source_items(develocity_source(self.config, self.inputs, self.manager)))
        assert self.session.send.call_args.args[0].url.split("?")[0] == expected

    def test_redirect_is_rejected(self) -> None:
        redirect = response({}, 302)
        redirect.headers["Location"] = "https://other.example.com/api/builds"
        self.session.send.return_value = redirect
        with self.assertRaisesRegex(ValueError, "refusing to follow"):
            list(source_items(develocity_source(self.config, self.inputs, self.manager)))
        self.session.send.assert_called_once()
        assert self.session.send.call_args.kwargs["allow_redirects"] is False

    def test_unknown_table_fails_before_request(self) -> None:
        self.inputs.schema_name = "unknown"
        with self.assertRaises(UnknownResourceError):
            develocity_source(self.config, self.inputs, self.manager)
        with self.assertRaises(UnknownResourceError):
            validate_credentials(self.config, 123, "unknown")
        self.session.send.assert_not_called()
