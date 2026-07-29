from typing import Any, cast

from unittest.mock import Mock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cortex.cortex import (
    _flatten_relationship,
    _flatten_scorecard_score,
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
