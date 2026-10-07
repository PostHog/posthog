import io
import time
import ipaddress
import threading
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from typing import cast
from urllib.parse import urlparse

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from django.core.cache import cache
from django.http import HttpResponse, StreamingHttpResponse
from django.test import override_settings

import requests
from parameterized import parameterized
from PIL import Image
from requests.adapters import HTTPAdapter
from requests.structures import CaseInsensitiveDict
from rest_framework import status

from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.uploaded_media import UploadedMedia
from posthog.models.utils import generate_random_token_personal

from products.messaging.backend.services.brand_detection import DetectedBrand, detected_brand

PUBLIC_IP = "93.184.216.34"
PRIVATE_IP = "10.0.0.7"


def png(width: int, height: int, color: tuple[int, int, int] = (46, 125, 50)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, format="PNG")
    return buffer.getvalue()


class FakeClock:
    def __init__(self) -> None:
        self.now = time.monotonic()

    def monotonic(self) -> float:
        return self.now


class TricklingBody(io.RawIOBase):
    def __init__(self, body: bytes, clock: FakeClock, seconds_per_byte: float) -> None:
        self.body = body
        self.clock = clock
        self.seconds_per_byte = seconds_per_byte

    def readable(self) -> bool:
        return True

    def read1(self, size: int = -1) -> bytes:
        if not self.body:
            return b""
        self.clock.now += self.seconds_per_byte
        byte, self.body = self.body[:1], self.body[1:]
        return byte

    def read(self, size: int = -1) -> bytes:
        received = b""
        while self.body and (size < 0 or len(received) < size):
            received += self.read1()
        return received


class StalledBody(io.RawIOBase):
    def readable(self) -> bool:
        return True

    def read1(self, size: int = -1) -> bytes:
        raise TimeoutError("timed out")


class Urllib3Body:
    def __init__(self, body: io.RawIOBase | io.BytesIO) -> None:
        self._fp = body

    def read(self, size: int = -1) -> bytes:
        return self._fp.read(size)

    def close(self) -> None:
        self._fp.close()


class FakeWeb:
    def __init__(self) -> None:
        self.addresses: dict[str, str] = {}
        self.pages: dict[str, tuple[int, dict[str, str], bytes | io.RawIOBase]] = {}
        self.requested: list[str] = []
        self.on_request: dict[str, Callable[[], None]] = {}
        self.clock: FakeClock | None = None
        self.dns_seconds = 0.0

    def serve(
        self,
        url: str,
        body: bytes | io.RawIOBase = b"",
        *,
        content_type: str = "text/html",
        status_code: int = 200,
        ip: str = PUBLIC_IP,
    ) -> None:
        self.addresses[urlparse(url).hostname or ""] = ip
        self.pages[url] = (status_code, {"Content-Type": content_type}, body)

    def redirect(self, url: str, location: str, *, ip: str = PUBLIC_IP) -> None:
        self.addresses[urlparse(url).hostname or ""] = ip
        self.pages[url] = (302, {"Location": location}, b"")

    def resolve(self, host: str) -> set[ipaddress.IPv4Address]:
        if self.clock:
            self.clock.now += self.dns_seconds
        return {ipaddress.IPv4Address(self.addresses[host])} if host in self.addresses else set()

    def send(self, request: requests.PreparedRequest, **_kwargs: object) -> requests.Response:
        parsed = urlparse(request.url or "")
        url = f"{parsed.scheme}://{request.headers['Host']}{parsed.path or '/'}"
        self.requested.append(url)
        if hook := self.on_request.pop(url, None):
            hook()
        status_code, headers, body = self.pages.get(url, (404, {}, b""))
        response = requests.Response()
        response.status_code = status_code
        response.headers = CaseInsensitiveDict(headers)
        response.raw = Urllib3Body(io.BytesIO(body) if isinstance(body, bytes) else body)
        response.url = url
        return response


