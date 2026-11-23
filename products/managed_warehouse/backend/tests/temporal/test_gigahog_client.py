import json
import datetime as dt

import pytest

import requests

from products.managed_warehouse.backend.temporal.gigahog_client import GigahogClient, GigahogConfig, GigahogError


@pytest.mark.parametrize("api_direct", [False, True])
def test_gigahog_proxy_routing(monkeypatch, api_direct):
    proxy = "http://proxy.example.test:8080"
    monkeypatch.setenv("HTTPS_PROXY", proxy)
    monkeypatch.setenv("NO_PROXY", "")
    monkeypatch.setenv("no_proxy", "")
    config = GigahogConfig(
        url="https://api.example.test",
        catalog="imports",
        data_path="s3://test-bucket/imports/",
        token_url="https://auth.example.test/oauth/token",
        client_id=f"writer-{api_direct}",
        client_secret="test-secret",
        api_direct=api_direct,
    )
    calls = []

    def send(_adapter, request, *, proxies, verify, **kwargs):
        calls.append((request.url, proxies.get("https"), verify))
        response = requests.Response()
        response.request = request
        response.url = request.url
        response.status_code = 200
        if request.url == config.token_url:
            payload = {
                "access_token": "test-token",
                "expires_in": 3600,
                "storage": {
                    "access_key_id": "test-key",
                    "secret_access_key": "test-key-secret",
                    "session_token": "test-session",
                    "expiration": (dt.datetime.now(dt.UTC) + dt.timedelta(hours=1)).isoformat(),
                },
            }
        else:
            assert request.headers["Authorization"] == "Bearer test-token"
            payload = {"name": "team_42"}
            if api_direct:
                response.status_code = 307
                response.headers["Location"] = "https://redirect.example.test/"
        response._content = json.dumps(payload).encode()
        return response

    monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
    monkeypatch.delenv("CURL_CA_BUNDLE", raising=False)
    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", send)

    with GigahogClient(config, team_id=42) as client:
        if api_direct:
            with pytest.raises(GigahogError) as exc:
                client.namespace("team_42")
            assert exc.value.status_code == 307
        else:
            assert client.namespace("team_42").name == "team_42"

    assert calls == [
        (config.token_url, proxy, True),
        (f"{config.url}/v1/catalogs/imports/namespaces/team_42", None if api_direct else proxy, True),
    ]
