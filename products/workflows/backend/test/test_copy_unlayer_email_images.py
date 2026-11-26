import io
import json
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from parameterized import parameterized
from PIL import Image
from urllib3 import HTTPConnectionPool, HTTPResponse

from posthog.models import Team
from posthog.models.uploaded_media import UploadedMedia
from posthog.storage import object_storage

from products.messaging.backend.facade.api import get_template_email_content
from products.messaging.backend.facade.testing import (
    create_message_template_for_test,
    get_message_template_draft_for_test,
)
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.hog_flow.hog_flow_template import HogFlowTemplate
from products.workflows.backend.services.unlayer_images import find_source_keys, replace_in_blob

BANNER = "https://assets.unlayer.com/projects/275430/1712000000000-banner.png"
SANDBOX = "https://assets.unlayer.com/projects/0/1690000000000-logo.png"
GONE = "https://assets.unlayer.com/projects/0/1690000000001-gone.png"
COPY = "https://media.example.com/uploaded_media/copy"


def _png() -> bytes:
    data = io.BytesIO()
    Image.new("RGB", (3, 2)).save(data, "PNG")
    return data.getvalue()


def _email_action(html: str, design: Any) -> dict[str, Any]:
    return {
        "id": "action_email",
        "type": "function_email",
        "config": {
            "template_id": "template-email",
            "inputs": {"email": {"templating": "liquid", "value": {"html": html, "design": design, "subject": "Hi"}}},
        },
    }


def _unlayer_html(url: str) -> str:
    # Unlayer writes each image twice: once for Outlook, once for every other client.
    return (
        f'<!--[if mso]><img src="{url}" width="600" /><![endif]-->'
        f'<!--[if !mso]><!--><img src="{url}" style="width:100%" /><!--<![endif]-->'
    )


class TestReplaceInBlob(SimpleTestCase):
    @parameterized.expand(
        [
            ("plain", f'<img src="{BANNER}">', f'<img src="{COPY}">'),
            ("query string kept", f'<img src="{BANNER}?w=960px">', f'<img src="{COPY}?w=960px">'),
            (
                "protocol relative",
                '<img src="//assets.unlayer.com/projects/275430/1712000000000-banner.png">',
                f'<img src="{COPY}">',
            ),
            (
                "doubled slash",
                '<img src="https://assets.unlayer.com//projects/275430/1712000000000-banner.png">',
                f'<img src="{COPY}">',
            ),
            ("css url", f"background-image: url('{BANNER}');", f"background-image: url('{COPY}');"),
            ("css url with entities", f"background: url(&quot;{BANNER}&quot;)", f"background: url(&quot;{COPY}&quot;)"),
            ("css url unquoted", f"background: url({BANNER}) no-repeat", f"background: url({COPY}) no-repeat"),
            (
                "liquid in the address",
                f'<img src="{BANNER}/{{{{ person.id }}}}">',
                f'<img src="{BANNER}/{{{{ person.id }}}}">',
            ),
            (
                "lookalike host",
                '<img src="https://assets.unlayer.com.evil.example/projects/1/a.png">',
                '<img src="https://assets.unlayer.com.evil.example/projects/1/a.png">',
            ),
            (
                "another host",
                '<img src="https://cdn.tools.unlayer.com/social/icons/x.png">',
                '<img src="https://cdn.tools.unlayer.com/social/icons/x.png">',
            ),
            (
                "quoted address with a space in the file name",
                '<img src="https://assets.unlayer.com/projects/275430/1712000000000 banner.png?w=2">',
                f'<img src="{COPY}?w=2">',
            ),
            ("plain text after the address", f"{BANNER} is our banner", f"{COPY} is our banner"),
            ("two addresses on their own lines", f"{BANNER}\n{BANNER}", f"{COPY}\n{COPY}"),
        ]
    )
    def test_replaces_every_spelling_of_a_copied_image_and_nothing_else(
        self, _name: str, before: str, after: str
    ) -> None:
        copies = {BANNER: COPY, "https://assets.unlayer.com/projects/275430/1712000000000%20banner.png": COPY}
        assert replace_in_blob({"html": before}, copies)[0] == {"html": after}

    @parameterized.expand(
        [
            ("plain text after the address", f"{BANNER} is our banner", [BANNER]),
            ("text after the address that ends like a file name", f"{BANNER} and see example.com", [BANNER]),
            ("two addresses on their own lines", f"{BANNER}\n{BANNER}", [BANNER, BANNER]),
            ("liquid in a whole value", f"{BANNER}{{{{ person.id }}}}", []),
            ("a path that climbs out of its project", "https://assets.unlayer.com/projects/1/../../a.png", []),
            ("another address after a space", f"{BANNER} https://example.com/b.png", [BANNER]),
            ("an image name after a space", f"{BANNER} and see logo.png", [BANNER]),
            (
                "a file name with spaces and dots",
                "https://assets.unlayer.com/projects/0/1-Screenshot 2024-05-01 at 10.30.45 AM.png",
                ["https://assets.unlayer.com/projects/0/1-Screenshot%202024-05-01%20at%2010.30.45%20AM.png"],
            ),
        ]
    )
    def test_collects_only_real_addresses_from_a_text_value(self, _name: str, text: str, keys: list[str]) -> None:
        assert find_source_keys(text) == keys

    def test_an_encoded_space_and_a_literal_space_are_one_file(self) -> None:
        key = "https://assets.unlayer.com/projects/0/1-my%20logo.png"
        blob = {
            "html": '<img src="https://assets.unlayer.com/projects/0/1-my%20logo.png">',
            "design": {"url": "https://assets.unlayer.com/projects/0/1-my logo.png"},
        }
        new_blob, count = replace_in_blob(blob, {key: COPY})
        assert count == 2
        assert new_blob == {"html": f'<img src="{COPY}">', "design": {"url": COPY}}


