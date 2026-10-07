import io
import json
from collections.abc import Iterable, Mapping
from datetime import timedelta
from typing import TYPE_CHECKING, cast
from urllib.parse import urlparse

import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.http import HttpResponse, StreamingHttpResponse
from django.test import SimpleTestCase, override_settings
from django.utils import timezone

import requests
from parameterized import parameterized
from PIL import Image

from posthog.egress.github.transport import GitHubEgressBudgetExhausted
from posthog.models import Team
from posthog.models.integration import Integration
from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.uploaded_media import UploadedMedia
from posthog.models.utils import generate_random_token_personal

from products.messaging.backend.api.github_brand import GitHubBrandRequestSerializer

if TYPE_CHECKING:
    from rest_framework.response import _MonkeyPatchedResponse


def png(width: int = 256, height: int = 128) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "#e5484d").save(buffer, format="PNG")
    return buffer.getvalue()


class FakeGitHub:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {
            "public/manifest.json": b'{"name": "Juniper Studio", "theme_color": "#e5484d"}',
            "public/logo.png": png(),
        }
        self.status = 200
        self.calls: list[str] = []

    def __call__(self, method: str, url: str, **kwargs: object) -> requests.Response:
        path = urlparse(url).path
        self.calls.append(path)
        response = requests.Response()
        response.status_code = self.status
        body = self._body(path) if self.status == 200 else {"message": "Unavailable"}
        response.raw = io.BytesIO(body if isinstance(body, bytes) else json.dumps(body).encode())
        return response

    def _body(self, path: str) -> object:
        if "/git/trees/" in path:
            return {
                "tree": [
                    {"path": name, "sha": f"{index:040x}", "type": "blob", "size": len(content)}
                    for index, (name, content) in enumerate(self.files.items())
                ]
            }
        if "/git/blobs/" in path:
            return list(self.files.values())[int(path.rsplit("/", 1)[-1], 16)]
        return {"default_branch": "main"}


class ClockAdvancingStream(io.BytesIO):
    def __init__(self, content: bytes, clock: MagicMock) -> None:
        super().__init__(content)
        self.unread_bytes = len(content)
        self._clock = clock

    def read(self, size: int | None = -1) -> bytes:
        self._clock.return_value += 10
        chunk = super().read(size)
        self.unread_bytes -= len(chunk)
        return chunk


class TestGitHubBrandRequestSerializer(SimpleTestCase):
    @parameterized.expand(
        [
            ("juniper/studio?x=y",),
            ("juniper/studio/extra",),
            ("../studio",),
            ("juniper/..",),
            ("juniper/studio\n",),
            ("https://github.com/juniper/studio",),
            ("-juniper/studio",),
        ]
    )
    def test_rejects_anything_but_owner_slash_repo(self, repository: str) -> None:
        serializer = GitHubBrandRequestSerializer(data={"integration_id": 1, "repository": repository})

        assert not serializer.is_valid()
        assert "repository" in serializer.errors

    def test_accepts_owner_slash_repo(self) -> None:
        serializer = GitHubBrandRequestSerializer(data={"integration_id": 1, "repository": "juniper-co/studio.web_2"})

        assert serializer.is_valid(), serializer.errors


