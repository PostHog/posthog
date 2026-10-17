import json
import socket
from collections.abc import Iterable
from http import HTTPStatus
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest import TestCase
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from requests import HTTPError, Response, Session

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
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
        self.driver = SourceDriver(DevelocitySource(), self.config)

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
        first = build("build-one", 1000)
        first["models"] = {"gradleAttributes": {"model": {"buildDuration": 200}}}
        second = build("build-two", 1000)
        result = self.driver.run(
            name,
            [ScriptedResponse(json=[first]), ScriptedResponse(json=[second]), ScriptedResponse(json=[])],
        )
        assert result.raised is None
        assert result.rows == [first, second]
        assert len(result.requests) == 3
        assert result.params("fromBuild") == [None, "build-one", "build-two"]
        for request in result.requests:
            assert request.path == "/api/builds"
            assert request.headers["authorization"] == "Bearer test-access-key"
            assert request.read_timeout == 60
            assert request.param("fromInstant") == "0"
            assert request.param("reverse") == "false"
            assert request.param("maxBuilds") == "100"
            assert request.param("query") == query
            assert list(request.query.get("models", ())) == models
        assert result.response is not None and result.response.sort_mode == "asc"
        assert result.saved_states == [
            DevelocityResumeConfig(cursor="build-one"),
            DevelocityResumeConfig(cursor="build-two"),
        ]
        assert result.committed_states == result.saved_states

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
        result = self.driver.run(
            "builds",
            [ScriptedResponse(json=[])],
            should_use_incremental_field=incremental,
            db_incremental_field_last_value=last_value,
        )
        assert result.raised is None
        assert result.rows == []
        assert result.params("fromInstant") == [expected]
        assert result.saved_states == []

    @parameterized.expand([(False,), (True,)])
    def test_repeated_cursor_fails(self, resume: bool) -> None:
        result = self.driver.run(
            "builds",
            [ScriptedResponse(json=[build("same-build", 1000)])] * (1 if resume else 2),
            resume_state=DevelocityResumeConfig(cursor="same-build") if resume else None,
        )
        assert isinstance(result.raised, ValueError) and "pagination is not advancing" in str(result.raised)
        assert len(result.requests) == (1 if resume else 2)

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
        with scripted_network([ScriptedResponse(json=[] if status == 200 else {}, status=status)]) as network:
            actual_valid, actual_message = validate_credentials(self.config, 123, schema)
        assert actual_valid is valid
        if message:
            assert actual_message is not None and message in actual_message
        else:
            assert actual_message is None
        assert len(network.requests_log) == 1
        request = network.requests_log[0]
        assert request.query == {"maxBuilds": ("1",), "maxWaitSecs": ("1",), "reverse": ("true",)}
        assert request.headers["authorization"] == "Bearer test-access-key"

    @parameterized.expand([(401, "invalid or expired"), (403, "Access build data via the API")])
    def test_sync_auth_errors_match_user_message(self, status: int, message: str) -> None:
        result = self.driver.run("builds", [ScriptedResponse(json={}, status=status)])
        assert isinstance(result.raised, HTTPError)
        mapped = [
            value for key, value in DevelocitySource().get_non_retryable_errors().items() if key in str(result.raised)
        ]
        assert len(mapped) == 1 and mapped[0] is not None and message in mapped[0]
        assert len(result.requests) == 1

    @parameterized.expand([(429,), (500,), (503,)])
    def test_probe_transient_errors_remain_retryable(self, status: int) -> None:
        with scripted_network(always(ScriptedResponse(json={}, status=status))) as network:
            with pytest.raises(RESTClientRetryableError):
                validate_credentials(self.config, 123)
        assert {request.path for request in network.requests_log} == {"/api/builds"}

    def test_other_client_error_propagates(self) -> None:
        with scripted_network([ScriptedResponse(json={}, status=404)]) as network:
            with pytest.raises(HTTPError):
                validate_credentials(self.config, 123)
        assert len(network.requests_log) == 1

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
        with scripted_network([]) as network:
            valid, message = validate_credentials(self.config, 123)
        assert not valid and message is not None and "HTTPS Develocity instance URL" in message
        assert network.requests_log == []
        result = self.driver.run("builds", [])
        assert isinstance(result.raised, ValueError)
        assert result.requests == []

    @parameterized.expand(
        [
            ("https://develocity.example.com/", "https://develocity.example.com/api/builds"),
            ("https://develocity.example.com:8443", "https://develocity.example.com:8443/api/builds"),
        ]
    )
    def test_instance_url_normalization(self, instance_url: str, expected: str) -> None:
        self.config.instance_url = instance_url
        result = self.driver.run("builds", [ScriptedResponse(json=[])])
        assert result.raised is None
        assert result.requests[0].url.split("?")[0] == expected

    def test_redirect_is_rejected(self) -> None:
        result = self.driver.run(
            "builds",
            [ScriptedResponse(json={}, status=302, headers={"Location": "https://other.example.com/api/builds"})],
        )
        assert isinstance(result.raised, ValueError) and "refusing to follow" in str(result.raised)
        assert len(result.requests) == 1

    def test_unknown_table_fails_before_request(self) -> None:
        result = self.driver.run("unknown", [])
        assert isinstance(result.raised, UnknownResourceError)
        assert result.requests == []
        with scripted_network([]) as network:
            with pytest.raises(UnknownResourceError):
                validate_credentials(self.config, 123, "unknown")
        assert network.requests_log == []


class TestDevelocityPrivateDNS(TestCase):
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

    @parameterized.expand([("127.0.0.1",), ("10.0.0.1",), ("169.254.169.254",), ("::1",)])
    def test_private_dns_answer_is_rejected(self, address: str) -> None:
        self.dns.return_value = [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, 443))]
        valid, message = validate_credentials(self.config, 123)
        assert not valid and message
        with self.assertRaises(ValueError):
            develocity_source(self.config, self.inputs, self.manager)
        self.session.send.assert_not_called()