@override_settings(UPLOADED_MEDIA_PUBLIC_URL="https://media.example.com")
class TestCopyUnlayerEmailImages(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.other_team = Team.objects.create(organization=self.organization, name="other")
        self.served: dict[str, int] = {BANNER: 200, SANDBOX: 403, GONE: 404}
        self.requested: list[str] = []
        # The fake sits under requests, so it sees the request target exactly as it goes on the wire.
        original = HTTPConnectionPool.urlopen

        def urlopen(pool: HTTPConnectionPool, method: str, url: str, **kwargs: Any) -> HTTPResponse:
            if pool.host != "assets.unlayer.com":
                return original(pool, method, url, **kwargs)
            return self._respond(f"https://{pool.host}{url}")

        patcher = patch.object(HTTPConnectionPool, "urlopen", urlopen)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _respond(self, address: str) -> HTTPResponse:
        self.requested.append(address)
        # Unlayer's sandbox refuses some files at their address but serves them at the doubled slash.
        status = 200 if address == SANDBOX.replace("/projects/", "//projects/") else self.served.get(address, 404)
        return HTTPResponse(body=io.BytesIO(_png()), status=status, headers={}, preload_content=False)

    def _flow(self, team: Team, html: str, design: Any) -> HogFlow:
        return HogFlow.objects.create(
            team=team,
            name="flow",
            actions=[_email_action(html, design)],
            edges=[],
            draft={"actions": [_email_action(html, design)]},
        )

    def _run(self, *args: str) -> None:
        call_command("copy_unlayer_email_images", "--team-id", str(self.team.id), "--rate", "1000", *args)

    def test_copies_each_image_once_per_team_and_points_every_row_at_it(self) -> None:
        design = {"body": {"rows": [{"values": {"backgroundImage": {"url": SANDBOX}}}]}, "src": {"url": BANNER}}
        html = (
            _unlayer_html(BANNER)
            + f'<div style="background-image: url(&quot;{SANDBOX}&quot;)"></div>'
            + _unlayer_html(GONE)
        )
        flow = self._flow(self.team, html, design)
        template = create_message_template_for_test(
            team_id=self.team.id,
            name="t",
            content={"email": {"html": _unlayer_html(BANNER), "design": design}},
            draft_content={"email": {"html": _unlayer_html(BANNER)}},
        )
        theirs = self._flow(self.other_team, html, design)
        their_actions = theirs.actions

        self._run("--dry-run")
        flow.refresh_from_db()
        assert flow.actions[0]["config"]["inputs"]["email"]["value"]["html"] == html
        assert not UploadedMedia.objects.filter(team=self.team).exists()

        self._run()

        copies = {m.file_name: m for m in UploadedMedia.objects.filter(team=self.team, created_by__isnull=True)}
        assert len(copies) == 2
        assert [(m.content_type, m.width, m.height, m.purpose) for m in copies.values()] == [
            ("image/png", 3, 2, "email")
        ] * 2
        banner, sandbox = (next(m for name, m in copies.items() if part in (name or "")) for part in ("banner", "logo"))
        flow.refresh_from_db()
        value = flow.actions[0]["config"]["inputs"]["email"]["value"]
        expected_html = (
            _unlayer_html(banner.get_absolute_url())
            + f'<div style="background-image: url(&quot;{sandbox.get_absolute_url()}&quot;)"></div>'
            + _unlayer_html(GONE)
        )
        assert value["html"] == expected_html
        assert value["design"] == {
            "body": {"rows": [{"values": {"backgroundImage": {"url": sandbox.get_absolute_url()}}}]},
            "src": {"url": banner.get_absolute_url()},
        }
        assert value["subject"] == "Hi"
        assert (flow.draft or {})["actions"][0]["config"]["inputs"]["email"]["value"]["html"] == expected_html
        assert (get_template_email_content(self.team.id, template) or {})["html"] == _unlayer_html(
            banner.get_absolute_url()
        )
        assert get_message_template_draft_for_test(self.team.id, template) == {
            "email": {"html": _unlayer_html(banner.get_absolute_url())}
        }
        theirs.refresh_from_db()
        assert theirs.actions == their_actions

        requested_before = len(self.requested)
        self._run()
        assert UploadedMedia.objects.filter(team=self.team).count() == 2
        # Only the image that can't be copied is asked for again.
        assert self.requested[requested_before:] == [GONE]
        assert SANDBOX.replace("/projects/", "//projects/") in self.requested[:requested_before]

    def test_a_second_environment_of_the_project_reuses_the_project_copy(self) -> None:
        environment = Team.objects.create(organization=self.organization, name="staging", parent_team=self.team)
        self._flow(self.team, _unlayer_html(BANNER), {"src": {"url": BANNER}})
        self._flow(environment, _unlayer_html(BANNER), {"src": {"url": BANNER}})

        self._run()
        call_command("copy_unlayer_email_images", "--team-id", str(environment.id), "--rate", "1000")

        assert UploadedMedia.objects.filter(team_id=self.team.id, created_by__isnull=True).count() == 1

    @parameterized.expand([("unlayer is down", 503, True), ("the file is gone", 404, False)])
    def test_a_failed_download_leaves_the_row_unchanged(self, _name: str, status: int, fails_the_run: bool) -> None:
        self.served[BANNER] = status
        flow = self._flow(self.team, _unlayer_html(BANNER), {"src": {"url": BANNER}})

        if fails_the_run:
            with self.assertRaises(CommandError):
                self._run()
        else:
            self._run()

        flow.refresh_from_db()
        assert flow.actions[0]["config"]["inputs"]["email"]["value"]["html"] == _unlayer_html(BANNER)
        assert not UploadedMedia.objects.filter(team_id=self.team.id).exists()

    @parameterized.expand([("same bytes", False, 1), ("other bytes under the same name", True, 2)])
    def test_reuses_an_earlier_copy_only_when_it_holds_the_same_image(
        self, _name: str, replace_bytes: bool, copies: int
    ) -> None:
        self._flow(self.team, _unlayer_html(BANNER), {"src": {"url": BANNER}})
        self._run()
        earlier = UploadedMedia.objects.get(team_id=self.team.id, created_by__isnull=True)
        if replace_bytes:
            object_storage.write(earlier.media_location or "", b"\x89PNG not the banner")
        later = self._flow(self.team, _unlayer_html(BANNER), {"src": {"url": BANNER}})

        self._run()

        assert UploadedMedia.objects.filter(team_id=self.team.id, created_by__isnull=True).count() == copies
        later.refresh_from_db()
        html = later.actions[0]["config"]["inputs"]["email"]["value"]["html"]
        assert (earlier.get_absolute_url() in html) is not replace_bytes

    @parameterized.expand([("taken down", False), ("taken down and its file deleted", True)])
    def test_leaves_an_image_whose_copy_was_taken_down_on_unlayer(self, _name: str, delete_file: bool) -> None:
        self._flow(self.team, _unlayer_html(BANNER), {"src": {"url": BANNER}})
        self._run()
        UploadedMedia.objects.filter(team_id=self.team.id).update(serving_disabled_at=timezone.now())
        if delete_file:
            UploadedMedia.delete_stored_files(list(UploadedMedia.objects.filter(team_id=self.team.id)))
        later = self._flow(self.team, _unlayer_html(BANNER), {"src": {"url": BANNER}})
        requested_before = len(self.requested)

        self._run()

        later.refresh_from_db()
        assert later.actions[0]["config"]["inputs"]["email"]["value"]["html"] == _unlayer_html(BANNER)
        assert UploadedMedia.objects.filter(team_id=self.team.id).count() == 1
        assert self.requested[requested_before:] == []

    def test_leaves_a_team_with_too_many_images_untouched(self) -> None:
        flow = self._flow(self.team, _unlayer_html(BANNER) + _unlayer_html(SANDBOX), {})

        with self.assertRaises(CommandError):
            self._run("--max-images-per-team", "1")

        flow.refresh_from_db()
        assert flow.actions[0]["config"]["inputs"]["email"]["value"]["html"] == _unlayer_html(BANNER) + _unlayer_html(
            SANDBOX
        )
        assert self.requested == []

    def test_refuses_a_negative_team_limit(self) -> None:
        with self.assertRaises(CommandError):
            call_command("copy_unlayer_email_images", "--all-teams", "--max-teams", "-1")

    @override_settings(UPLOADED_MEDIA_PUBLIC_URL="", SITE_URL="http://localhost:8000")
    def test_refuses_to_write_copies_recipients_cannot_load(self) -> None:
        flow = self._flow(self.team, _unlayer_html(BANNER), {"src": {"url": BANNER}})

        with self.assertRaises(CommandError):
            self._run()

        flow.refresh_from_db()
        assert BANNER in flow.actions[0]["config"]["inputs"]["email"]["value"]["html"]
        assert self.requested == []

    def test_shared_workflow_templates_stay_on_unlayer(self) -> None:
        actions = [_email_action(_unlayer_html(BANNER), {"src": {"url": BANNER}})]
        own = HogFlowTemplate.objects.create(team=self.team, name="own", scope="team", actions=actions, edges=[])
        shared = HogFlowTemplate.objects.create(
            team=self.team, name="shared", scope="global", actions=actions, edges=[]
        )

        self._run()

        own.refresh_from_db()
        shared.refresh_from_db()
        assert BANNER not in json.dumps(own.actions)
        assert shared.actions == actions
