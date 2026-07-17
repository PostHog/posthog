from posthog.test.base import BaseTest
from unittest.mock import Mock, patch

from django.test import override_settings

import requests
from parameterized import parameterized

from products.feature_flags.backend.cross_region_flag_sync import DOGFOOD_SELF_TEAM_ID, sync_cross_region_dogfood_flags
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
class TestSyncCrossRegionDogfoodFlags(BaseTest):
    def setUp(self):
        super().setUp()
        clear_flag_definition_caches(DOGFOOD_SELF_TEAM_ID, kinds=["redis", "s3"])

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_no_op_outside_eu(self):
        # Every EU pod would otherwise re-poll the US API directly -- exactly the
        # per-pod polling this task exists to replace -- if this guard were dropped.
        with patch(f"{_MODULE}.requests.get") as mock_get:
            sync_cross_region_dogfood_flags()

        mock_get.assert_not_called()

    @override_settings(POSTHOG_FLAGS_PROJECT_SECRET_TOKEN="")
    def test_no_op_without_token(self):
        # Before the charts secret is provisioned, this would otherwise send a
        # request with an empty bearer token every 30s.
        with patch(f"{_MODULE}.requests.get") as mock_get:
            sync_cross_region_dogfood_flags()

        mock_get.assert_not_called()

    def test_sends_stored_etag_and_skips_write_on_304(self):
        payload = {"flags": [{"key": "existing"}], "group_type_mapping": {}, "cohorts": {}}
        flag_definitions_hypercache.set_cache_value(DOGFOOD_SELF_TEAM_ID, payload)
        local_etag = flag_definitions_hypercache.get_etag(DOGFOOD_SELF_TEAM_ID)
        assert local_etag

        with (
            patch(f"{_MODULE}.requests.get", return_value=_mock_response(304)) as mock_get,
            patch.object(flag_definitions_hypercache, "set_cache_value") as mock_set,
        ):
            sync_cross_region_dogfood_flags()

        url, kwargs = mock_get.call_args
        assert url[0] == "https://us.i.posthog.com/flags/definitions"
        assert kwargs["headers"]["Authorization"] == "Bearer phs_test_token"
        assert kwargs["headers"]["If-None-Match"] == f'"{local_etag}"'
        # 304 means unchanged -- a write here would defeat the point of sending the etag.
        mock_set.assert_not_called()

    def test_writes_fetched_payload_on_200(self):
        payload = {"flags": [{"key": "new-flag"}], "group_type_mapping": {}, "cohorts": {}}

        with patch(f"{_MODULE}.requests.get", return_value=_mock_response(200, payload)):
            sync_cross_region_dogfood_flags()

        assert flag_definitions_hypercache.get_from_cache(DOGFOOD_SELF_TEAM_ID) == payload
        # A write that doesn't arm the ETag would make every later tick skip the
        # conditional GET, silently degrading to a full transfer on every poll.
        assert flag_definitions_hypercache.get_etag(DOGFOOD_SELF_TEAM_ID)

    def test_fails_safe_on_request_exception(self):
        # A crash here would take down the Celery task every 30s; the existing
        # cache entry must survive an upstream hiccup instead.
        with (
            patch(f"{_MODULE}.requests.get", side_effect=requests.ConnectionError("boom")),
            patch.object(flag_definitions_hypercache, "set_cache_value") as mock_set,
        ):
            sync_cross_region_dogfood_flags()

        mock_set.assert_not_called()

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
            sync_cross_region_dogfood_flags()

        mock_set.assert_not_called()
