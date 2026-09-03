import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.gainsight_cs.gainsight_cs import (
    GainsightCsHostNotAllowedError,
    GainsightCsResumeConfig,
    _normalize_row,
    _parse_fields,
    _rows_from_body,
    gainsight_cs_source,
    normalize_domain,
    parse_custom_objects,
    validate_credentials,
)

SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.gainsight_cs.gainsight_cs.make_tracked_session"
)
HOST_CHECK_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.gainsight_cs.gainsight_cs._is_host_safe"
)
PAGE_SIZE_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.gainsight_cs.gainsight_cs.MAX_PAGE_SIZE"
)

DOMAIN = "acme.gainsightcloud.com"


def _response(body: Any, *, status_code: int = 200, headers: dict[str, str] | None = None) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    if headers:
        resp.headers.update(headers)
    return resp


def _describe_body(fields: list[dict[str, Any]], object_name: str = "company") -> dict[str, Any]:
    return {"result": True, "data": [{"objectName": object_name, "fields": fields}]}


def _field(name: str, data_type: str = "STRING", sortable: bool = True) -> dict[str, Any]:
    return {"fieldName": name, "dataType": data_type, "meta": {"sortable": sortable}}


def _manager(resume_state: GainsightCsResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


class TestResponseEnvelope:
    @parameterized.expand(
        [
            ("records_at_data", {"result": True, "data": [{"Gsid": "1"}]}, [{"Gsid": "1"}]),
            ("records_nested", {"result": True, "data": {"records": [{"Gsid": "1"}]}}, [{"Gsid": "1"}]),
            ("empty_nested", {"result": True, "data": {"records": []}}, []),
            ("empty_list", {"result": True, "data": []}, []),
            ("null_data", {"result": True, "data": None}, []),
        ]
    )
    def test_reads_both_documented_envelopes(self, _name: str, body: dict[str, Any], expected: list[Any]) -> None:
        # The Company docs put the records directly on `data`, Timeline nests them under
        # `data.records`. Reading only one shape turns the other into a single junk row.
        assert _rows_from_body(body, "company") == expected

    def test_rejects_an_unrecognized_data_shape(self) -> None:
        with pytest.raises(ValueError, match="unexpected record shape"):
            _rows_from_body({"result": True, "data": {"count": 3}}, "company")

    def test_surfaces_an_api_failure_returned_on_a_200(self) -> None:
        body = {"result": False, "errorDesc": "Object not found", "data": None}
        with pytest.raises(ValueError, match="Object not found"):
            _rows_from_body(body, "company")


class TestParseFields:
    def test_prefers_the_definition_for_the_requested_object(self) -> None:
        # Describe answers with a list; taking the first entry blindly would select another
        # object's fields and sync the wrong columns.
        body = {
            "result": True,
            "data": [
                {"objectName": "company_person", "fields": [_field("PersonId")]},
                {"objectName": "company", "fields": [_field("Name")]},
            ],
        }
        assert [f.name for f in _parse_fields(body, "company")] == ["Name"]

    def test_reads_type_and_sortability_from_the_field_metadata(self) -> None:
        body = _describe_body([_field("CreatedDate", data_type="datetime", sortable=False)])
        field = _parse_fields(body, "company")[0]
        assert (field.data_type, field.sortable) == ("DATETIME", False)

    def test_raises_when_the_object_exposes_no_fields(self) -> None:
        with pytest.raises(ValueError, match="no fields for object"):
            _parse_fields(_describe_body([]), "company")

    def test_never_substitutes_another_objects_fields(self) -> None:
        # The requested object is present but empty. Borrowing the neighbour's fields would build a
        # `select` of columns this object doesn't have.
        body = {
            "result": True,
            "data": [
                {"objectName": "company", "fields": []},
                {"objectName": "company_person", "fields": [_field("PersonId")]},
            ],
        }
        with pytest.raises(ValueError, match="no fields for object"):
            _parse_fields(body, "company")


class TestNormalizeRow:
    @parameterized.expand(
        [
            ("epoch_millis", 1521691459693, datetime(2018, 3, 22, 4, 4, 19, 693000, tzinfo=UTC)),
            ("iso_string_untouched", "2024-02-05T07:17:16Z", "2024-02-05T07:17:16Z"),
            ("none_untouched", None, None),
        ]
    )
    def test_converts_date_fields(self, _name: str, value: Any, expected: Any) -> None:
        assert _normalize_row({"CreatedDate": value}, frozenset({"CreatedDate"})) == {"CreatedDate": expected}

    def test_leaves_non_date_columns_alone(self) -> None:
        row = {"Employees": 1521691459693, "CreatedDate": 0}
        normalized = _normalize_row(row, frozenset({"CreatedDate"}))
        assert normalized["Employees"] == 1521691459693


class TestCustomObjects:
    @parameterized.expand(
        [
            ("trims_whitespace", " health__gc , renewal__gc ", ["health__gc", "renewal__gc"]),
            ("drops_path_traversal", "../../etc/passwd,ok__gc", ["ok__gc"]),
            ("drops_query_injection", "company?x=1", []),
            ("drops_standard_objects", "company,health__gc", ["health__gc"]),
            ("empty", "", []),
            ("none", None, []),
        ]
    )
    def test_only_object_shaped_names_survive(self, _name: str, raw: str | None, expected: list[str]) -> None:
        # These names are interpolated into the request path, so anything that isn't a bare
        # object name has to be dropped before it can reshape the URL.
        assert parse_custom_objects(raw) == expected


class TestNormalizeDomain:
    @parameterized.expand(
        [
            ("bare", "acme.gainsightcloud.com"),
            ("with_scheme", "https://acme.gainsightcloud.com"),
            ("with_trailing_slash", "https://acme.gainsightcloud.com/"),
            ("with_path", "acme.gainsightcloud.com/v1/data"),
            ("padded", "  acme.gainsightcloud.com  "),
        ]
    )
    def test_reduces_user_input_to_a_bare_host(self, _name: str, raw: str) -> None:
        assert normalize_domain(raw) == DOMAIN


class TestPagination:
    def _run(self, session: mock.MagicMock, manager: mock.MagicMock, page_size: int = 2) -> list[list[dict[str, Any]]]:
        with (
            mock.patch(SESSION_PATCH, return_value=session),
            mock.patch(HOST_CHECK_PATCH, return_value=(True, None)),
            mock.patch(PAGE_SIZE_PATCH, page_size),
        ):
            response = gainsight_cs_source(
                domain=DOMAIN,
                access_key="key",
                schema_name="company",
                object_name="company",
                primary_keys=["Gsid"],
                team_id=1,
                resumable_source_manager=manager,
            )
            return list(cast(Iterable[list[dict[str, Any]]], response.items()))

    def test_pages_until_a_short_page_and_advances_the_offset(self) -> None:
        session = mock.MagicMock()
        session.get.return_value = _response(_describe_body([_field("Gsid")]))
        session.post.side_effect = [
            _response({"result": True, "data": [{"Gsid": "1"}, {"Gsid": "2"}]}),
            _response({"result": True, "data": [{"Gsid": "3"}]}),
        ]
        manager = _manager()

        batches = self._run(session, manager)

        assert batches == [[{"Gsid": "1"}, {"Gsid": "2"}], [{"Gsid": "3"}]]
        assert [call.kwargs["json"]["offset"] for call in session.post.call_args_list] == [0, 2]

    def test_checkpoints_only_after_a_full_page_is_yielded(self) -> None:
        session = mock.MagicMock()
        session.get.return_value = _response(_describe_body([_field("Gsid")]))
        session.post.side_effect = [
            _response({"result": True, "data": [{"Gsid": "1"}, {"Gsid": "2"}]}),
            _response({"result": True, "data": []}),
        ]
        manager = _manager()

        self._run(session, manager)

        # One save, for the boundary after the first page — the terminal page has nothing to resume to.
        manager.save_state.assert_called_once_with(GainsightCsResumeConfig(offset=2))

    def test_resumes_from_the_saved_offset(self) -> None:
        session = mock.MagicMock()
        session.get.return_value = _response(_describe_body([_field("Gsid")]))
        session.post.side_effect = [_response({"result": True, "data": [{"Gsid": "9"}]})]
        manager = _manager(GainsightCsResumeConfig(offset=4))

        self._run(session, manager)

        assert session.post.call_args_list[0].kwargs["json"]["offset"] == 4

    def test_orders_on_gsid_only_when_the_object_reports_it_sortable(self) -> None:
        session = mock.MagicMock()
        session.get.return_value = _response(_describe_body([_field("Gsid", sortable=False)]))
        session.post.side_effect = [_response({"result": True, "data": []})]

        self._run(session, _manager())

        assert "orderBy" not in session.post.call_args_list[0].kwargs["json"]

    def test_partitions_on_created_date_when_the_object_has_one(self) -> None:
        session = mock.MagicMock()
        session.get.return_value = _response(_describe_body([_field("Gsid"), _field("CreatedDate", "DATETIME")]))

        with (
            mock.patch(SESSION_PATCH, return_value=session),
            mock.patch(HOST_CHECK_PATCH, return_value=(True, None)),
        ):
            response = gainsight_cs_source(
                domain=DOMAIN,
                access_key="key",
                schema_name="company",
                object_name="company",
                primary_keys=["Gsid"],
                team_id=1,
                resumable_source_manager=_manager(),
            )

        assert response.partition_keys == ["CreatedDate"]

    def test_refuses_a_host_that_resolves_internally(self) -> None:
        session = mock.MagicMock()
        with (
            mock.patch(SESSION_PATCH, return_value=session),
            mock.patch(HOST_CHECK_PATCH, return_value=(False, "Host not allowed")),
            pytest.raises(GainsightCsHostNotAllowedError),
        ):
            gainsight_cs_source(
                domain="internal.corp",
                access_key="key",
                schema_name="company",
                object_name="company",
                primary_keys=["Gsid"],
                team_id=1,
                resumable_source_manager=_manager(),
            )
        session.get.assert_not_called()


class TestValidateCredentials:
    def _validate(self, response: Response) -> tuple[bool, str | None]:
        session = mock.MagicMock()
        session.get.return_value = response
        with (
            mock.patch(SESSION_PATCH, return_value=session),
            mock.patch(HOST_CHECK_PATCH, return_value=(True, None)),
        ):
            return validate_credentials(DOMAIN, "key", "company", 1)

    @parameterized.expand(
        [
            ("unauthorized", 401, "rejected the access key"),
            ("forbidden", 403, "rejected the access key"),
            ("missing_object", 404, "no object named 'company'"),
            ("server_error", 500, "unexpected status (500)"),
        ]
    )
    def test_maps_each_status_to_the_message_a_user_reads(self, _name: str, status: int, expected: str) -> None:
        ok, error = self._validate(_response({}, status_code=status))
        assert ok is False
        assert error is not None and expected in error

    def test_accepts_a_describe_that_returns_fields(self) -> None:
        assert self._validate(_response(_describe_body([_field("Gsid")]))) == (True, None)

    def test_rejects_a_200_that_describes_nothing(self) -> None:
        ok, error = self._validate(_response(_describe_body([])))
        assert ok is False
        assert error is not None and "no fields for object" in error

    def test_rejects_a_redirect_rather_than_replaying_the_key(self) -> None:
        redirect = _response({}, status_code=302, headers={"Location": "https://evil.example.com/"})
        ok, error = self._validate(redirect)
        assert ok is False
        assert error is not None and "isn't allowed" in error

    def test_rejects_a_domain_that_resolves_internally(self) -> None:
        with mock.patch(HOST_CHECK_PATCH, return_value=(False, "Host not allowed")):
            assert validate_credentials("internal.corp", "key", "company", 1) == (False, "Host not allowed")

    def test_rejects_a_domain_that_is_not_a_hostname(self) -> None:
        ok, error = validate_credentials("acme corp.gainsightcloud.com", "key", "company", None)
        assert ok is False
        assert error is not None and "doesn't look like a Gainsight domain" in error
