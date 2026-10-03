import json
from dataclasses import dataclass, field

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.cache import cache
from django.test import override_settings

import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from parameterized import parameterized
from rest_framework import status

from posthog.egress.github.transport import GitHubEgressBudgetExhausted
from posthog.egress.limiter.policies import Priority
from posthog.models import Organization, Team
from posthog.models.github_integration_base import INSTALLATION_UNAVAILABLE_SINCE_CONFIG_KEY
from posthog.models.integration import Integration

BRAND_DETECTION_FLAG = "workflows-brand-detection"
INVENTED_APP_PRIVATE_KEY = (
    rsa.generate_private_key(public_exponent=65537, key_size=2048)
    .private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    .decode()
)

NEXT_SHADCN_APP = {
    "package.json": json.dumps({"name": "acme-web", "private": True}),
    "app/layout.tsx": """import type { Metadata } from "next"
import { Inter } from "next/font/google"

const inter = Inter({ subsets: ["latin"] })

export const metadata: Metadata = { title: "Acme" }
""",
    "app/globals.css": """@tailwind base;

@layer base {
  :root {
    --background: 0 0% 100%;
    --foreground: 222.2 84% 4.9%;
    --primary: 222.2 47.4% 11.2%;
    --brand: 252 87% 58%;
  }

  .dark {
    --background: 222.2 84% 4.9%;
    --primary: 210 40% 98%;
  }
}
""",
    "tailwind.config.ts": """export default {
  theme: { extend: { colors: { primary: { DEFAULT: "hsl(var(--primary))" } } } },
}
""",
    "README.md": "# Acme web\n",
}

MONOREPO = {
    "package.json": json.dumps({"name": "acme-monorepo"}),
    "apps/docs/package.json": json.dumps({"name": "@acme/docs"}),
    "apps/docs/app/globals.css": ":root {\n  --primary: #0a7d32;\n}\n",
    "apps/web/package.json": json.dumps({"name": "@acme/web"}),
    "apps/web/app/globals.css": ":root {\n  --brand: #e5484d;\n}\n",
    "apps/web/public/manifest.json": json.dumps({"name": "Acme Cloud"}),
    "apps/admin/package.json": json.dumps({"name": "@acme/admin"}),
    "apps/admin/app/globals.css": ":root {\n  --primary: #2563eb;\n}\n",
}


def _response(status_code: int, body: bytes | dict | list, headers: dict[str, str] | None = None) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response._content = body if isinstance(body, bytes) else json.dumps(body).encode()
    response.headers.update(headers or {})
    return response


@dataclass(frozen=False)
class FakeGitHub:
    """Serves invented repositories through the HTTP boundary of GitHubIntegration."""

    repositories: dict[str, dict[str, str]]
    status_overrides: dict[str, int] = field(default_factory=dict)
    override_headers: dict[str, str] = field(default_factory=dict)
    refused_token_refresh: requests.Response | None = None
    times_out_on: str | None = None
    shed: bool = False
    calls: list[dict] = field(default_factory=list)

    def __call__(self, method: str, url: str, **kwargs) -> requests.Response:
        self.calls.append({"url": url, **kwargs})
        if self.shed:
            raise GitHubEgressBudgetExhausted("shed")
        path = url.removeprefix("https://api.github.com")
        if path.startswith("/app/installations/"):
            return self._token_refresh()
        if self.times_out_on and self.times_out_on in path:
            raise requests.ConnectTimeout("invented timeout")
        for fragment, status_code in self.status_overrides.items():
            if fragment in path:
                return _response(status_code, {"message": "denied"}, self.override_headers)
        owner, name, *rest = path.removeprefix("/repos/").split("/", 2)
        files = self.repositories.get(f"{owner}/{name}")
        if files is None:
            return _response(404, {"message": "Not Found"})
        if not rest:
            return _response(200, {"name": name, "full_name": f"{owner}/{name}", "default_branch": "main"})
        if rest[0].startswith("git/trees/"):
            tree = [
                {"path": file_path, "type": "blob", "sha": f"sha-{index}", "size": len(text.encode())}
                for index, (file_path, text) in enumerate(files.items())
            ]
            return _response(200, {"sha": "tree", "tree": tree, "truncated": False})
        if rest[0].startswith("git/blobs/"):
            index = int(rest[0].removeprefix("git/blobs/sha-"))
            return _response(200, list(files.values())[index].encode())
        return _response(404, {"message": "Not Found"})

    def _token_refresh(self) -> requests.Response:
        if self.refused_token_refresh is not None:
            return self.refused_token_refresh
        return _response(201, {"token": "invented-fresh-token", "expires_at": "2099-01-01T00:00:00+00:00"})

    def blob_reads(self) -> int:
        return sum("/git/blobs/" in call["url"] for call in self.calls)


