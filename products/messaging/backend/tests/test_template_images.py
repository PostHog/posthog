import io
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized
from PIL import Image

from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.uploaded_media import UploadedMedia
from posthog.models.utils import generate_random_token_personal

from products.messaging.backend.models.message_template import MessageTemplate
from products.messaging.backend.models.provider_import_run import ProviderImportRun
from products.messaging.backend.provider_imports import runs
from products.messaging.backend.provider_imports.images import TemplateImages
from products.messaging.backend.provider_imports.mailchimp import MailchimpImportProvider
from products.messaging.backend.provider_imports.resend import ResendImportProvider
from products.messaging.backend.provider_imports.sendgrid import SendGridImportProvider
from products.messaging.backend.services.message_templates import update_template
from products.messaging.backend.tests.fake_mailchimp import FULL_KEY, FakeMailchimp, split_url
from products.workflows.backend.facade.contracts import CopiedImages, EmailImageSource

IMAGES = "products.messaging.backend.provider_imports.images"
HERO = "https://mcusercontent.com/abc/images/hero.png"
COPY = "https://posthog.example.com/uploaded_media/1"


class TestTemplateImages(SimpleTestCase):
    def _place(self, html: str, source: EmailImageSource | None = MailchimpImportProvider.image_source) -> str:
        images = TemplateImages(team_id=1, user_id=1, source=source, can_upload=True)
        with (
            patch(f"{IMAGES}.can_edit_media", return_value=True),
            patch(
                f"{IMAGES}.copy_images_for_team",
                lambda _team, _user, urls, *_, **__: CopiedImages(copies=dict.fromkeys(urls, COPY), downloads=0),
            ),
        ):
            images.copy([html])
            return images.place(html).html

    @parameterized.expand(
        [
            ("img", f'<img src="{HERO}">', f'<img src="{COPY}">'),
            ("unquoted", f"<img src={HERO}>", f"<img src={COPY}>"),
            ("old_http_host", '<img src="http://gallery.mailchimp.com/a.png">', f'<img src="{COPY}">'),
            ("no_scheme", "<img src='//dim.mcusercontent.com/a.png?w=1&amp;h=2'>", f"<img src='{COPY}'>"),
            (
                "srcset",
                f'<img srcset="{HERO} 1x, https://mcusercontent.com/b,c.png 2x, https://x.example.com/d.png 3x">',
                f'<img srcset="{COPY} 1x, {COPY} 2x, https://x.example.com/d.png 3x">',
            ),
            ("background", f'<td background="{HERO}">', f'<td background="{COPY}">'),
            ("css_plain", f"<style>a{{background:url({HERO})}}</style>", f"<style>a{{background:url({COPY})}}</style>"),
            (
                "css_in_style_attribute",
                f"""<td style="background:url('{HERO}') no-repeat">""",
                f"""<td style="background:url('{COPY}') no-repeat">""",
            ),
            (
                "css_escaped_quotes",
                f'<td style="background:url(&quot;{HERO}&quot;)">',
                f'<td style="background:url(&quot;{COPY}&quot;)">',
            ),
            (
                "outlook_vml",
                f'<!--[if mso]><v:fill type="frame" src="{HERO}" /><v:imagedata src="{HERO}"/><![endif]-->',
                f'<!--[if mso]><v:fill type="frame" src="{COPY}" /><v:imagedata src="{COPY}"/><![endif]-->',
            ),
        ]
    )
    def test_points_every_kind_of_image_at_its_copy(self, _name: str, html: str, expected: str) -> None:
        assert self._place(html) == expected

    @parameterized.expand(
        [
            ("own_domain", '<img src="https://img.example.com/a.png">'),
            ("link", f'<a href="{HERO}">{HERO}</a>'),
            ("image_named_in_a_link", f'<a href="https://example.com/?src={HERO}&background={HERO}">x</a>'),
            ("lazy_attribute", f'<img data-src="{HERO}">'),
            ("lookalike_suffix", '<img src="https://evilmcusercontent.com/a.png">'),
            ("lookalike_prefix", '<img src="https://mcusercontent.com.example.com/a.png">'),
            ("user_info", '<img src="https://mcusercontent.com@example.com/a.png">'),
            ("user_info_on_the_host", '<img src="https://example.com:x@mcusercontent.com/a.png">'),
            ("encoded_at", '<img src="https://mcusercontent.com&#64;example.com/a.png">'),
            ("backslash", '<img src="https://example.com\\@mcusercontent.com/a.png">'),
            ("port", '<img src="https://mcusercontent.com:8443/a.png">'),
            ("bad_port", '<img src="https://mcusercontent.com:x/a.png">'),
            ("unicode_lookalike", '<img src="https://mcusercontent.cоm/a.png">'),
            ("other_bucket", '<img src="https://other.s3.amazonaws.com/mcusercontent.com/a.png">'),
            ("merge_tag", '<img src="https://mcusercontent.com/*|MERGE|*.png">'),
            ("liquid", '<img src="https://mcusercontent.com/{{ person.properties.x }}.png">'),
            ("encoded_liquid", '<img src="https://mcusercontent.com/%7B%7B x %7D%7D.png">'),
        ]
    )
    def test_leaves_everything_else_as_it_is(self, _name: str, html: str) -> None:
        assert self._place(html) == html

    @parameterized.expand(
        [
            (SendGridImportProvider, "https://cdn.mcauto-images-production.sendgrid.net/x/1x1.png", True),
            (SendGridImportProvider, "https://marketing-image-production.s3.amazonaws.com/uploads/a.png", True),
            (SendGridImportProvider, "https://u1.ct.sendgrid.net/a.png", False),
            (ResendImportProvider, "https://resend-attachments.s3.amazonaws.com/abc", True),
            (ResendImportProvider, HERO, False),
        ]
    )
    def test_each_provider_reads_only_its_own_hosts(self, provider: Any, url: str, copied: bool) -> None:
        assert (self._place(f'<img src="{url}">', provider.image_source) != f'<img src="{url}">') is copied

    @parameterized.expand(["src=\"url('&quot;", "url(&quot;", "src='", 'srcset="'])
    def test_a_huge_body_of_unclosed_quotes_scans_quickly(self, unit: str) -> None:
        body = unit * 100_000
        assert self._place(body) == body


