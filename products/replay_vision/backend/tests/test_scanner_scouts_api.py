from unittest.mock import patch

from parameterized import parameterized

from posthog.models.scoping import team_scope

from products.replay_vision.backend.scout_source import SCOUT_SOURCE_PRODUCT
from products.replay_vision.backend.tests.test_api import _VisionAPITestCase
from products.signals.backend.models import SignalScoutConfig


class TestScannerScoutCreate(_VisionAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.scanner = self._create_scanner()

    def _scouts_url(self, scanner_id: str) -> str:
        return f"/api/environments/{self.team.id}/vision/scanners/{scanner_id}/scouts/"

    def _payload(self, **overrides: object) -> dict:
        return {
            "name": "signals-scout-daily-digest",
            "description": "Daily digest for this scanner.",
            "body": "Watch this scanner and file a digest.",
            **overrides,
        }

    def test_creates_a_scout_recorded_as_belonging_to_the_scanner_in_the_url(self) -> None:
        response = self.client.post(self._scouts_url(str(self.scanner.id)), data=self._payload(), format="json")
        assert response.status_code == 201, response.json()

        with team_scope(self.team.id):
            config = SignalScoutConfig.objects.get(skill_name="signals-scout-daily-digest")
        assert config.source_product == SCOUT_SOURCE_PRODUCT
        assert config.source_id == str(self.scanner.id)

    def test_a_source_supplied_in_the_body_cannot_claim_another_scanner(self) -> None:
        # The pair is the reports endpoint's ownership record, so it must come from the URL the
        # caller's access was checked against, never from input the caller controls.
        other = self._create_scanner(name="another-scanner")
        response = self.client.post(
            self._scouts_url(str(self.scanner.id)),
            data=self._payload(
                config={"source_product": SCOUT_SOURCE_PRODUCT, "source_id": str(other.id)},
            ),
            format="json",
        )
        assert response.status_code == 201, response.json()

        with team_scope(self.team.id):
            config = SignalScoutConfig.objects.get(skill_name="signals-scout-daily-digest")
        assert config.source_id == str(self.scanner.id)

    def test_the_public_scout_endpoint_cannot_record_a_source_at_all(self) -> None:
        # Signals cannot check access to a scanner, so its own create endpoint must not be able to
        # claim one: otherwise a skill editor without access to a scanner could bind a scout to it.
        response = self.client.post(
            f"/api/environments/{self.team.id}/signals/scout/",
            data={
                "name": "signals-scout-elsewhere",
                "description": "Made through the generic endpoint.",
                "body": "Watch something.",
                "config": {"source_product": SCOUT_SOURCE_PRODUCT, "source_id": str(self.scanner.id)},
            },
            format="json",
        )
        assert response.status_code in (200, 201), response.json()

        with team_scope(self.team.id):
            config = SignalScoutConfig.objects.get(skill_name="signals-scout-elsewhere")
        assert config.source_product is None
        assert config.source_id is None

    def test_scanner_editor_without_skill_authoring_cannot_create_a_scout(self) -> None:
        # A scout is an LLM skill carrying the report-channel agent tools, so editing a scanner is
        # not on its own enough to author one. Routing creation through Replay Vision must not let a
        # caller around the skill-authoring bar the Signals endpoint applies.
        with patch(
            "products.access_control.backend.facade.user_access_control.UserAccessControl.check_access_level_for_resource"
        ) as check_resource:
            check_resource.side_effect = lambda resource, *args, **kwargs: resource != "llm_skill"
            response = self.client.post(self._scouts_url(str(self.scanner.id)), data=self._payload(), format="json")

        assert response.status_code == 403, response.json()
        with team_scope(self.team.id):
            assert not SignalScoutConfig.objects.filter(skill_name="signals-scout-daily-digest").exists()

    @parameterized.expand(
        [
            ("oversized_body", {"body": "x" * 1_000_001}),
            ("name_without_the_scout_prefix", {"name": "not-a-scout"}),
        ]
    )
    def test_the_scanner_route_applies_the_same_definition_bars_as_the_generic_endpoint(
        self, _name: str, overrides: dict
    ) -> None:
        # A scout created here is the same LLM skill, so it cannot be a way around the name and
        # prompt-size limits the Signals endpoint enforces.
        response = self.client.post(
            self._scouts_url(str(self.scanner.id)), data=self._payload(**overrides), format="json"
        )
        assert response.status_code == 400, response.json()

    def test_a_scout_that_already_exists_without_an_owner_is_not_adopted(self) -> None:
        # Reusing a name tunes the existing config, and the reports route serves a scanner's reports
        # on the strength of the recorded owner — so adopting an unowned scout would surface every
        # report it filed before, to a caller who only has access to the scanner.
        self.client.post(
            f"/api/environments/{self.team.id}/signals/scout/",
            data=self._payload(),
            format="json",
        )

        response = self.client.post(self._scouts_url(str(self.scanner.id)), data=self._payload(), format="json")

        assert response.status_code == 409, response.json()
        with team_scope(self.team.id):
            config = SignalScoutConfig.objects.get(skill_name="signals-scout-daily-digest")
        assert config.source_id is None

    def test_a_child_scoped_api_key_cannot_create_a_scout_on_the_parent_team(self) -> None:
        # Scout rows canonicalize to the parent team on save, so a key scoped only to a child
        # environment clears the default scope check (URL team is the child) while the skill and
        # config it creates land on the parent.
        from posthog.models.personal_api_key import PersonalAPIKey
        from posthog.models.team import Team
        from posthog.models.utils import generate_random_token_personal, hash_key_value

        env = Team.objects.create(organization=self.organization, parent_team=self.team, name="env")
        scanner = self._create_scanner(name="child-scanner", team=env)
        raw = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="child-scoped",
            user=self.user,
            secure_value=hash_key_value(raw),
            scopes=["replay_scanner:write", "session_recording:read", "llm_skill:write", "signal_scout:write"],
            scoped_teams=[env.id],
        )
        self.client.logout()

        response = self.client.post(
            f"/api/projects/{env.id}/vision/scanners/{scanner.id}/scouts/",
            data=self._payload(),
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {raw}",
        )

        assert response.status_code == 403, response.content
        with team_scope(self.team.id):
            assert not SignalScoutConfig.objects.filter(skill_name="signals-scout-daily-digest").exists()
