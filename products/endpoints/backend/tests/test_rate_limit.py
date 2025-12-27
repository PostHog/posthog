from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import TestCase

from products.data_warehouse.backend.models import DataWarehouseSavedQuery
from products.endpoints.backend.models import Endpoint
from products.endpoints.backend.rate_limit import (
    INLINE_BURST_RATE,
    INLINE_SUSTAINED_RATE,
    MATERIALIZED_BURST_RATE,
    MATERIALIZED_SUSTAINED_RATE,
    EndpointBurstThrottle,
    EndpointSustainedThrottle,
    _check_and_cache_materialization_status,
    _is_materialized_endpoint_request,
    clear_endpoint_materialization_cache,
    get_endpoint_materialization_cache_key,
    is_endpoint_materialization_ready,
    set_endpoint_materialization_ready,
)


class TestMaterializationCacheHelpers(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_get_cache_key_format(self):
        cache_key = get_endpoint_materialization_cache_key(123, "my_endpoint")
        self.assertEqual(cache_key, "endpoint_materialized_ready:123:my_endpoint")

    def test_is_endpoint_materialization_ready_returns_none_on_miss(self):
        result = is_endpoint_materialization_ready(123, "nonexistent")
        self.assertIsNone(result)

    def test_set_and_get_materialization_ready_true(self):
        set_endpoint_materialization_ready(123, "test_endpoint", True)
        result = is_endpoint_materialization_ready(123, "test_endpoint")
        self.assertTrue(result)

    def test_set_and_get_materialization_ready_false(self):
        set_endpoint_materialization_ready(123, "test_endpoint", False)
        result = is_endpoint_materialization_ready(123, "test_endpoint")
        self.assertFalse(result)

    def test_clear_cache(self):
        set_endpoint_materialization_ready(123, "test_endpoint", True)
        self.assertTrue(is_endpoint_materialization_ready(123, "test_endpoint"))

        clear_endpoint_materialization_cache(123, "test_endpoint")
        self.assertIsNone(is_endpoint_materialization_ready(123, "test_endpoint"))


class TestCheckAndCacheMaterializationStatus(APIBaseTest):
    def setUp(self):
        super().setUp()
        cache.clear()

    def tearDown(self):
        cache.clear()
        super().tearDown()

    def test_returns_false_for_nonexistent_endpoint(self):
        result = _check_and_cache_materialization_status(self.team.id, "nonexistent")
        self.assertFalse(result)

    def test_returns_false_for_non_materialized_endpoint(self):
        endpoint = Endpoint.objects.create(
            name="inline_endpoint",
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT 1"},
            created_by=self.user,
            is_active=True,
        )

        result = _check_and_cache_materialization_status(self.team.id, endpoint.name)
        self.assertFalse(result)
        self.assertFalse(is_endpoint_materialization_ready(self.team.id, endpoint.name))

    def test_returns_false_for_materialized_but_not_completed(self):
        saved_query = DataWarehouseSavedQuery.objects.create(
            name="test_query",
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT 1"},
            is_materialized=True,
            status=DataWarehouseSavedQuery.Status.RUNNING,
            origin=DataWarehouseSavedQuery.Origin.ENDPOINT,
        )
        endpoint = Endpoint.objects.create(
            name="running_endpoint",
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT 1"},
            created_by=self.user,
            is_active=True,
            saved_query=saved_query,
        )

        result = _check_and_cache_materialization_status(self.team.id, endpoint.name)
        self.assertFalse(result)
        self.assertFalse(is_endpoint_materialization_ready(self.team.id, endpoint.name))

    def test_returns_true_for_completed_materialized_endpoint(self):
        saved_query = DataWarehouseSavedQuery.objects.create(
            name="completed_query",
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT 1"},
            is_materialized=True,
            status=DataWarehouseSavedQuery.Status.COMPLETED,
            origin=DataWarehouseSavedQuery.Origin.ENDPOINT,
        )
        endpoint = Endpoint.objects.create(
            name="materialized_endpoint",
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT 1"},
            created_by=self.user,
            is_active=True,
            saved_query=saved_query,
        )

        result = _check_and_cache_materialization_status(self.team.id, endpoint.name)
        self.assertTrue(result)
        self.assertTrue(is_endpoint_materialization_ready(self.team.id, endpoint.name))


class TestIsMaterializedEndpointRequest(APIBaseTest):
    def setUp(self):
        super().setUp()
        cache.clear()

    def tearDown(self):
        cache.clear()
        super().tearDown()

    def test_returns_false_when_no_team_id(self):
        request = MagicMock()
        view = MagicMock()
        view.team_id = None
        view.kwargs = {"name": "test"}

        result = _is_materialized_endpoint_request(request, view)
        self.assertFalse(result)

    def test_returns_false_when_no_endpoint_name(self):
        request = MagicMock()
        view = MagicMock()
        view.team_id = 123
        view.kwargs = {}

        result = _is_materialized_endpoint_request(request, view)
        self.assertFalse(result)

    def test_returns_cached_true_value(self):
        set_endpoint_materialization_ready(123, "test", True)

        request = MagicMock()
        view = MagicMock()
        view.team_id = 123
        view.kwargs = {"name": "test"}

        result = _is_materialized_endpoint_request(request, view)
        self.assertTrue(result)

    def test_returns_cached_false_value(self):
        set_endpoint_materialization_ready(123, "test", False)

        request = MagicMock()
        view = MagicMock()
        view.team_id = 123
        view.kwargs = {"name": "test"}

        result = _is_materialized_endpoint_request(request, view)
        self.assertFalse(result)

    def test_lazy_loads_on_cache_miss(self):
        saved_query = DataWarehouseSavedQuery.objects.create(
            name="lazy_load_query",
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT 1"},
            is_materialized=True,
            status=DataWarehouseSavedQuery.Status.COMPLETED,
            origin=DataWarehouseSavedQuery.Origin.ENDPOINT,
        )
        endpoint = Endpoint.objects.create(
            name="lazy_load_endpoint",
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT 1"},
            created_by=self.user,
            is_active=True,
            saved_query=saved_query,
        )

        self.assertIsNone(is_endpoint_materialization_ready(self.team.id, endpoint.name))

        request = MagicMock()
        view = MagicMock()
        view.team_id = self.team.id
        view.kwargs = {"name": endpoint.name}

        result = _is_materialized_endpoint_request(request, view)
        self.assertTrue(result)
        self.assertTrue(is_endpoint_materialization_ready(self.team.id, endpoint.name))


class TestEndpointThrottles(APIBaseTest):
    def setUp(self):
        super().setUp()
        cache.clear()

    def tearDown(self):
        cache.clear()
        super().tearDown()

    def test_burst_throttle_uses_inline_rate_by_default(self):
        throttle = EndpointBurstThrottle()

        request = MagicMock()
        view = MagicMock()
        view.team_id = 999
        view.kwargs = {"name": "nonexistent"}

        with patch.object(throttle, "allow_request", wraps=throttle.allow_request):
            throttle.allow_request(request, view)

        self.assertEqual(throttle.rate, INLINE_BURST_RATE)
        self.assertEqual(throttle.scope, "endpoint_burst")

    def test_burst_throttle_uses_materialized_rate_when_cached_true(self):
        set_endpoint_materialization_ready(self.team.id, "mat_endpoint", True)
        throttle = EndpointBurstThrottle()

        request = MagicMock()
        view = MagicMock()
        view.team_id = self.team.id
        view.kwargs = {"name": "mat_endpoint"}

        with patch.object(EndpointBurstThrottle, "allow_request", return_value=True):
            throttle.allow_request(request, view)

        self.assertEqual(throttle.rate, MATERIALIZED_BURST_RATE)
        self.assertEqual(throttle.scope, "materialized_endpoint_burst")

    def test_sustained_throttle_uses_inline_rate_by_default(self):
        throttle = EndpointSustainedThrottle()

        request = MagicMock()
        view = MagicMock()
        view.team_id = 999
        view.kwargs = {"name": "nonexistent"}

        with patch.object(throttle, "allow_request", wraps=throttle.allow_request):
            throttle.allow_request(request, view)

        self.assertEqual(throttle.rate, INLINE_SUSTAINED_RATE)
        self.assertEqual(throttle.scope, "endpoint_sustained")

    def test_sustained_throttle_uses_materialized_rate_when_cached_true(self):
        set_endpoint_materialization_ready(self.team.id, "mat_endpoint", True)
        throttle = EndpointSustainedThrottle()

        request = MagicMock()
        view = MagicMock()
        view.team_id = self.team.id
        view.kwargs = {"name": "mat_endpoint"}

        with patch.object(EndpointSustainedThrottle, "allow_request", return_value=True):
            throttle.allow_request(request, view)

        self.assertEqual(throttle.rate, MATERIALIZED_SUSTAINED_RATE)
        self.assertEqual(throttle.scope, "materialized_endpoint_sustained")