class TestTemplateImageImport(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.mailchimp = FakeMailchimp()
        png = io.BytesIO()
        Image.new("RGB", (3, 2)).save(png, "PNG")
        self.png = png.getvalue()
        self.served = {HERO}
        self.requested: list[str] = []
        self._patch("products.messaging.backend.provider_imports.runs.start_provider_import_workflow")
        # Both modules share one `requests`, so one stand-in answers for the API and the image host.
        self._patch("products.messaging.backend.services.mailchimp_client.requests.get", self._get)
        self._patch("products.messaging.backend.services.mailchimp_client.REQUESTS_PER_SECOND", 100000)
        self.campaign = self.mailchimp.data["campaigns"][0]

    def _patch(self, target: str, *replacement: Any) -> Any:
        patcher = patch(target, *replacement)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def _get(self, url: str, params: dict | None = None, headers: dict | None = None, **kwargs: Any) -> MagicMock:
        if "mcusercontent.com" in url:
            self.requested.append(url)
            assert kwargs["allow_redirects"] is False
            response = MagicMock(status_code=200 if url in self.served else 404)
            response.__enter__.return_value = response
            response.raw = io.BytesIO(self.png)
            return response
        _, path, query = split_url(url)
        query = {**query, **{key: str(value) for key, value in (params or {}).items()}}
        status, body, response_headers = self.mailchimp.handle(path, query, (headers or {}).get("Authorization", ""))
        response = MagicMock(status_code=status, ok=status < 400, headers=response_headers)
        response.json.return_value = body
        return response

    def _run(self, image_access: runs.ImageAccess | None = runs.COPY_IMAGES) -> ProviderImportRun:
        run = runs.start_run(
            self.team.id, "mailchimp", ["campaigns"], FULL_KEY, self.user.id, {}, image_access=image_access
        )
        runs.run_step(self.team.id, run.id, "campaigns", attempt=1)
        runs.finish_run(self.team.id, run.id)
        run.refresh_from_db()
        return run

    def _template(self) -> MessageTemplate:
        return MessageTemplate.objects.get(team_id=self.team.id, key=f"mailchimp-campaign-{self.campaign['id']}")

    def _notes(self, run: ProviderImportRun) -> str:
        items = run.progress["campaigns"]["items"]
        return " ".join(next(i for i in items if (i["url"] or "").endswith(str(self._template().id)))["notes"])

    def test_copies_once_names_what_it_missed_and_keeps_edits(self) -> None:
        gone = "https://mcusercontent.com/abc/images/gone.png"
        tagged = "https://mcusercontent.com/abc/*|MERGE7|*.png"
        self.campaign["content"]["html"] = (
            f'<img src="{HERO}"><td background="{HERO}"><img src="{gone}"><img src="{tagged}">'
        )

        run = self._run()

        assert run.status == "completed", run.progress
        media = UploadedMedia.objects.get(team=self.team, purpose="email")
        assert (media.created_by, media.width, media.size_bytes) == (self.user, 3, len(self.png))
        email = self._template().content["email"]
        assert email["html"].count(media.get_absolute_url()) == 2
        assert HERO not in str(email["design"]) and media.get_absolute_url() in str(email["design"])
        notes = self._notes(run)
        assert gone in notes and "address holds a template tag" in notes
        assert gone in self._template().description

        # Same images in a campaign made later: the copy is used again, and the edited template stays.
        update_template(self.team.id, self._template().id, {"content": {"email": {"html": "edited"}}})
        self.mailchimp.data["campaigns"].append({**self.campaign, "id": "later1"})
        self._run()

        assert self._template().content == {"email": {"html": "edited"}}
        later = MessageTemplate.objects.get(team_id=self.team.id, key="mailchimp-campaign-later1")
        assert media.get_absolute_url() in later.content["email"]["html"]
        assert self.requested.count(HERO) == 1
        assert UploadedMedia.objects.filter(team=self.team).count() == 1

        # Nothing new to import, so nothing is requested, not even the image that failed.
        before = len(self.requested)
        self._run()
        assert len(self.requested) == before

    @parameterized.expand(
        [
            ("flag_off", None, True, ""),
            ("no_access_at_start", runs.NO_IMAGE_ACCESS, True, "uploaded_media:write"),
            ("access_lost_since", runs.COPY_IMAGES, False, "uploaded_media:write"),
        ]
    )
    def test_nothing_is_requested_without_permission(
        self, _name: str, image_access: runs.ImageAccess | None, can_edit: bool, note: str
    ) -> None:
        self.campaign["content"]["html"] = f'<img src="{HERO}">'
        with patch(f"{IMAGES}.can_edit_media", return_value=can_edit):
            run = self._run(image_access)

        assert run.status == "completed"
        assert HERO in self._template().content["email"]["html"]
        assert self.requested == []
        assert note in self._notes(run)

    @parameterized.expand(
        [
            ("with_media_scope", True, ["uploaded_media:write"], True),
            ("without_media_scope", True, [], False),
            ("flag_off", False, ["uploaded_media:write"], False),
        ]
    )
    def test_a_key_copies_images_only_with_the_media_scope(
        self, _name: str, flag: bool, extra_scopes: list[str], copied: bool
    ) -> None:
        self.campaign["content"]["html"] = f'<img src="{HERO}">'
        key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="key",
            user=self.user,
            secure_value=hash_key_value(key),
            scopes=["hog_flow:write", "person:read", *extra_scopes],
        )
        self.client.logout()
        with patch(
            "products.messaging.backend.facade.provider_imports.feature_enabled_or_false",
            side_effect=lambda name, *_args, **_kwargs: flag or name != "workflows-import-template-images",
        ):
            response = self.client.post(
                f"/api/projects/{self.team.id}/messaging_provider_imports/",
                {"provider": "mailchimp", "steps": ["campaigns"], "api_key": FULL_KEY},
                headers={"authorization": f"Bearer {key}"},
            )
        assert response.status_code == 201, response.json()
        runs.run_step(self.team.id, response.json()["id"], "campaigns", attempt=1)

        assert UploadedMedia.objects.filter(team=self.team).exists() is copied