@override_settings(OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_MEDIA_UPLOADS_FOLDER="test_github_brand")
class TestDetectBrandFromGitHub(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        self.integration = self._integration_for(self.team)
        self.github = FakeGitHub()
        for patcher in (
            patch("posthog.models.github_integration_base.github_request", side_effect=self.github),
            patch("posthoganalytics.feature_enabled", return_value=True),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _integration_for(self, team: Team) -> Integration:
        return Integration.objects.create(
            team=team,
            kind="github",
            integration_id="1234",
            config={"installation_id": "1234"},
            sensitive_config={"access_token": "invented-token"},
        )

    def _detect(
        self, payload: Mapping[str, object] | None = None, *, authorization: str = ""
    ) -> "_MonkeyPatchedResponse":
        return self.client.post(
            f"/api/projects/{self.team.id}/email_brand/detect_from_github/",
            {"integration_id": self.integration.id, "repository": "juniper/studio", **(payload or {})},
            format="json",
            HTTP_AUTHORIZATION=authorization,
        )

    def test_detects_a_brand_and_serves_the_stored_raster_logo_without_saving_the_brand(self) -> None:
        response = self._detect()

        assert response.status_code == 200, response.json()
        brand = response.json()
        assert {key: brand[key] for key in ("repository", "name", "primary_color")} == {
            "repository": "juniper/studio",
            "name": "Juniper Studio",
            "primary_color": "#e5484d",
        }
        image = cast(HttpResponse | StreamingHttpResponse, self.client.get(urlparse(brand["logo_url"]).path))
        assert (image.status_code, image["Content-Type"]) == (200, "image/png")
        assert (
            b"".join(
                cast(Iterable[bytes], image.streaming_content)
                if isinstance(image, StreamingHttpResponse)
                else [image.content]
            )
            == png()
        )
        assert self.client.get(f"/api/projects/{self.team.id}/email_brand/current/").status_code == 404

    @parameterized.expand(
        [
            ("svg", "public/logo.svg", b'<svg xmlns="http://www.w3.org/2000/svg"/>'),
            ("svg named png", "public/logo.png", b'<svg xmlns="http://www.w3.org/2000/svg"/>'),
            ("html", "public/logo.png", b"<html>Not a logo</html>"),
            ("too small", "public/logo.png", png(32, 32)),
            ("too large", "public/logo.png", png() + b"\0" * (4 * 1024 * 1024)),
        ]
    )
    def test_leaves_the_logo_empty_without_a_usable_raster_image(self, _case: str, path: str, body: bytes) -> None:
        self.github.files = {"public/manifest.json": b'{"name": "Juniper Studio"}', path: body}

        response = self._detect()

        assert response.status_code == 200, response.json()
        assert (response.json()["name"], response.json()["logo_url"]) == ("Juniper Studio", None)

    def test_tries_at_most_three_logo_candidates(self) -> None:
        self.github.files = {
            **{f"public/logo-{index}.png": b"not an image" * 100 for index in range(3)},
            "public/logo-z.png": png(),
        }

        response = self._detect()

        assert response.status_code == 200, response.json()
        assert response.json()["logo_url"] is None

    def test_names_an_empty_repository_after_itself(self) -> None:
        def empty_repository(method: str, url: str, **kwargs: object) -> requests.Response:
            response = self.github(method, url, **kwargs)
            if "/git/trees/" in url:
                response.status_code = 409
            return response

        with patch("posthog.models.github_integration_base.github_request", side_effect=empty_repository):
            response = self._detect()

        assert response.status_code == 200, response.json()
        assert response.json() == {
            "repository": "juniper/studio",
            "name": "Studio",
            "primary_color": None,
            "logo_url": None,
        }

    @parameterized.expand([(403, 400), (404, 400), (429, 429), (503, 429)])
    def test_reports_github_errors(self, github_status: int, expected_status: int) -> None:
        self.github.status = github_status

        response = self._detect()

        assert response.status_code == expected_status, response.json()
        if expected_status == 400:
            assert response.json()["attr"] == "repository"
        else:
            assert response.json()["detail"] == "GitHub is busy or unavailable, try again."

    def test_reports_an_egress_refusal_as_busy(self) -> None:
        with patch(
            "posthog.models.github_integration_base.github_request",
            side_effect=GitHubEgressBudgetExhausted("shed"),
        ):
            response = self._detect()

        assert response.status_code == 429, response.json()

    def test_rejects_an_invalid_repository_before_calling_github(self) -> None:
        response = self._detect({"repository": "../studio"})

        assert (response.status_code, response.json()["attr"]) == (400, "repository")
        assert self.github.calls == []

    def test_rejects_an_integration_of_another_environment(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other project")

        response = self._detect({"integration_id": self._integration_for(other_team).id})

        assert (response.status_code, response.json()["attr"]) == (400, "integration_id")
        assert self.github.calls == []

    def test_reuses_a_detection_for_ten_minutes(self) -> None:
        with time_machine.travel(timezone.now(), tick=False) as clock:
            first = self._detect().json()
            calls = len(self.github.calls)
            self.github.files["public/manifest.json"] = b'{"name": "Juniper Cloud"}'

            clock.shift(timedelta(minutes=9))
            assert self._detect().json() == first
            assert len(self.github.calls) == calls

            clock.shift(timedelta(minutes=2))
            assert self._detect().json()["name"] == "Juniper Cloud"

    def test_does_not_reuse_a_detection_that_ran_out_of_time(self) -> None:
        with patch("time.monotonic", return_value=100) as clock:

            def slow_github(method: str, url: str, **kwargs: object) -> requests.Response:
                if "/git/blobs/" in url:
                    clock.return_value = 116
                return self.github(method, url, **kwargs)

            with patch("posthog.models.github_integration_base.github_request", side_effect=slow_github):
                assert self._detect().status_code == 200
        self.github.files["public/manifest.json"] = b'{"name": "Juniper Cloud"}'

        response = self._detect()

        assert response.status_code == 200, response.json()
        assert response.json()["name"] == "Juniper Cloud"

    def test_stops_reading_a_slow_github_response_once_the_time_is_up(self) -> None:
        self.github.files = {f"src/module{index}.py": b"print()" for index in range(2000)}
        slow_streams: list[ClockAdvancingStream] = []
        with patch("time.monotonic", return_value=100) as clock:

            def slow_tree(method: str, url: str, **kwargs: object) -> requests.Response:
                response = self.github(method, url, **kwargs)
                if "/git/trees/" in url:
                    response.raw = ClockAdvancingStream(response.raw.getvalue(), clock)
                    slow_streams.append(response.raw)
                return response

            with patch("posthog.models.github_integration_base.github_request", side_effect=slow_tree):
                response = self._detect()

        assert response.status_code == 200, response.json()
        assert not any("/git/blobs/" in call for call in self.github.calls)
        assert slow_streams[0].unread_bytes > 0

    def test_stores_one_logo_for_an_environment_that_detects_twice(self) -> None:
        environment = Team.objects.create(organization=self.organization, parent_team=self.team, name="Staging")
        self.integration = self._integration_for(environment)

        for _ in range(2):
            cache.clear()
            response = self.client.post(
                f"/api/environments/{environment.id}/email_brand/detect_from_github/",
                {"integration_id": self.integration.id, "repository": "juniper/studio"},
                format="json",
            )
            assert response.status_code == 200, response.json()

        assert UploadedMedia.objects.filter(team_id=self.team.id).count() == 1

    def test_is_hidden_while_the_flag_is_off(self) -> None:
        with patch("posthoganalytics.feature_enabled", return_value=False):
            assert self._detect().status_code == 404
        assert self.github.calls == []

    def test_needs_write_access_because_it_stores_the_logo(self) -> None:
        key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="read only", user=self.user, secure_value=hash_key_value(key), scopes=["hog_flow:read"]
        )

        response = self._detect(authorization=f"Bearer {key}")

        assert response.status_code == 403
        assert self.github.calls == []
