from datetime import UTC, datetime
from typing import Any, cast

from unittest.mock import Mock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cortex.cortex import (
    _encode_entity_tag,
    _flatten_relationship,
    _flatten_scorecard_score,
    _format_cortex_datetime,
    _normalize_dependency,
    cortex_source,
    get_resource,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cortex.settings import CORTEX_ENDPOINTS


class _FakeDltResource:
    def __init__(self, name: str, rows: list[dict]) -> None:
        self.name = name
        self._rows = rows

    def add_map(self, mapper: Any) -> "_FakeDltResource":
        self._rows = [mapper(dict(row)) for row in self._rows]
        return self

    def __iter__(self) -> Any:
        return iter(self._rows)


class TestCortexTransport:
    @parameterized.expand(
        [
            ("unauthorized", 401, None, False),
            ("forbidden_at_create", 403, None, True),
            ("forbidden_for_schema", 403, "entities", False),
            ("ok", 200, None, True),
            ("unexpected", 500, None, False),
        ]
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.cortex.cortex.make_tracked_session")
    def test_validate_credentials_status_mapping(
        self, _name: str, status_code: int, schema_name: str | None, expected_ok: bool, mock_session: Mock
    ) -> None:
        response = Mock(status_code=status_code)
        mock_session.return_value.get.return_value = response

        is_valid, _message = validate_credentials(api_key="cx_key", schema_name=schema_name)

        assert is_valid is expected_ok

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.cortex.cortex.make_tracked_session")
    def test_validate_credentials_probes_catalog_with_bearer(self, mock_session: Mock) -> None:
        mock_session.return_value.get.return_value = Mock(status_code=200)

        validate_credentials(api_key="cx_key")

        call = mock_session.return_value.get.call_args
        assert call.args[0] == "https://api.getcortexapp.com/api/v1/catalog"
        assert call.kwargs["headers"]["Authorization"] == "Bearer cx_key"
        assert call.kwargs["params"] == {"page": 0, "pageSize": 1}

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.cortex.cortex.make_tracked_session")
    def test_validate_credentials_handles_request_exception(self, mock_session: Mock) -> None:
        mock_session.return_value.get.side_effect = requests.exceptions.RequestException("boom")
        is_valid, message = validate_credentials(api_key="cx_key")
        assert is_valid is False
        assert message is not None and "boom" in message

    def test_get_resource_entities_page_number_paginated(self) -> None:
        resource = cast(dict[str, Any], get_resource(CORTEX_ENDPOINTS["entities"]))
        assert resource["name"] == "entities"
        assert resource["write_disposition"] == "replace"
        assert resource["endpoint"]["path"] == "/catalog"
        assert resource["endpoint"]["data_selector"] == "entities"
        assert resource["endpoint"]["params"] == {"pageSize": 250}
        paginator = resource["endpoint"]["paginator"]
        assert isinstance(paginator, PageNumberPaginator)
        assert paginator.total_path == "totalPages"

    def test_get_resource_teams_single_page(self) -> None:
        resource = cast(dict[str, Any], get_resource(CORTEX_ENDPOINTS["teams"]))
        assert resource["endpoint"]["data_selector"] == "teams"
        assert resource["endpoint"]["params"] == {}
        assert isinstance(resource["endpoint"]["paginator"], SinglePagePaginator)

    @parameterized.expand(
        [
            # `includeDrafts` and `includeExpired` both default to false, so leaving them off
            # would silently drop Initiatives from the table.
            (
                "initiatives",
                {"pageSize": 250, "includeDrafts": "true", "includeExpired": "true"},
                PageNumberPaginator,
            ),
            ("team_hierarchies", {}, SinglePagePaginator),
        ]
    )
    def test_get_resource_sends_the_declared_list_params(
        self, name: str, expected_params: dict[str, Any], paginator_type: type
    ) -> None:
        resource = cast(dict[str, Any], get_resource(CORTEX_ENDPOINTS[name]))
        assert resource["endpoint"]["params"] == expected_params
        assert isinstance(resource["endpoint"]["paginator"], paginator_type)

    @parameterized.expand(list(CORTEX_ENDPOINTS.keys()))
    def test_get_resource_matches_declared_primary_key_and_endpoint(self, name: str) -> None:
        config = CORTEX_ENDPOINTS[name]
        resource = cast(dict[str, Any], get_resource(config))
        assert resource["name"] == name
        assert resource["endpoint"]["path"] == config.path

    def test_flatten_scorecard_score_pulls_service_identifiers(self) -> None:
        item = {"service": {"tag": "svc-a", "id": "cid123", "name": "Service A"}, "score": {"summary": {"score": 90}}}
        flattened = _flatten_scorecard_score(item)
        assert flattened["service_tag"] == "svc-a"
        assert flattened["service_id"] == "cid123"
        assert flattened["service_name"] == "Service A"

    def test_flatten_scorecard_score_handles_missing_service(self) -> None:
        flattened = _flatten_scorecard_score({})
        assert flattened["service_tag"] is None
        assert flattened["service_id"] is None

    def test_flatten_relationship_pulls_source_and_destination_identifiers(self) -> None:
        item = {
            "relationshipTypeTag": "depends-on",
            "sourceEntity": {"tag": "service-a", "id": "cid1"},
            "destinationEntity": {"tag": "service-b", "id": "cid2"},
        }
        flattened = _flatten_relationship(item)
        assert flattened["source_entity_tag"] == "service-a"
        assert flattened["source_entity_id"] == "cid1"
        assert flattened["destination_entity_tag"] == "service-b"
        assert flattened["destination_entity_id"] == "cid2"

    def test_flatten_relationship_handles_missing_entities(self) -> None:
        flattened = _flatten_relationship({})
        assert flattened["source_entity_tag"] is None
        assert flattened["destination_entity_tag"] is None

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.cortex.cortex.rest_api_resource")
    def test_cortex_source_entities_top_level(self, mock_rest_api_resource: Mock) -> None:
        mock_rest_api_resource.return_value = Mock()
        response = cortex_source(api_key="cx_key", endpoint="entities", team_id=1, job_id="job-1")

        assert response.name == "entities"
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"
        assert response.partition_keys is None

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.cortex.cortex.rest_api_resource")
    def test_cortex_source_scorecards_partitions_on_date_created(self, mock_rest_api_resource: Mock) -> None:
        mock_rest_api_resource.return_value = Mock()
        response = cortex_source(api_key="cx_key", endpoint="scorecards", team_id=1, job_id="job-1")

        assert response.primary_keys == ["tag"]
        assert response.partition_keys == ["dateCreated"]
        assert response.partition_mode == "datetime"

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.cortex.cortex.build_dependent_resource")
    def test_cortex_source_scorecard_scores_fanout_flattens_and_injects_parent_tag(
        self, mock_build_dependent_resource: Mock
    ) -> None:
        # `build_dependent_resource` has already applied its own parent-field rename by the time
        # it returns, so the fake child row carries the renamed `scorecard_tag` (not the raw
        # `_scorecards_tag`); this test only exercises our own `_flatten_scorecard_score` add_map.
        mock_build_dependent_resource.return_value = _FakeDltResource(
            "scorecard_scores",
            [{"service": {"tag": "svc-a", "id": "cid1"}, "scorecard_tag": "scorecard-1"}],
        )

        response = cortex_source(api_key="cx_key", endpoint="scorecard_scores", team_id=1, job_id="job-1")
        rows = list(cast(Any, response.items()))

        assert rows == [
            {
                "service": {"tag": "svc-a", "id": "cid1"},
                "scorecard_tag": "scorecard-1",
                "service_tag": "svc-a",
                "service_id": "cid1",
                "service_name": None,
            }
        ]
        assert response.primary_keys == ["scorecard_tag", "service_tag"]

        kwargs = mock_build_dependent_resource.call_args.kwargs
        assert kwargs["fanout"].parent_name == "scorecards"
        assert kwargs["fanout"].resolve_param == "tag"
        assert kwargs["should_use_incremental_field"] is False
        assert kwargs["db_incremental_field_last_value"] is None
        assert kwargs["child_endpoint_extra"]["data_selector"] == "serviceScores"
        assert isinstance(kwargs["parent_endpoint_extra"]["paginator"], PageNumberPaginator)

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.cortex.cortex.build_dependent_resource")
    def test_cortex_source_relationships_fanout_flattens_entities(self, mock_build_dependent_resource: Mock) -> None:
        mock_build_dependent_resource.return_value = _FakeDltResource(
            "relationships",
            [
                {
                    "relationshipTypeTag": "depends-on",
                    "sourceEntity": {"tag": "service-a"},
                    "destinationEntity": {"tag": "service-b"},
                }
            ],
        )

        response = cortex_source(api_key="cx_key", endpoint="relationships", team_id=1, job_id="job-1")
        rows = list(cast(Any, response.items()))

        assert rows[0]["source_entity_tag"] == "service-a"
        assert rows[0]["destination_entity_tag"] == "service-b"
        assert response.primary_keys == ["relationship_type_tag", "source_entity_tag", "destination_entity_tag"]

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout.rest_api_resources"
    )
    def test_cortex_source_relationships_fanout_injects_parent_relationship_type_tag(
        self, mock_rest_api_resources: Mock
    ) -> None:
        mock_rest_api_resources.return_value = [
            _FakeDltResource("relationship_types", [{"tag": "depends-on"}]),
            _FakeDltResource(
                "relationships",
                [
                    {
                        "sourceEntity": {"tag": "service-a"},
                        "destinationEntity": {"tag": "service-b"},
                        "_relationship_types_tag": "depends-on",
                    }
                ],
            ),
        ]

        response = cortex_source(api_key="cx_key", endpoint="relationships", team_id=1, job_id="job-1")
        rows = list(cast(Any, response.items()))

        assert rows[0]["relationship_type_tag"] == "depends-on"

    @parameterized.expand(
        [
            ("plain", "payments-api", "payments-api"),
            ("slashes", "/services/payments-api", "%2Fservices%2Fpayments-api"),
            ("space_and_colon", "payments api:v2", "payments%20api%3Av2"),
            ("missing", None, ""),
        ]
    )
    def test_encode_entity_tag_makes_the_tag_addressable(self, _name: str, tag: str | None, expected: str) -> None:
        # Cortex matches a tag exactly as encoded, so an unencoded slash addresses the wrong path.
        assert _encode_entity_tag({"tag": tag})["tag_encoded"] == expected

    @parameterized.expand(
        [
            ("absent", {}, "", ""),
            ("null", {"method": None, "path": None}, "", ""),
            ("present", {"method": "GET", "path": "/2.0/users"}, "GET", "/2.0/users"),
        ]
    )
    def test_normalize_dependency_fills_the_key_columns(
        self, _name: str, item: dict[str, Any], method: str, path: str
    ) -> None:
        normalized = _normalize_dependency(dict(item))
        assert normalized["method"] == method
        assert normalized["path"] == path

    def test_format_cortex_datetime_drops_the_zone(self) -> None:
        # Cortex documents startTime as a date-time without a time zone.
        assert _format_cortex_datetime(datetime(2024, 3, 1, 9, 30, tzinfo=UTC)) == "2024-03-01T09:30:00"

    def test_format_cortex_datetime_caps_a_future_cursor_at_now(self) -> None:
        formatted = _format_cortex_datetime(datetime(2999, 1, 1, tzinfo=UTC))
        assert formatted <= datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.cortex.cortex.rest_api_resource")
    def test_cortex_source_users_partitions_on_joined_at(self, mock_rest_api_resource: Mock) -> None:
        mock_rest_api_resource.return_value = Mock()
        response = cortex_source(api_key="cx_key", endpoint="users", team_id=1, job_id="job-1")

        assert response.primary_keys == ["email"]
        assert response.partition_keys == ["joinedAt"]
        assert response.sort_mode == "asc"

    @parameterized.expand(["custom_events", "deploys", "dependencies", "entity_groups"])
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.cortex.cortex.build_dependent_resource")
    def test_entity_fanouts_bind_the_encoded_tag(
        self, endpoint: str, mock_build_dependent_resource: Mock, *_: Any
    ) -> None:
        mock_build_dependent_resource.return_value = _FakeDltResource(endpoint, [])

        cortex_source(api_key="cx_key", endpoint=endpoint, team_id=1, job_id="job-1")

        kwargs = mock_build_dependent_resource.call_args.kwargs
        assert kwargs["fanout"].parent_name == "entities"
        assert kwargs["fanout"].resolve_field == "tag_encoded"
        # Without the parent map the derived resolve field never exists on a parent row.
        assert kwargs["parent_data_map"] is _encode_entity_tag

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.cortex.cortex.build_dependent_resource")
    def test_cortex_source_custom_events_incremental_passes_the_watermark(
        self, mock_build_dependent_resource: Mock
    ) -> None:
        mock_build_dependent_resource.return_value = _FakeDltResource("custom_events", [])

        response = cortex_source(
            api_key="cx_key",
            endpoint="custom_events",
            team_id=1,
            job_id="job-1",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 3, 1, tzinfo=UTC),
            incremental_field="timestamp",
        )

        kwargs = mock_build_dependent_resource.call_args.kwargs
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["incremental_field"] == "timestamp"
        assert kwargs["db_incremental_field_last_value"] == datetime(2024, 3, 1, tzinfo=UTC)
        window = kwargs["incremental_config_factory"]("timestamp")
        assert window["start_param"] == "startTime"
        assert window["cursor_path"] == "timestamp"
        # Fan-out rows arrive grouped per entity, so the watermark may only commit once the whole
        # run is done — an asc sync would checkpoint one entity's latest event over every entity
        # it has not reached yet.
        assert response.sort_mode == "desc"

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.cortex.cortex.build_dependent_resource")
    def test_cortex_source_custom_events_full_refresh_omits_the_watermark(
        self, mock_build_dependent_resource: Mock
    ) -> None:
        mock_build_dependent_resource.return_value = _FakeDltResource("custom_events", [])

        cortex_source(api_key="cx_key", endpoint="custom_events", team_id=1, job_id="job-1")

        kwargs = mock_build_dependent_resource.call_args.kwargs
        assert kwargs["should_use_incremental_field"] is False
        assert kwargs["db_incremental_field_last_value"] is None

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.cortex.cortex.build_dependent_resource")
    def test_cortex_source_dependencies_requests_outgoing_edges_only(self, mock_build_dependent_resource: Mock) -> None:
        mock_build_dependent_resource.return_value = _FakeDltResource(
            "dependencies", [{"callerTag": "a", "calleeTag": "b"}]
        )

        response = cortex_source(api_key="cx_key", endpoint="dependencies", team_id=1, job_id="job-1")
        rows = list(cast(Any, response.items()))

        # Each edge is listed by both of its endpoints; pulling incoming edges too would fetch
        # every edge twice, under two different callers.
        assert mock_build_dependent_resource.call_args.kwargs["fanout"].child_params == {
            "includeOutgoing": "true",
            "includeIncoming": "false",
        }
        assert rows[0]["method"] == "" and rows[0]["path"] == ""
        assert response.primary_keys == ["callerTag", "calleeTag", "method", "path"]

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.cortex.cortex.build_dependent_resource")
    def test_entity_groups_keys_membership_on_a_column_the_fanout_injects(
        self, mock_build_dependent_resource: Mock
    ) -> None:
        # A group row carries only the group's own tag. If the parent rename stops producing
        # `entity_id`, the key column is never populated and every entity in a group merges
        # onto one row.
        mock_build_dependent_resource.return_value = _FakeDltResource("entity_groups", [{"tag": "tier-1"}])

        response = cortex_source(api_key="cx_key", endpoint="entity_groups", team_id=1, job_id="job-1")

        injected = set(mock_build_dependent_resource.call_args.kwargs["fanout"].parent_field_renames.values())
        assert set(response.primary_keys or []) - {"tag"} <= injected