@override_settings(
    FORCE_URL_VALIDATION=True, OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_MEDIA_UPLOADS_FOLDER="test_brand_detection"
)
class TestDetectBrand(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        self.web = FakeWeb()
        for patcher in (
            patch("posthog.security.url_validation.resolve_host_ips", side_effect=self.web.resolve),
            patch.object(HTTPAdapter, "send", new=self.web.send),
            patch("posthoganalytics.feature_enabled", return_value=True),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def detect(self) -> dict:
        response = self.client.post(f"/api/projects/{self.team.id}/messaging_templates/detect_brand/")
        assert response.status_code == status.HTTP_200_OK, response.json()
        return response.json()

    def serve_juniper_site(self) -> None:
        self.web.serve(
            "https://juniper.example/",
            b"""<html><head>
                <title>Juniper Studio | Home</title>
                <meta name="msapplication-TileColor" content="#2d89ef">
                <link rel="manifest" href="/site.webmanifest">
                <link rel="icon" sizes="32x32" href="/favicon-32.png">
            </head></html>""",
        )
        self.web.serve(
            "https://juniper.example/site.webmanifest",
            b'{"theme_color": "#2e7d32", "icons": [{"src": "/icon-512.png", "sizes": "512x512"}]}',
            content_type="application/manifest+json",
        )
        self.web.serve("https://juniper.example/icon-512.png", png(512, 512), content_type="image/png")
        self.web.serve("https://juniper.example/favicon-32.png", png(32, 32), content_type="image/png")

    def test_detects_the_brand_of_the_first_public_authorized_url_and_hosts_its_logo(self) -> None:
        self.team.app_urls = ["http://localhost:3000", "https://preview-123.vercel.app", "https://juniper.example"]
        self.team.save()
        self.serve_juniper_site()

        brand = self.detect()

        assert {key: brand[key] for key in ("website", "name", "primary_color")} == {
            "website": "https://juniper.example/",
            "name": "Juniper Studio",
            "primary_color": "#2e7d32",
        }
        logo = cast(HttpResponse | StreamingHttpResponse, self.client.get(urlparse(brand["logo_url"]).path))
        assert logo.status_code == status.HTTP_200_OK
        assert logo["Content-Type"] == "image/png"
        assert b"".join(
            cast(Iterable[bytes], logo.streaming_content) if isinstance(logo, StreamingHttpResponse) else [logo.content]
        ) == png(512, 512)

    def test_falls_back_to_the_most_viewed_public_host(self) -> None:
        preview_hosts = [(f"pr-{number}.juniper.vercel.app", 4) for number in range(10)]
        for host, views in [("localhost:8000", 5), *preview_hosts, ("juniper.example", 3), ("other.example", 2)]:
            for _ in range(views):
                _create_event(team=self.team, event="$pageview", distinct_id="visitor", properties={"$host": host})
        flush_persons_and_events()
        self.serve_juniper_site()

        assert self.detect()["name"] == "Juniper Studio"

    def test_reports_nothing_without_a_public_website(self) -> None:
        self.team.app_urls = ["http://localhost:3000", "http://192.168.1.20"]
        self.team.save()

        assert self.detect() == {"website": None, "name": None, "primary_color": None, "logo_url": None}
        assert self.web.requested == []

    def test_detects_once_a_day_and_keeps_one_copy_of_an_unchanged_logo(self) -> None:
        self.team.app_urls = ["https://juniper.example"]
        self.team.save()
        self.serve_juniper_site()

        first = self.detect()
        fetches = len(self.web.requested)
        assert first["logo_url"] is not None

        with time_machine.travel(datetime.now(UTC) + timedelta(hours=23)):
            assert (self.detect(), len(self.web.requested)) == (first, fetches)
        with time_machine.travel(datetime.now(UTC) + timedelta(hours=25)):
            assert self.detect()["logo_url"] == first["logo_url"]
            assert len(self.web.requested) > fetches

    def test_retries_an_unreachable_website_soon_instead_of_waiting_a_day(self) -> None:
        self.team.app_urls = ["https://juniper.example"]
        self.team.save()
        self.web.serve("https://juniper.example/", status_code=503)

        assert self.detect()["name"] is None
        self.web.serve("https://juniper.example/", b"<title>Juniper Studio</title>")

        with time_machine.travel(datetime.now(UTC) + timedelta(minutes=16)):
            assert self.detect()["name"] == "Juniper Studio"

    def test_reads_the_head_of_a_home_page_larger_than_it_downloads(self) -> None:
        self.team.app_urls = ["https://juniper.example"]
        self.team.save()
        self.web.serve(
            "https://juniper.example/",
            b'<head><meta name="theme-color" content="#ff6600"><title>Juniper</title></head>'
            + b"<body>"
            + b"x" * (3 * 1024 * 1024)
            + b"</body>",
        )

        brand = self.detect()

        assert (brand["name"], brand["primary_color"]) == ("Juniper", "#ff6600")

    @parameterized.expand(
        [
            ("private_address", "http://internal.example/admin"),
            ("malformed", "http://[internal"),
            ("bad_port", "https://user@other.example:bad/"),
        ]
    )
    def test_refuses_a_redirect_it_cannot_safely_follow(self, _name: str, location: str) -> None:
        self.team.app_urls = ["https://juniper.example"]
        self.team.save()
        self.web.redirect("https://juniper.example/", location)
        self.web.serve("http://internal.example/admin", b"<title>Internal admin</title>", ip=PRIVATE_IP)

        brand = self.detect()

        assert (brand["website"], brand["name"]) == ("https://juniper.example/", None)
        assert "http://internal.example/admin" not in self.web.requested

    def test_stops_reading_a_trickling_page_at_the_deadline(self) -> None:
        self.team.app_urls = ["https://juniper.example"]
        self.team.save()
        clock = FakeClock()
        started = clock.now
        self.web.serve("https://juniper.example/", TricklingBody(b"<title>Juniper</title>" * 10, clock, 1.0))

        with patch("time.monotonic", side_effect=clock.monotonic):
            brand = self.detect()

        assert brand["name"] is None
        assert clock.now - started <= 16

    @parameterized.expand(
        [
            ("declared_charset", "windows-1252", "Café Juniper".encode("cp1252"), "Café Juniper"),
            ("unknown_charset", "klingon", "Café Juniper".encode(), "Café Juniper"),
            ("binary_codec", "base64", "Café Juniper".encode(), "Café Juniper"),
        ]
    )
    def test_decodes_the_page_text(self, _name: str, charset: str, title: bytes, expected: str) -> None:
        self.team.app_urls = ["https://juniper.example"]
        self.team.save()
        self.web.serve(
            "https://juniper.example/",
            b"<title>" + title + b"</title>",
            content_type=f"text/html; charset={charset}",
        )

        assert self.detect()["name"] == expected

    def test_survives_a_page_that_stalls_mid_body(self) -> None:
        self.team.app_urls = ["https://juniper.example"]
        self.team.save()
        self.web.serve("https://juniper.example/", StalledBody())

        assert self.detect() == {
            "website": "https://juniper.example/",
            "name": None,
            "primary_color": None,
            "logo_url": None,
        }

    def test_stops_choosing_a_website_at_the_deadline(self) -> None:
        self.team.app_urls = [f"https://dead-{number}.juniper.example" for number in range(20)]
        self.team.save()
        clock = FakeClock()
        started = clock.now
        self.web.clock, self.web.dns_seconds = clock, 2.0

        with patch("time.monotonic", side_effect=clock.monotonic):
            assert self.detect()["website"] is None

        assert clock.now - started <= 18

    def test_skips_an_authorized_url_that_resolves_to_a_private_address(self) -> None:
        self.team.app_urls = ["https://staging.juniper.example", "https://juniper.example"]
        self.team.save()
        self.web.serve("https://staging.juniper.example/", b"<title>Staging</title>", ip=PRIVATE_IP)
        self.serve_juniper_site()

        assert self.detect()["website"] == "https://juniper.example/"

    def test_keeps_no_logo_record_while_object_storage_is_off(self) -> None:
        self.team.app_urls = ["https://juniper.example"]
        self.team.save()
        self.serve_juniper_site()

        with self.settings(OBJECT_STORAGE_ENABLED=False):
            assert self.detect()["logo_url"] is None
        assert not UploadedMedia.objects.filter(team=self.team).exists()

    def test_a_concurrent_request_waits_for_the_running_detection(self) -> None:
        self.team.app_urls = ["https://juniper.example"]
        self.team.save()
        self.serve_juniper_site()
        concurrent: list[DetectedBrand] = []
        waiter = threading.Thread(target=lambda: concurrent.append(detected_brand(self.team, self.user)))
        self.web.on_request["https://juniper.example/"] = waiter.start

        brand = self.detect()
        waiter.join(timeout=10)

        assert concurrent and concurrent[0].logo_url == brand["logo_url"]
        assert self.web.requested.count("https://juniper.example/") == 1

    @parameterized.expand(
        [
            ("svg", b'<svg xmlns="http://www.w3.org/2000/svg"></svg>', "image/png"),
            ("html_posing_as_png", b"<html><script>alert(1)</script></html>", "image/png"),
            ("too_small", png(32, 32), "image/png"),
            ("too_large", png(16, 16) + b"\0" * (4 * 1024 * 1024), "image/png"),
        ]
    )
    def test_skips_a_logo_it_cannot_safely_host(self, _name: str, body: bytes, content_type: str) -> None:
        self.team.app_urls = ["https://juniper.example"]
        self.team.save()
        self.web.serve(
            "https://juniper.example/",
            b'<title>Juniper</title><link rel="apple-touch-icon" href="/apple-touch-icon.png">',
        )
        self.web.serve("https://juniper.example/apple-touch-icon.png", body, content_type=content_type)

        brand = self.detect()

        assert (brand["name"], brand["logo_url"]) == ("Juniper", None)

    def test_is_hidden_while_the_flag_is_off(self) -> None:
        with (
            patch("posthoganalytics.feature_enabled", return_value=False),
            patch("products.messaging.backend.api.message_templates.detected_brand") as detection,
        ):
            response = self.client.post(f"/api/projects/{self.team.id}/messaging_templates/detect_brand/")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        detection.assert_not_called()

    def test_is_hidden_when_flag_evaluation_fails(self) -> None:
        with (
            patch("posthoganalytics.feature_enabled", side_effect=RuntimeError("flag unavailable")),
            patch("products.messaging.backend.api.message_templates.detected_brand") as detection,
        ):
            response = self.client.post(f"/api/projects/{self.team.id}/messaging_templates/detect_brand/")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        detection.assert_not_called()

    def test_needs_write_access_to_workflows(self) -> None:
        key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="read only", user=self.user, secure_value=hash_key_value(key), scopes=["hog_flow:read"]
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/messaging_templates/detect_brand/", HTTP_AUTHORIZATION=f"Bearer {key}"
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