def _only_brand_detection_enabled(flag: str, *args, **kwargs) -> bool:
    return flag == BRAND_DETECTION_FLAG


@override_settings(GITHUB_APP_CLIENT_ID="invented-client-id", GITHUB_APP_PRIVATE_KEY=INVENTED_APP_PRIVATE_KEY)
@patch("posthoganalytics.feature_enabled", side_effect=_only_brand_detection_enabled)
class TestEmailBrandDetectAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        self.integration = self._github_integration(self.team)
        self.github = FakeGitHub(repositories={"acme/acme-web": NEXT_SHADCN_APP, "acme/platform": MONOREPO})
        patcher = patch("posthog.models.github_integration_base.github_request", side_effect=self.github)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _github_integration(self, team: Team) -> Integration:
        return Integration.objects.create(
            team=team,
            kind="github",
            integration_id="1234",
            config={"installation_id": "1234", "account": {"type": "Organization", "name": "acme"}},
            sensitive_config={"access_token": "invented-token"},
        )

    def _detect(self, **payload):
        body = {"integration_id": self.integration.id, **payload}
        return self.client.post(f"/api/projects/{self.team.id}/email_brand/detect/", body, format="json")

    def test_proposes_the_brand_token_as_primary_and_the_next_font_without_saving_the_brand(self, _flag):
        saved = self.client.patch(
            f"/api/projects/{self.team.id}/email_brand/current/", {"name": "Saved"}, format="json"
        ).json()

        response = self._detect(repository="acme/acme-web")

        assert response.status_code == status.HTTP_200_OK, response.json()
        detection = response.json()
        assert detection["repository"] == "acme/acme-web"
        assert detection["proposal"]["primary_color"] == {
            "value": "#5c37f1",
            "path": "app/globals.css",
            "line": 8,
            "default_theme": False,
            "font_stack": None,
        }
        assert detection["proposal"]["font_family"]["value"] == "Inter"
        assert detection["proposal"]["font_family"]["path"] == "app/layout.tsx"
        assert detection["proposal"]["font_family"]["font_stack"] == "Inter, Arial, Helvetica, sans-serif"
        assert detection["proposal"]["name"]["value"] == "Acme"
        assert [candidate["value"] for candidate in detection["candidates"]["primary_color"]][:2] == [
            "#5c37f1",
            "#0f172a",
        ]
        files_read = {file["path"]: file["found"] for file in detection["files_read"]}
        assert {"field": "primary_color", "value": "#5c37f1"} in files_read["app/globals.css"]
        assert "README.md" not in files_read
        assert {(call["source"], call["priority"], call["timeout"]) for call in self.github.calls} == {
            ("workflows_brand", Priority.NORMAL, 5)
        }
        assert self.client.get(f"/api/projects/{self.team.id}/email_brand/current/").json() == saved

    def test_picks_the_web_app_of_a_monorepo_and_reads_another_app_on_request(self, _flag):
        detected = self._detect(repository="acme/platform").json()

        assert detected["app_root"] == "apps/web/"
        assert detected["app_root_alternatives"] == ["apps/admin/"]
        assert detected["proposal"]["primary_color"]["value"] == "#e5484d"
        assert detected["proposal"]["name"]["value"] == "Acme Cloud"

        admin = self._detect(repository="acme/platform", app_root="apps/admin").json()

        assert admin["app_root"] == "apps/admin/"
        assert admin["proposal"]["primary_color"]["value"] == "#2563eb"

    def test_reuses_a_detection_for_ten_minutes_unless_refreshed(self, _flag):
        first = self._detect(repository="acme/acme-web").json()
        requests_after_first = len(self.github.calls)

        cached = self._detect(repository="acme/acme-web").json()

        assert cached == first
        assert len(self.github.calls) == requests_after_first

        refreshed = self._detect(repository="acme/acme-web", refresh=True)
        assert refreshed.status_code == status.HTTP_200_OK
        assert len(self.github.calls) == 2 * requests_after_first

    @parameterized.expand(
        [
            ("shed by the egress limiter", {"shed": True}, status.HTTP_429_TOO_MANY_REQUESTS, "github_busy"),
            (
                "rate limited by GitHub",
                {"status_overrides": {"/git/trees/": 429}},
                status.HTTP_429_TOO_MANY_REQUESTS,
                "github_busy",
            ),
            (
                "rate limited by GitHub with a 403",
                {"status_overrides": {"/git/trees/": 403}, "override_headers": {"X-RateLimit-Remaining": "0"}},
                status.HTTP_429_TOO_MANY_REQUESTS,
                "github_busy",
            ),
            (
                "token refresh fails for a moment",
                {"status_overrides": {"/repos/": 401}, "refused_token_refresh": _response(502, b"Bad gateway")},
                status.HTTP_429_TOO_MANY_REQUESTS,
                "github_busy",
            ),
            (
                "token refresh rate limited",
                {
                    "status_overrides": {"/repos/": 401},
                    "refused_token_refresh": _response(
                        403, {"message": "API rate limit exceeded"}, {"X-RateLimit-Remaining": "0"}
                    ),
                },
                status.HTTP_429_TOO_MANY_REQUESTS,
                "github_busy",
            ),
            (
                "fresh token not accepted yet",
                {"status_overrides": {"/repos/": 401}},
                status.HTTP_429_TOO_MANY_REQUESTS,
                "github_busy",
            ),
            (
                "app uninstalled, so the token refresh is refused",
                {
                    "status_overrides": {"/repos/": 401},
                    "refused_token_refresh": _response(404, {"message": "Not Found"}),
                },
                status.HTTP_400_BAD_REQUEST,
                "github_disconnected",
            ),
            (
                "app suspended, so the token refresh is refused",
                {
                    "status_overrides": {"/repos/": 401},
                    "refused_token_refresh": _response(403, {"message": "This installation has been suspended"}),
                },
                status.HTTP_400_BAD_REQUEST,
                "github_disconnected",
            ),
            (
                "file read forbidden",
                {"status_overrides": {"/git/blobs/": 403}},
                status.HTTP_400_BAD_REQUEST,
                "repository_unreadable",
            ),
            (
                "repository not found",
                {"repositories": {}},
                status.HTTP_400_BAD_REQUEST,
                "repository_unreadable",
            ),
        ]
    )
    def test_reports_why_github_could_not_be_read(self, _flag, _name, fake_state, expected_status, expected_code):
        for attribute, value in fake_state.items():
            setattr(self.github, attribute, value)

        response = self._detect(repository="acme/acme-web")

        assert response.status_code == expected_status, response.json()
        assert response.json()["code"] == expected_code

    def test_a_stale_unavailable_marker_does_not_turn_a_timeout_into_disconnected(self, _flag):
        self.integration.config = {**self.integration.config, INSTALLATION_UNAVAILABLE_SINCE_CONFIG_KEY: 1}
        self.integration.save()
        self.github.times_out_on = "/git/blobs/"

        response = self._detect(repository="acme/acme-web")

        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS, response.json()
        assert response.json()["code"] == "github_busy"

    def test_reports_disconnected_when_the_scheduled_token_refresh_is_refused(self, _flag):
        self.integration.config = {**self.integration.config, "expires_in": 3600, "refreshed_at": 1}
        self.integration.save()
        self.github.refused_token_refresh = _response(404, {"message": "Not Found"})

        response = self._detect(repository="acme/acme-web")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["code"] == "github_disconnected"

    def test_reports_a_github_server_error_without_retrying_past_the_time_budget(self, _flag):
        self.github.status_overrides = {"/git/blobs/": 502}

        response = self._detect(repository="acme/acme-web")

        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS, response.json()
        assert response.json()["code"] == "github_busy"
        assert self.github.blob_reads() == 1

    def test_does_not_reuse_a_detection_that_ran_out_of_time(self, _flag):
        with patch("products.workflows.backend.services.email_brand_detection.DETECTION_BUDGET_SECONDS", -1):
            partial = self._detect(repository="acme/acme-web").json()
        assert partial["files_read"] == []
        requests_after_partial = len(self.github.calls)

        complete = self._detect(repository="acme/acme-web").json()

        assert len(self.github.calls) > requests_after_partial
        assert complete["proposal"]["primary_color"]["value"] == "#5c37f1"

    def test_proposes_nothing_for_an_empty_repository(self, _flag):
        self.github.status_overrides = {"/git/trees/": 409}

        response = self._detect(repository="acme/acme-web")

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["files_read"] == []
        assert response.json()["proposal"]["primary_color"] is None

    def test_only_reads_through_a_github_integration_of_the_project(self, _flag):
        foreign_team = Team.objects.create(organization=Organization.objects.create(name="Other org"))
        self.integration = self._github_integration(foreign_team)

        response = self._detect(repository="acme/acme-web")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["attr"] == "integration_id"
        assert self.github.calls == []

    @parameterized.expand(
        [
            ("parent directory", "../..", "repository"),
            ("dot segment", "acme/..", "repository"),
            ("extra path", "acme/acme-web/contents", "repository"),
            ("app root outside the repository", "acme/platform", "app_root"),
        ]
    )
    def test_rejects_targets_outside_the_repository_without_reading_files(self, _flag, _name, repository, attr):
        response = self._detect(repository=repository, app_root="apps/missing")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["attr"] == attr
        assert not any("/git/blobs/" in call["url"] for call in self.github.calls)

    def test_is_hidden_while_the_flag_is_off(self, flag):
        flag.side_effect = None
        flag.return_value = False

        response = self._detect(repository="acme/acme-web")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert self.github.calls == []
