from datetime import timedelta

import pytest
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest import mock

from django.utils import timezone

from rest_framework import status
from rest_framework.response import Response

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.endpoints.backend.logic.execution import EndpointExecutionService
from products.endpoints.backend.tests.conftest import create_endpoint_with_version
from products.warehouse_sources.backend.facade.models import DataWarehouseTable

pytestmark = [pytest.mark.django_db]


class TestStaleFallbackRequiredVariables(ClickhouseTestMixin, APIBaseTest):
    """Verification: required-variable enforcement is keyed on the version's materialization
    CONFIG, not on which execution path serves the request — so the stale-materialization
    fallback to inline cannot be used to bypass required breakdown variables."""

    def _create_stale_materialized_trends_endpoint(self, name: str) -> None:
        trends_query = {
            "kind": "TrendsQuery",
            "series": [{"kind": "EventsNode", "event": "$pageview", "math": "total"}],
            "dateRange": {"date_from": "-7d"},
            "interval": "day",
            "breakdownFilter": {
                "breakdowns": [{"property": "$browser", "type": "event"}],
                "breakdown_limit": 5,
            },
        }
        _create_event(team=self.team, event="$pageview", distinct_id="user1")
        flush_persons_and_events()

        endpoint = create_endpoint_with_version(
            name=name,
            team=self.team,
            query=trends_query,
            created_by=self.user,
            is_active=True,
        )
        response = self.client.patch(
            f"/api/environments/{self.team.id}/endpoints/{endpoint.name}/",
            {"is_materialized": True, "data_freshness_seconds": 3600},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, response.json()

        version = endpoint.versions.first()
        version.refresh_from_db()
        saved_query = version.saved_query
        assert saved_query is not None
        saved_query.status = DataWarehouseSavedQuery.Status.COMPLETED
        # Materialized 2h ago with a 1h freshness target -> stale -> inline fallback.
        saved_query.last_run_at = timezone.now() - timedelta(hours=2)
        saved_query.table = DataWarehouseTable.objects.create(
            team=self.team,
            name=name,
            format=DataWarehouseTable.TableFormat.Parquet,
            url_pattern=f"s3://test-bucket/{name}",
        )
        saved_query.save()

    def test_stale_fallback_missing_required_variable_still_400s(self):
        self._create_stale_materialized_trends_endpoint("stale_required_check")

        with (
            mock.patch.object(
                EndpointExecutionService, "_execute_materialized_endpoint", return_value=Response({})
            ) as mock_materialized,
            mock.patch.object(
                EndpointExecutionService, "_execute_inline_endpoint", return_value=Response({})
            ) as mock_inline,
        ):
            response = self.client.post(
                f"/api/environments/{self.team.id}/endpoints/stale_required_check/run",
                {},
                format="json",
            )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert "Required variable" in str(response.json())
        mock_inline.assert_not_called()
        mock_materialized.assert_not_called()

    def test_stale_fallback_with_required_variable_serves_inline(self):
        self._create_stale_materialized_trends_endpoint("stale_required_provided")

        with (
            mock.patch.object(
                EndpointExecutionService, "_execute_materialized_endpoint", return_value=Response({})
            ) as mock_materialized,
            mock.patch.object(
                EndpointExecutionService, "_execute_inline_endpoint", return_value=Response({})
            ) as mock_inline,
        ):
            response = self.client.post(
                f"/api/environments/{self.team.id}/endpoints/stale_required_provided/run",
                {"variables": {"$browser": "Chrome"}},
                format="json",
            )

        assert response.status_code == status.HTTP_200_OK, response.json()
        mock_inline.assert_called_once()
        mock_materialized.assert_not_called()

    def test_materialized_exception_fallback_happens_after_validation(self):
        """The mid-flight fallback (materialized executor raising) also can't bypass
        enforcement: with the variable missing, validation 400s before any executor runs,
        so the raising materialized path is never even reached."""
        self._create_stale_materialized_trends_endpoint("exception_fallback_check")
        # Make it fresh so the materialized path is selected, then blow it up mid-flight.
        version = None
        from products.endpoints.backend.models import Endpoint

        endpoint = Endpoint.objects.get(team=self.team, name="exception_fallback_check")
        version = endpoint.versions.first()
        version.saved_query.last_run_at = timezone.now()
        version.saved_query.save(update_fields=["last_run_at"])

        with (
            mock.patch.object(
                EndpointExecutionService, "_execute_materialized_endpoint", side_effect=RuntimeError("boom")
            ) as mock_materialized,
            mock.patch.object(
                EndpointExecutionService, "_execute_inline_endpoint", return_value=Response({})
            ) as mock_inline,
        ):
            # Missing required variable: 400 before either executor runs.
            response = self.client.post(
                f"/api/environments/{self.team.id}/endpoints/exception_fallback_check/run",
                {},
                format="json",
            )
            assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
            mock_materialized.assert_not_called()
            mock_inline.assert_not_called()

            # Variable provided: materialized path raises, inline serves the (validated) request.
            response = self.client.post(
                f"/api/environments/{self.team.id}/endpoints/exception_fallback_check/run",
                {"variables": {"$browser": "Chrome"}},
                format="json",
            )
            assert response.status_code == status.HTTP_200_OK, response.json()
            mock_materialized.assert_called_once()
            mock_inline.assert_called_once()
