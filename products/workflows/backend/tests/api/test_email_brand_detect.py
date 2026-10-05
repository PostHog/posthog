import io
import os
import json
import base64
import struct
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import unquote, urlsplit

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.cache import cache
from django.test import override_settings

import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from parameterized import parameterized
from PIL import Image
from rest_framework import status

from posthog.egress.github.transport import GitHubEgressBudgetExhausted
from posthog.egress.limiter.policies import Priority
from posthog.models import Organization, Team
from posthog.models.github_integration_base import INSTALLATION_UNAVAILABLE_SINCE_CONFIG_KEY
from posthog.models.integration import Integration
from posthog.models.uploaded_media import MAX_IMAGE_BYTES
from posthog.storage import object_storage

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
CONTENTS_API_INLINE_LIMIT = 1024 * 1024
TEST_MEDIA_FOLDER = "test-email-brand-logos"

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


def _png(width: int = 32, height: int = 32, *, noise: bool = False) -> bytes:
    image = Image.frombytes("RGB", (width, height), os.urandom(width * height * 3)) if noise else None
    image = image or Image.new("RGB", (width, height), "#5c37f1")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _ico(*sizes: tuple[int, int]) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", max(sizes), "#e5484d").save(buffer, format="ICO", sizes=list(sizes))
    return buffer.getvalue()


def _ico_frames(*frames: tuple[str, tuple[int, int]]) -> bytes:
    images = []
    for bitmap_format, size in frames:
        single = io.BytesIO()
        Image.new("RGBA", size, "#e5484d").save(single, format="ICO", sizes=[size], bitmap_format=bitmap_format)
        images.append(single.getvalue())
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries, data = b"", b""
    for image in images:
        entry, frame = image[6:22], image[struct.unpack_from("<I", image, 18)[0] :]
        entries += entry[:12] + struct.pack("<I", offset + len(data))
        data += frame
    return header + entries + data


SVG_LOGO = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect fill="#5c37f1" width="10" height="10"/></svg>'
)

BRAND_ASSETS: dict[str, str | bytes] = {
    "package.json": json.dumps({"name": "acme-assets"}),
    "public/favicon.ico": _ico((16, 16), (48, 48)),
    "public/logo.svg": SVG_LOGO,
    "public/logo.png": _png(),
    "public/logo-white.png": _png(),
    "public/integrations/slack/logo.png": _png(),
}

LOGO_FILES: dict[str, str | bytes] = {
    **BRAND_ASSETS,
    "public/brand/logo-large.png": _png(700, 600, noise=True),
    "public/brand/logo-huge.png": b"\x89PNG" + b"0" * MAX_IMAGE_BYTES,
    "public/brand/logo-broken.png": b"<html>not an image</html>",
    "public/brand/logo-broken.svg": "<html>not an svg</html>",
    "public/brand/logo #2.png": _png(),
    "public/brand/mixed.ico": _ico_frames(("bmp", (48, 48)), ("png", (64, 64))),
    "public/brand/many-frames.ico": _ico_frames(*[("png", (16, 16))] * 22),
}


def _response(status_code: int, body: bytes | dict | list, headers: dict[str, str] | None = None) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response._content = body if isinstance(body, bytes) else json.dumps(body).encode()
    response.raw = io.BytesIO(response._content)
    response.headers.update(headers or {})
    return response


def _bytes(content: str | bytes) -> bytes:
    return content if isinstance(content, bytes) else content.encode()


@dataclass(frozen=False)
class FakeGitHub:
    """Serves invented repositories through the HTTP boundary of GitHubIntegration."""

    repositories: Mapping[str, Mapping[str, str | bytes]]
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
        path = urlsplit(url).path
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
                {"path": file_path, "type": "blob", "sha": f"sha-{index}", "size": len(_bytes(content))}
                for index, (file_path, content) in enumerate(files.items())
            ]
            return _response(200, {"sha": "tree", "tree": tree, "truncated": False})
        if rest[0].startswith("git/blobs/"):
            index = int(rest[0].removeprefix("git/blobs/sha-"))
            return _response(200, _bytes(list(files.values())[index]))
        if rest[0].startswith("contents/"):
            return self._contents_entry(files, unquote(rest[0].removeprefix("contents/")))
        return _response(404, {"message": "Not Found"})

    def _token_refresh(self) -> requests.Response:
        if self.refused_token_refresh is not None:
            return self.refused_token_refresh
        return _response(201, {"token": "invented-fresh-token", "expires_at": "2099-01-01T00:00:00+00:00"})

    def _contents_entry(self, files: Mapping[str, str | bytes], file_path: str) -> requests.Response:
        if any(path.startswith(f"{file_path}/") for path in files):
            return _response(200, [{"type": "file", "path": path} for path in files if path.startswith(file_path)])
        if file_path not in files:
            return _response(404, {"message": "Not Found"})
        content = _bytes(files[file_path])
        inline = len(content) <= CONTENTS_API_INLINE_LIMIT
        return _response(
            200,
            {
                "type": "file",
                "path": file_path,
                "sha": f"sha-{list(files).index(file_path)}",
                "size": len(content),
                "encoding": "base64" if inline else "none",
                "content": base64.b64encode(content).decode() if inline else "",
            },
        )

    def blob_reads(self) -> int:
        return sum("/git/blobs/" in call["url"] for call in self.calls)


def _only_brand_detection_enabled(flag: str, *args, **kwargs) -> bool:
    return flag == BRAND_DETECTION_FLAG


