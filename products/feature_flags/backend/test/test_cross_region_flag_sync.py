from posthog.test.base import BaseTest
from unittest.mock import Mock, patch

from django.test import override_settings

import requests
from parameterized import parameterized

from posthog.models.team import Team

from products.feature_flags.backend.cache_keys import EU_CROSS_REGION_MIRROR_CACHE_KEY
from products.feature_flags.backend.cross_region_flag_sync import sync_cross_region_flags
from products.feature_flags.backend.local_evaluation import clear_flag_definition_caches, flag_definitions_hypercache

_MODULE = "products.feature_flags.backend.cross_region_flag_sync"


def _mock_response(status_code: int, json_data: dict | list | None = None, json_error: bool = False) -> Mock:
    response = Mock()
    response.status_code = status_code
    if json_error:
        response.json.side_effect = ValueError("bad json")
    else:
        response.json.return_value = json_data
    return response


@override_settings(CLOUD_DEPLOYMENT="EU", POSTHOG_FLAGS_PROJECT_SECRET_TOKEN="phs_test_token")
class TestSyncCrossRegionFlags(BaseTest):
    def setUp(self):
        super().setUp()
        clear_flag_definition_caches(EU_CROSS_REGION_MIRROR_CACHE_KEY, kinds=["redis", "s3"])

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_no_op_outside_eu(self):
        # Every EU pod would otherwise re-poll the US API directly -- exactly the
        # per-pod polling this task exists to replace -- if this guard were dropped.
        with patch(f"{_MODULE}.requests.get") as mock_get:
            sync_cross_region_flags()

        mock_get.assert_not_called()

    @override_settings(POSTHOG_FLAGS_PROJECT_SECRET_TOKEN="")
    def test_no_op_without_token(self):
        # Before the charts secret is provisioned, this would otherwise send a
        # request with an empty bearer token every 30s.
        with patch(f"{_MODULE}.requests.get") as mock_get:
            sync_cross_region_flags()

        mock_get.assert_not_called()

    def test_sends_stored_etag_and_skips_write_on_304(self):
        # Regression guard for the sentinel-key fix: the etag that gates the
        # conditional GET must be read/written under EU_CROSS_REGION_MIRROR_CACHE_KEY,
        # not team id 2 -- a real, unrelated EU team's id.
        payload = {"flags": [{"key": "existing"}], "group_type_mapping": {}, "cohorts": {}}
        flag_definitions_hypercache.set_cache_value(EU_CROSS_REGION_MIRROR_CACHE_KEY, payload)
        local_etag = flag_definitions_hypercache.get_etag(EU_CROSS_REGION_MIRROR_CACHE_KEY)
        assert local_etag

        with (
            patch(f"{_MODULE}.requests.get", return_value=_mock_response(304)) as mock_get,
            patch.object(flag_definitions_hypercache, "set_cache_value") as mock_set,
        ):
            sync_cross_region_flags()

        url, kwargs = mock_get.call_args
        assert url[0] == "https://us.i.posthog.com/flags/definitions"
        assert kwargs["headers"]["Authorization"] == "Bearer phs_test_token"
        assert kwargs["headers"]["If-None-Match"] == f'"{local_etag}"'
        # 304 means unchanged -- a write here would defeat the point of sending the etag.
        mock_set.assert_not_called()

    def test_writes_fetched_payload_under_sentinel_key_without_clobbering_real_team(self):
        # The collision this change fixes: before the sentinel key, the sync wrote
        # under the plain team-id key 2, which is EU's own real, unrelated team.
        # A real team's cache entry must be untouched by this sync.
        real_team = Team.objects.create(organization=self.organization, id=2, name="Real EU team 2")
        real_team_payload = {"flags": [{"key": "real-eu-flag"}], "group_type_mapping": {}, "cohorts": {}}
        flag_definitions_hypercache.set_cache_value(real_team, real_team_payload)

        sync_payload = {"flags": [{"key": "mirrored-us-flag"}], "group_type_mapping": {}, "cohorts": {}}
        with patch(f"{_MODULE}.requests.get", return_value=_mock_response(200, sync_payload)):
            sync_cross_region_flags()

        assert flag_definitions_hypercache.get_from_cache(EU_CROSS_REGION_MIRROR_CACHE_KEY) == sync_payload
        # A write that doesn't arm the ETag would make every later tick skip the
        # conditional GET, silently degrading to a full transfer on every poll.
        assert flag_definitions_hypercache.get_etag(EU_CROSS_REGION_MIRROR_CACHE_KEY)
        assert flag_definitions_hypercache.get_from_cache(real_team) == real_team_payload

    @parameterized.expand(
        [
            ("connection_error", requests.ConnectionError("boom")),
            ("timeout", requests.Timeout("slow")),
            ("proxy_error", requests.exceptions.ProxyError("proxy down")),
        ]
    )
    def test_transient_network_error_is_not_captured(self, _name, exc):
        # These self-heal on the next 30s tick, so they must fail safe (keep the
        # cached entry) without reporting to error tracking -- otherwise every blip
        # spawns a "new issue".
        with (
            patch(f"{_MODULE}.requests.get", side_effect=exc),
            patch.object(flag_definitions_hypercache, "set_cache_value") as mock_set,
            patch(f"{_MODULE}.capture_exception_throttled") as mock_capture,
        ):
            sync_cross_region_flags()

        mock_set.assert_not_called()
        mock_capture.assert_not_called()

    def test_unexpected_request_error_is_captured(self):
        # A non-network RequestException (e.g. a malformed URL) is genuinely
        # unexpected, so it should still surface in error tracking.
        with (
            patch(f"{_MODULE}.requests.get", side_effect=requests.RequestException("unexpected")),
            patch.object(flag_definitions_hypercache, "set_cache_value") as mock_set,
            patch(f"{_MODULE}.capture_exception_throttled") as mock_capture,
        ):
            sync_cross_region_dogfood_flags()

        mock_set.assert_not_called()
        mock_capture.assert_called_once()

    @parameterized.expand(
        [
            ("server_error", 500, False, None),
            ("bad_json_body", 200, True, None),
            # A non-dict shape would otherwise be cached verbatim and served to every
            # EU pod until the next successful sync -- must fail safe like the others.
            ("unexpected_shape", 200, False, ["not", "a", "dict"]),
        ]
    )
    def test_fails_safe_on_bad_response(self, _name, status_code, json_error, json_data):
        with (
            patch(f"{_MODULE}.requests.get", return_value=_mock_response(status_code, json_data, json_error)),
            patch.object(flag_definitions_hypercache, "set_cache_value") as mock_set,
        ):
            sync_cross_region_flags()

        mock_set.assert_not_called()
