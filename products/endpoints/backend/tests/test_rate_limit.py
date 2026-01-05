from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import TestCase

from parameterized import parameterized

from products.data_warehouse.backend.models import DataWarehouseSavedQuery
from products.endpoints.backend.models import Endpoint
from products.endpoints.backend.rate_limit import (
    EndpointBurstThrottle,
    EndpointSustainedThrottle,
    _check_and_cache_materialization_status,
    _is_materialized_endpoint_request,
    clear_endpoint_materialization_cache,
    is_endpoint_materialization_ready,
    set_endpoint_materialization_ready,
)


class TestMaterializationCache(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_cache_miss_returns_none(self):
        self.assertIsNone(is_endpoint_materialization_ready(123, "nonexistent"))

    @parameterized.expand([(True,), (False,)])
    def test_set_and_get_materialization_status(self, is_ready):
        set_endpoint_materialization_ready(123, "test_endpoint", is_ready)
        self.assertEqual(is_endpoint_materialization_ready(123, "test_endpoint"), is_ready)

    def test_clear_cache(self):
        set_endpoint_materialization_ready(123, "test_endpoint", True)
        clear_endpoint_materialization_cache(123, "test_endpoint")
        self.assertIsNone(is_endpoint_materialization_ready(123, "test_endpoint"))


class TestCheckAndCacheMaterializationStatus(APIBaseTest):
    def setUp(self):
        super().setUp()
        cache.clear()

    def tearDown(self):
        cache.clear()
        super().tearDown()

    def test_nonexistent_endpoint_returns_false(self):
        self.assertFalse(_check_and_cache_materialization_status(self.team.id, "nonexistent"))

    def test_non_materialized_endpoint_returns_false_and_caches(self):
        Endpoint.objects.create(
            name="inline_endpoint",
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT 1"},
            created_by=self.user,
            is_active=True,
        )

        self.assertFalse(_check_and_cache_materialization_status(self.team.id, "inline_endpoint"))
        self.assertFalse(is_endpoint_materialization_ready(self.team.id, "inline_endpoint"))

    @parameterized.expand(
        [
            (DataWarehouseSavedQuery.Status.RUNNING, False),
            (DataWarehouseSavedQuery.Status.FAILED, False),
            (DataWarehouseSavedQuery.Status.COMPLETED, True),
        ]
    )
    def test_materialized_endpoint_status(self, status, expected_ready):
        saved_query = DataWarehouseSavedQuery.objects.create(
            name=f"query_{status}",
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT 1"},
            is_materialized=True,
            status=status,
            origin=DataWarehouseSavedQuery.Origin.ENDPOINT,
        )
        Endpoint.objects.create(
            name=f"endpoint_{status}",
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT 1"},
            created_by=self.user,
            is_active=True,
            saved_query=saved_query,
        )

        result = _check_and_cache_materialization_status(self.team.id, f"endpoint_{status}")
        self.assertEqual(result, expected_ready)
        self.assertEqual(is_endpoint_materialization_ready(self.team.id, f"endpoint_{status}"), expected_ready)


class TestIsMaterializedEndpointRequest(APIBaseTest):
    def setUp(self):
        super().setUp()
        cache.clear()

    def tearDown(self):
        cache.clear()
        super().tearDown()

    @parameterized.expand(
        [
            (None, "test"),  # no team_id
            (123, None),  # no endpoint_name (via empty kwargs)
        ]
    )
    def test_returns_false_when_missing_context(self, team_id, endpoint_name):
        request = MagicMock()
        view = MagicMock()
        view.team_id = team_id
        view.kwargs = {"name": endpoint_name} if endpoint_name else {}

        self.assertFalse(_is_materialized_endpoint_request(request, view))

    def test_uses_cached_value(self):
        set_endpoint_materialization_ready(123, "test", True)

        request = MagicMock()
        view = MagicMock()
        view.team_id = 123
        view.kwargs = {"name": "test"}

        self.assertTrue(_is_materialized_endpoint_request(request, view))

    def test_lazy_loads_on_cache_miss(self):
        saved_query = DataWarehouseSavedQuery.objects.create(
            name="lazy_query",
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT 1"},
            is_materialized=True,
            status=DataWarehouseSavedQuery.Status.COMPLETED,
            origin=DataWarehouseSavedQuery.Origin.ENDPOINT,
        )
        Endpoint.objects.create(
            name="lazy_endpoint",
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT 1"},
            created_by=self.user,
            is_active=True,
            saved_query=saved_query,
        )

        self.assertIsNone(is_endpoint_materialization_ready(self.team.id, "lazy_endpoint"))

        request = MagicMock()
        view = MagicMock()
        view.team_id = self.team.id
        view.kwargs = {"name": "lazy_endpoint"}

        self.assertTrue(_is_materialized_endpoint_request(request, view))
        self.assertTrue(is_endpoint_materialization_ready(self.team.id, "lazy_endpoint"))


class TestEndpointThrottles(APIBaseTest):
    def setUp(self):
        super().setUp()
        cache.clear()

    def tearDown(self):
        cache.clear()
        super().tearDown()

    def test_uses_api_queries_scope_for_non_materialized(self):
        throttle = EndpointBurstThrottle()

        request = MagicMock()
        view = MagicMock()
        view.team_id = 999
        view.kwargs = {"name": "nonexistent"}

        with patch.object(throttle, "allow_request", wraps=throttle.allow_request):
            throttle.allow_request(request, view)

        self.assertEqual(throttle.scope, "api_queries_burst")

    def test_uses_materialized_scope_when_materialized(self):
        set_endpoint_materialization_ready(self.team.id, "mat_endpoint", True)

        for throttle_class, expected_scope in [
            (EndpointBurstThrottle, "materialized_endpoint_burst"),
            (EndpointSustainedThrottle, "materialized_endpoint_sustained"),
        ]:
            throttle = throttle_class()
            request = MagicMock()
            view = MagicMock()
            view.team_id = self.team.id
            view.kwargs = {"name": "mat_endpoint"}

            throttle.allow_request(request, view)

            self.assertEqual(throttle.scope, expected_scope)