@override_settings(
    GITHUB_APP_CLIENT_ID="invented-client-id",
    GITHUB_APP_PRIVATE_KEY=INVENTED_APP_PRIVATE_KEY,
    OBJECT_STORAGE_ENABLED=True,
    OBJECT_STORAGE_MEDIA_UPLOADS_FOLDER=TEST_MEDIA_FOLDER,
)
@patch("posthoganalytics.feature_enabled", side_effect=_only_brand_detection_enabled)
class TestEmailBrandDetectAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        self.integration = self._github_integration(self.team)
        self.github = FakeGitHub(
            repositories={
                "acme/acme-web": NEXT_SHADCN_APP,
                "acme/platform": MONOREPO,
                "acme/assets": BRAND_ASSETS,
                "acme/logos": LOGO_FILES,
            }
        )
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

    def _import_logo(self, path: str, repository: str = "acme/logos"):
        body = {"integration_id": self.integration.id, "repository": repository, "path": path}
        response = self.client.post(f"/api/projects/{self.team.id}/email_brand/import_logo/", body, format="json")
        if response.status_code == status.HTTP_200_OK and response.json()["media_id"]:
            self.addCleanup(
                object_storage.delete, f"{TEST_MEDIA_FOLDER}/team-{self.team.id}/media-{response.json()['media_id']}"
            )
        return response

    def _email_media_library(self) -> list[dict]:
        return self.client.get(f"/api/projects/{self.team.id}/uploaded_media/?purpose=email").json()["results"]

    def _served_image(self, url: str) -> Image.Image:
        self.client.logout()
        served = self.client.get(url)
        self.client.force_login(self.user)
        assert served.status_code == status.HTTP_200_OK
        return Image.open(io.BytesIO(served.content))

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

    def test_ranks_own_raster_logos_above_svg_and_ico_and_skips_variants_and_third_party_logos(self, _flag):
        response = self._detect(repository="acme/assets")

        assert response.status_code == status.HTTP_200_OK, response.json()
        candidates = response.json()["logo_candidates"]
        paths = [candidate["path"] for candidate in candidates]
        assert paths.index("public/logo.png") < paths.index("public/logo.svg") < paths.index("public/favicon.ico")
        assert "public/integrations/slack/logo.png" not in paths
        assert "public/logo-white.png" not in paths
        assert candidates[paths.index("public/logo.svg")] == {
            "path": "public/logo.svg",
            "format": "svg",
            "size": len(SVG_LOGO.encode()),
        }

    @parameterized.expand(
        [
            ("sent inline by the contents API", "public/logo.png", (32, 32)),
            ("read as a blob above the inline limit", "public/brand/logo-large.png", (700, 600)),
            ("named with characters that need URL quoting", "public/brand/logo #2.png", (32, 32)),
        ]
    )
    def test_imports_a_raster_logo_into_the_email_media_library(self, _flag, _name, path, expected_size):
        response = self._import_logo(path)

        assert response.status_code == status.HTTP_200_OK, response.json()
        imported = response.json()
        assert imported["outcome"] == "imported"
        assert imported["svg"] is None
        assert [media["id"] for media in self._email_media_library()] == [imported["media_id"]]
        served = self._served_image(imported["url"])
        assert (served.format, served.size) == ("PNG", expected_size)

    @parameterized.expand(
        [
            ("png frames", "public/favicon.ico", (48, 48)),
            ("a bitmap frame beside a larger png frame", "public/brand/mixed.ico", (64, 64)),
        ]
    )
    def test_imports_an_ico_as_a_png_of_its_largest_frame(self, _flag, _name, path, expected_size):
        imported = self._import_logo(path).json()

        served = self._served_image(imported["url"])
        assert (served.format, served.size) == ("PNG", expected_size)
        assert self._email_media_library()[0]["content_type"] == "image/png"

    def test_returns_svg_markup_for_the_browser_to_rasterize_without_storing_it(self, _flag):
        response = self._import_logo("public/logo.svg")

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json() == {"outcome": "svg_needs_rasterizing", "media_id": None, "url": None, "svg": SVG_LOGO}
        assert self._email_media_library() == []

    @parameterized.expand(
        [
            ("over the size limit", "public/brand/logo-huge.png", "file_too_large"),
            ("not an image", "public/brand/logo-broken.png", "invalid_image"),
            ("not an svg", "public/brand/logo-broken.svg", "invalid_image"),
            ("an ico with more frames than any icon needs", "public/brand/many-frames.ico", "invalid_image"),
            ("missing", "public/brand/missing.png", "logo_not_found"),
            ("a directory", "public/brand", "logo_not_found"),
            ("outside the repository", "public/../../other/logo.png", "invalid_input"),
        ]
    )
    def test_rejects_a_logo_it_cannot_import(self, _flag, _name, path, expected_code):
        response = self._import_logo(path)

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert (response.json()["code"], response.json()["attr"]) == (expected_code, "path")
        assert self._email_media_library() == []

    @parameterized.expand(
        [
            ("shed by the egress limiter", {"shed": True}, status.HTTP_429_TOO_MANY_REQUESTS, "github_busy"),
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
                "file read forbidden",
                {"status_overrides": {"/contents/": 403}},
                status.HTTP_400_BAD_REQUEST,
                "repository_unreadable",
            ),
        ]
    )
    def test_reports_why_github_could_not_be_read_while_importing_a_logo(
        self, _flag, _name, fake_state, expected_status, expected_code
    ):
        for attribute, value in fake_state.items():
            setattr(self.github, attribute, value)

        response = self._import_logo("public/logo.png")

        assert response.status_code == expected_status, response.json()
        assert response.json()["code"] == expected_code

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

    @parameterized.expand([("detect",), ("import_logo",)])
    def test_is_hidden_while_the_flag_is_off(self, flag, action):
        flag.side_effect = None
        flag.return_value = False

        response = (
            self._detect(repository="acme/acme-web") if action == "detect" else self._import_logo("public/logo.png")
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert self.github.calls == []
