import json
from contextlib import contextmanager

import pytest
from unittest.mock import MagicMock, Mock, _patch, patch

from django.http import HttpResponse
from django.test import RequestFactory

import requests
from rest_framework import exceptions, viewsets
from rest_framework.response import Response

from products.enterprise.backend.api.vercel.test.base import VercelTestBase
from products.enterprise.backend.api.vercel.vercel_region_proxy_mixin import VercelRegionProxyMixin


class _TestVercelRegionProxyViewSet(VercelRegionProxyMixin, viewsets.GenericViewSet):
    def get(self, request):
        return Response({"message": "success"})


@pytest.mark.django_db
class TestVercelRegionProxyMixin(VercelTestBase):
    US_DOMAIN = "https://us.posthog.com"
    EU_DOMAIN = "https://eu.posthog.com"
    LOCALHOST_8000 = "http://localhost:8000"
    LOCALHOST_8010 = "http://localhost:8010"
    INVALID_INSTALLATION = "icfg_nonexistentinstallation"

    client_id_patcher: _patch
    jwks_patcher: _patch
    mock_jwks_function: MagicMock

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.client_id_patcher = patch("ee.settings.VERCEL_CLIENT_INTEGRATION_ID", "test_audience")
        cls.jwks_patcher = patch("ee.api.authentication.get_vercel_jwks")
        cls.client_id_patcher.start()
        cls.mock_jwks_function = cls.jwks_patcher.start()

    @classmethod
    def tearDownClass(cls):
        cls.client_id_patcher.stop()
        cls.jwks_patcher.stop()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self.test_viewset = _TestVercelRegionProxyViewSet()
        self.mock_jwks_function.return_value = self.mock_jwks

    def _setup_region_test(self, site_url, installation_id=None, debug=False):
        context_manager = self.settings(SITE_URL=site_url, DEBUG=debug)
        return context_manager

    def _create_authenticated_request(self, installation_id, auth_type="user"):
        factory = RequestFactory()
        if auth_type == "user":
            payload = self._create_user_auth_payload(installation_id=installation_id)
        else:
            payload = self._create_system_auth_payload(installation_id=installation_id)
        token = self._create_jwt_token(payload)
        auth_headers = {"HTTP_AUTHORIZATION": f"Bearer {token}", "HTTP_X_VERCEL_AUTH": auth_type}
        return factory.get("/test/", **auth_headers)

    def _create_request(self, token=None, auth_type="user"):
        factory = RequestFactory()
        headers = {}
        if token:
            headers.update({"HTTP_AUTHORIZATION": f"Bearer {token}", "HTTP_X_VERCEL_AUTH": auth_type})
        return factory.get("/test/", **headers)

    def _assert_drf_response(self, result, expected_data, status=200):
        assert isinstance(result, Response)
        assert result.data == expected_data
        assert result.status_code == status

    def _assert_http_response(self, result, expected_status):
        assert isinstance(result, HttpResponse)
        assert result.status_code == expected_status

    def _assert_json_content(self, response, expected_data):
        assert response.data == expected_data

    def _patch_super_dispatch(self, return_value):
        return patch("rest_framework.viewsets.GenericViewSet.dispatch", return_value=return_value)

    def _mock_success_response(self, data=None, status=200):
        response = Mock()
        response_data = data or {"success": True}
        response.content = str(response_data).replace("'", '"').encode()
        response.status_code = status
        response.headers = {"content-type": "application/json"}
        response.json.return_value = response_data
        return response

    def _mock_error_response(self, error_msg, status=500):
        response = Mock()
        response.content = f'{{"error": "{error_msg}"}}'.encode()
        response.status_code = status
        response.headers = {"content-type": "application/json"}
        return response

    def _patch_proxy_to_eu(self, return_value=None, side_effect=None):
        return patch.object(VercelRegionProxyMixin, "_proxy_to_eu", return_value=return_value, side_effect=side_effect)

    @contextmanager
    def _mock_dispatch_scenario(self, super_response=None, proxy_response=None, proxy_error=None):
        mocks = {}
        if super_response:
            mocks["super_dispatch"] = self._patch_super_dispatch(super_response)
        if proxy_response or proxy_error:
            mocks["proxy"] = self._patch_proxy_to_eu(return_value=proxy_response, side_effect=proxy_error)

        started_mocks = {key: mock.__enter__() for key, mock in mocks.items()}
        try:
            yield started_mocks
        finally:
            for mock in reversed(list(mocks.values())):
                mock.__exit__(None, None, None)

    def test_detects_development_environment(self):
        test_cases = [
            ("localhost_no_debug", self.LOCALHOST_8000, False, True),
            ("localhost_alt_port", self.LOCALHOST_8010, False, True),
            ("us_region_debug_mode", self.US_DOMAIN, True, True),
            ("us_region_production", self.US_DOMAIN, False, False),
            ("eu_region_production", self.EU_DOMAIN, False, False),
        ]

        for scenario, site_url, debug, expected in test_cases:
            with self.subTest(scenario=scenario, site_url=site_url, debug=debug):
                with self._setup_region_test(site_url, debug=debug):
                    assert self.test_viewset.is_dev_env == expected

    def test_detects_current_region(self):
        test_cases = [
            ("us_region", self.US_DOMAIN, "us"),
            ("eu_region", self.EU_DOMAIN, "eu"),
            ("unknown_domain", "https://other.domain.com", None),
            ("localhost", self.LOCALHOST_8000, None),
        ]

        for scenario, site_url, expected in test_cases:
            with self.subTest(scenario=scenario, site_url=site_url):
                with self._setup_region_test(site_url):
                    assert self.test_viewset.current_region == expected

    def test_retrieves_cached_installation_status(self):
        test_cases = [
            ("valid_installation", True, "installation_id"),
            ("invalid_installation", False, "icfg_nonexistentinstallation"),
        ]

        for scenario, expected, installation_id in test_cases:
            with self.subTest(scenario=scenario, expected=expected):
                if expected:
                    installation_id = self.installation_id
                result = self.test_viewset._get_cached_installation_status(installation_id)
                assert result == expected

    def test_extracts_installation_id_from_valid_jwt_token(self):
        request = self._create_authenticated_request(self.installation_id)
        result = self.test_viewset._extract_installation_id(request)
        assert result == self.installation_id

    def test_returns_none_for_invalid_jwt_token(self):
        request = self._create_request("invalid_token")
        result = self.test_viewset._extract_installation_id(request)
        assert result is None

    def test_returns_none_when_no_auth_headers_present(self):
        request = self._create_request()
        result = self.test_viewset._extract_installation_id(request)
        assert result is None

    def test_determines_proxy_requirement(self):
        test_cases = [
            ("us_region_missing_installation", self.US_DOMAIN, "icfg_nonexistentinstallation", "eu"),
            ("us_region_valid_installation", self.US_DOMAIN, "installation_id", None),
            ("eu_region_missing_installation", self.EU_DOMAIN, "icfg_nonexistentinstallation", None),
            ("us_region_no_installation", self.US_DOMAIN, None, None),
            ("unknown_domain", "https://unknown.domain.com", "installation_id", None),
        ]

        for scenario, site_url, installation_id, expected in test_cases:
            with self.subTest(scenario=scenario, site_url=site_url, installation_id=installation_id):
                if installation_id == "installation_id":
                    installation_id = self.installation_id
                request = self._create_request()
                with self._setup_region_test(site_url):
                    result = self.test_viewset._should_proxy_to_eu(installation_id, request)
                    expected_bool = expected == "eu"
                    assert result == expected_bool

    def test_upsert_with_data_region_us_does_not_proxy_from_us(self):
        """Test that upsert with data_region: 'US' doesn't proxy when in US region"""
        factory = RequestFactory()
        request_body = json.dumps(
            {
                "scopes": ["read"],
                "metadata": {"data_region": "US"},
                "credentials": {"access_token": "token", "token_type": "Bearer"},
            }
        )
        request = factory.put(
            "/api/vercel/v1/installations/icfg_nonexistentinstallation",
            data=request_body,
            content_type="application/json",
        )

        with self._setup_region_test(self.US_DOMAIN):
            result = self.test_viewset._should_proxy_to_eu("icfg_nonexistentinstallation", request)
            assert result is False  # Should not proxy

    def test_upsert_with_data_region_eu_proxies_from_us(self):
        """Test that upsert with data_region: 'EU' proxies from US to EU region"""
        factory = RequestFactory()
        request_body = json.dumps(
            {
                "scopes": ["read"],
                "metadata": {"data_region": "EU"},
                "credentials": {"access_token": "token", "token_type": "Bearer"},
            }
        )
        request = factory.put(
            "/api/vercel/v1/installations/icfg_nonexistentinstallation",
            data=request_body,
            content_type="application/json",
        )

        with self._setup_region_test(self.US_DOMAIN):
            result = self.test_viewset._should_proxy_to_eu("icfg_nonexistentinstallation", request)
            assert result is True  # Should proxy to EU

    def test_upsert_without_data_region_uses_normal_logic(self):
        """Test that upsert without data_region falls back to normal proxy logic"""
        factory = RequestFactory()
        request_body = json.dumps(
            {
                "scopes": ["read"],
                "metadata": {},  # No data_region specified
                "credentials": {"access_token": "token", "token_type": "Bearer"},
            }
        )
        request = factory.put(
            "/api/vercel/v1/installations/icfg_nonexistentinstallation",
            data=request_body,
            content_type="application/json",
        )

        with self._setup_region_test(self.US_DOMAIN):
            result = self.test_viewset._should_proxy_to_eu("icfg_nonexistentinstallation", request)
            assert result is True  # Should proxy using normal logic (installation doesn't exist)

    def test_non_upsert_request_ignores_data_region(self):
        """Test that GET requests ignore data_region metadata"""
        factory = RequestFactory()
        request = factory.get("/api/vercel/v1/installations/icfg_nonexistentinstallation")

        with self._setup_region_test(self.US_DOMAIN):
            result = self.test_viewset._should_proxy_to_eu("icfg_nonexistentinstallation", request)
            assert result is True  # Should use normal logic (installation doesn't exist)

    @patch("ee.api.vercel.vercel_region_proxy_mixin.requests.request")
    def test_successfully_proxies_request_to_target_region(self, mock_request):
        mock_request.return_value = self._mock_success_response()
        mock_django_request = self._create_mock_request()

        with self._setup_region_test(self.US_DOMAIN):
            result = self.test_viewset._proxy_to_eu(mock_django_request)
            assert isinstance(result, Response)
            assert result.status_code == 200

    @patch("ee.api.vercel.vercel_region_proxy_mixin.requests.request")
    def test_raises_exception_on_proxy_request_failure(self, mock_request):
        mock_request.side_effect = requests.exceptions.RequestException("Connection failed")
        mock_django_request = self._create_mock_request(headers={})

        with self._setup_region_test(self.US_DOMAIN):
            with pytest.raises(exceptions.APIException):
                self.test_viewset._proxy_to_eu(mock_django_request)

    def _create_mock_request(self, headers=None):
        mock_request = Mock()
        mock_request.method = "GET"
        mock_request.build_absolute_uri.return_value = "https://us.posthog.com/api/projects/123"
        mock_request.META = headers or {"HTTP_AUTHORIZATION": "Bearer token", "HTTP_X_VERCEL_AUTH": "user"}
        mock_request.GET = {}
        mock_request.body = None

        # Mock the headers attribute that behaves like a dict when dict() is called on it
        headers_dict = {
            "Authorization": "Bearer token",
            "X-Vercel-Auth": "user",
        }
        mock_request.headers = headers_dict
        return mock_request

    def test_dispatch_behavior(self):
        test_cases = [
            ("localhost_bypasses_logic", self.LOCALHOST_8000, None, {"bypassed": True}, None, None),
            (
                "us_region_valid_installation_continues",
                self.US_DOMAIN,
                "valid",
                {"success": True},
                None,
                None,
            ),
            (
                "us_region_missing_installation_proxies_to_eu",
                self.US_DOMAIN,
                "invalid",
                None,
                {"proxied": True},
                "eu",
            ),
            (
                "us_region_proxy_failure_falls_back",
                self.US_DOMAIN,
                "invalid",
                {"fallback": True},
                None,
                "error",
            ),
            (
                "eu_region_valid_installation_continues",
                self.EU_DOMAIN,
                "valid",
                {"success": True},
                None,
                None,
            ),
            ("eu_region_missing_installation_returns_404", self.EU_DOMAIN, "invalid", None, None, "404"),
            (
                "missing_installation_id_continues",
                self.US_DOMAIN,
                "none",
                {"no_installation": True},
                None,
                None,
            ),
            ("no_auth_continues", self.US_DOMAIN, "no_auth", {"no_auth": True}, None, None),
            ("unknown_region_continues", "https://unknown.domain.com", None, {"unknown_region": True}, None, None),
        ]

        for (
            scenario,
            site_url,
            installation_type,
            expected_super_response,
            expected_proxy_response,
            expected_action,
        ) in test_cases:
            with self.subTest(scenario=scenario, site_url=site_url, installation_type=installation_type):
                debug = site_url == self.LOCALHOST_8000

                match installation_type:
                    case "valid":
                        request = self._create_authenticated_request(self.TEST_INSTALLATION_ID)
                    case "invalid":
                        request = self._create_authenticated_request(self.INVALID_INSTALLATION)
                    case "none":
                        token = self._create_jwt_token({})
                        request = self._create_request(token)
                    case _:
                        request = self._create_request()

                with self._setup_region_test(site_url, debug=debug):
                    if expected_action == "eu":
                        # We're in the US region with a missing installation, so we should proxy to EU
                        with self._patch_proxy_to_eu(Response(expected_proxy_response, status=200)) as mock_proxy:
                            result = self.test_viewset.dispatch(request, *[], **{})
                            self._assert_http_response(result, 200)
                            mock_proxy.assert_called_once()
                            # Just verify proxy was called - no region parameter anymore
                    elif expected_action == "error":
                        # Proxy fails, so we should fall back to normal processing
                        with self._patch_proxy_to_eu(side_effect=exceptions.APIException("Proxy failed")):
                            with self._patch_super_dispatch(Response(expected_super_response)) as mock_super_dispatch:
                                result = self.test_viewset.dispatch(request, *[], **{})
                                self._assert_drf_response(result, expected_super_response)
                                mock_super_dispatch.assert_called_once()
                    elif expected_action == "404":
                        # We're in the EU region with missing installation
                        with self.assertRaises(exceptions.NotFound):
                            self.test_viewset.dispatch(request, *[], **{})
                    else:
                        # We're in the US region with a valid installation
                        with self._patch_super_dispatch(Response(expected_super_response)) as mock_super_dispatch:
                            result = self.test_viewset.dispatch(request, *[], **{})
                            self._assert_drf_response(result, expected_super_response)
                            mock_super_dispatch.assert_called_once()
