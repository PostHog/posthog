import hashlib
from typing import Any

from unittest.mock import patch

from parameterized import parameterized

from posthog.models.integration import Integration
from posthog.models.scoping import team_scope
from posthog.models.team import Team

from products.replay_vision.backend.models.replay_scanner import ScannerType
from products.replay_vision.backend.scout_source import SCOUT_SOURCE_PRODUCT
from products.replay_vision.backend.scout_templates import ScoutTemplateKey, render_template_body
from products.replay_vision.backend.tests.helpers import create_experiment
from products.replay_vision.backend.tests.test_api import _VisionAPITestCase
from products.replay_vision.backend.variant_analysis import (
    VARIANT_ANALYSIS_SCHEMA,
    VARIANT_ANALYSIS_TAG,
    pause_variant_analysis_scouts,
)
from products.signals.backend.facade.source_scouts import refresh_source_scout
from products.signals.backend.models import SignalScoutConfig
from products.signals.backend.scout_harness.model_selection import scout_model_pin_catalog
from products.signals.backend.scout_harness.tools.structured_output import validate_structured_output_schema
from products.skills.backend.api.skill_services import publish_skill_version
from products.skills.backend.models.skills import LLMSkill


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

    def test_a_variant_analysis_scout_gets_the_record_schema_and_is_the_one_paused(self) -> None:
        experiment = create_experiment(self.team, "checkout-flag", launched=True, variants=["control", "test"])
        scanner = self._create_scanner(
            name="experiment-scanner",
            scanner_type=ScannerType.EXPERIMENT,
            scanner_config={"prompt": "p", "experiment_id": experiment.id},
        )
        url = self._scouts_url(str(scanner.id))
        analysis = self.client.post(
            url, data=self._payload(name="signals-scout-variant-analysis", variant_analysis=True), format="json"
        )
        digest = self.client.post(url, data=self._payload(), format="json")
        assert analysis.status_code == 201, analysis.json()
        assert digest.status_code == 201, digest.json()

        with team_scope(self.team.id):
            config = SignalScoutConfig.objects.get(skill_name="signals-scout-variant-analysis")
        # The readout reads only records of this shape, and Signals refuses a schema it can't compile
        # when the scout first records.
        assert config.structured_output_schema == VARIANT_ANALYSIS_SCHEMA
        validate_structured_output_schema(config.structured_output_schema)
        assert VARIANT_ANALYSIS_TAG in config.tag_list

        # A retried create adopts the same scout, but a second one would split the readout's records.
        retry = self.client.post(
            url, data=self._payload(name="signals-scout-variant-analysis", variant_analysis=True), format="json"
        )
        assert retry.status_code == 200, retry.json()

        assert pause_variant_analysis_scouts(scanner) == 1
        with team_scope(self.team.id):
            enabled = dict(
                SignalScoutConfig.objects.filter(source_id=str(scanner.id)).values_list("skill_name", "enabled")
            )
        assert enabled == {"signals-scout-variant-analysis": False, "signals-scout-daily-digest": True}

        # Paused still counts: the way back is to turn it on, not to add another.
        second = self.client.post(
            url, data=self._payload(name="signals-scout-variant-analysis-2", variant_analysis=True), format="json"
        )
        assert second.status_code == 400, second.json()
        assert second.json()["attr"] == "variant_analysis"

    def test_variant_analysis_needs_an_experiment_scanner(self) -> None:
        response = self.client.post(
            self._scouts_url(str(self.scanner.id)), data=self._payload(variant_analysis=True), format="json"
        )
        assert response.status_code == 400, response.json()
        with team_scope(self.team.id):
            assert not SignalScoutConfig.objects.filter(source_id=str(self.scanner.id)).exists()

    def test_templates_are_rendered_for_the_scanner_in_the_url(self) -> None:
        response = self.client.get(f"{self._scouts_url(str(self.scanner.id))}templates/")
        assert response.status_code == 200, response.json()
        templates = response.json()
        assert [t["key"] for t in templates] == ["daily-digest", "root-cause", "trend-watch", "new-issues", "scratch"]
        assert all(f"`vision-scanners-get` with id `{self.scanner.id}`" in t["body"] for t in templates)

    def test_a_body_with_unfilled_placeholders_is_rejected(self) -> None:
        response = self.client.post(
            self._scouts_url(str(self.scanner.id)),
            data=self._payload(body="Report on <WHAT THIS SCOUT WATCHES FOR> every day."),
            format="json",
        )
        assert response.status_code == 400, response.json()
        assert response.json()["attr"] == "body"

    def test_a_scout_can_be_created_with_a_slack_destination(self) -> None:
        # The create modal offers a Slack channel, so the destination arrives on the create call
        # rather than a follow-up PATCH. Validating it needs the project and the request in the
        # body serializer's context.
        integration = Integration.objects.create(team=self.team, kind=Integration.IntegrationKind.SLACK)
        response = self.client.post(
            self._scouts_url(str(self.scanner.id)),
            data=self._payload(
                config={
                    "output_destinations": {
                        "slack": {"integration_id": integration.id, "channel": "CSCOUTS|#scout-findings"}
                    }
                },
            ),
            format="json",
        )

        assert response.status_code == 201, response.json()
        with team_scope(self.team.id):
            config = SignalScoutConfig.objects.get(skill_name="signals-scout-daily-digest")
        assert config.output_destinations == {
            "slack": {"integration_id": integration.id, "channel": "CSCOUTS|#scout-findings", "thread_reports": True}
        }

    def test_a_scout_can_be_created_with_a_model_pin(self) -> None:
        # The model gate reads the team from the serializer context, so a create without it rejected
        # every pin as unavailable even where the flag was on.
        model = scout_model_pin_catalog()[0]
        with patch("products.signals.backend.scout_harness.serializers.scout_model_config_enabled", return_value=True):
            response = self.client.post(
                self._scouts_url(str(self.scanner.id)),
                data=self._payload(config={"model": model}),
                format="json",
            )

        assert response.status_code == 201, response.json()
        with team_scope(self.team.id):
            config = SignalScoutConfig.objects.get(skill_name="signals-scout-daily-digest")
        assert config.model == model

    def test_a_slack_destination_on_another_project_is_rejected_as_bad_input(self) -> None:
        # A destination the project does not own is the caller's mistake, so it must come back as a
        # 400 the modal can show — not a 500.
        other_team = Team.objects.create(organization=self.organization, name="other project")
        integration = Integration.objects.create(team=other_team, kind=Integration.IntegrationKind.SLACK)
        response = self.client.post(
            self._scouts_url(str(self.scanner.id)),
            data=self._payload(
                config={"output_destinations": {"slack": {"integration_id": integration.id, "channel": "C1|#c"}}},
            ),
            format="json",
        )

        assert response.status_code == 400, response.json()
        with team_scope(self.team.id):
            assert not SignalScoutConfig.objects.filter(skill_name="signals-scout-daily-digest").exists()

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
            ("name_the_inbox_reserves", {"name": "scratchpad"}),
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

    def test_a_scout_with_only_a_display_name_gets_a_derived_name_and_keeps_its_label(self) -> None:
        payload = self._payload(display_name="Checkout digest")
        del payload["name"]
        response = self.client.post(self._scouts_url(str(self.scanner.id)), data=payload, format="json")
        assert response.status_code == 201, response.json()

        with team_scope(self.team.id):
            config = SignalScoutConfig.objects.get(skill_name=response.json()["config"]["skill_name"])
        assert config.display_name == "Checkout digest"
        assert config.skill_name.endswith("checkout-digest")
        assert config.source_id == str(self.scanner.id)

    def test_a_scout_with_neither_name_nor_display_name_is_rejected(self) -> None:
        payload = self._payload()
        del payload["name"]
        response = self.client.post(self._scouts_url(str(self.scanner.id)), data=payload, format="json")
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


class TestScoutTemplateSync(_VisionAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.scanner = self._create_scanner()
        self.url = f"/api/environments/{self.team.id}/vision/scanners/{self.scanner.id}/scouts/"

    def _skill(self, name: str) -> LLMSkill:
        return LLMSkill.objects.get(team=self.team, name=name, is_latest=True, deleted=False)

    def _create(self, name: str, body: str, template_key: str | None) -> None:
        payload: dict[str, str] = {"name": name, "description": "d", "body": body}
        if template_key:
            payload["template_key"] = template_key
        response = self.client.post(self.url, data=payload, format="json")
        assert response.status_code == 201, response.json()

    def _template_body(self, key: str) -> str:
        templates = self.client.get(f"{self.url}templates/")
        assert templates.status_code == 200, templates.json()
        return next(t["body"] for t in templates.json() if t["key"] == key)

    def _refresh(self, *names: str) -> None:
        # The entry point the scout runner calls before it loads a scout's skill.
        for name in names:
            refresh_source_scout(self.team.id, name)

    def test_template_edits_reach_untouched_scouts_before_they_run_and_never_edited_ones(self) -> None:
        digest = self._template_body("daily-digest")
        self._create("signals-scout-x-daily-digest", digest, "daily-digest")
        # Claiming stamps server-owned metadata, which must not turn a retried create into a conflict.
        retry = self.client.post(
            self.url,
            data={
                "name": "signals-scout-x-daily-digest",
                "description": "d",
                "body": digest,
                "template_key": "daily-digest",
            },
            format="json",
        )
        assert retry.status_code == 200, retry.json()
        self._create("signals-scout-y-daily-digest", digest + "\nOnly report checkout.", "daily-digest")
        # A scout made before claiming existed: its untouched text is claimed on its next run.
        self._create("signals-scout-z-daily-digest", digest, None)
        # The scratch skeleton is the author's to fill in, so it never follows the template.
        self._create("signals-scout-w-scratch", self._template_body("scratch"), "scratch")
        names = [
            "signals-scout-x-daily-digest",
            "signals-scout-y-daily-digest",
            "signals-scout-z-daily-digest",
            "signals-scout-w-scratch",
        ]

        self._refresh(*names)
        assert {name: self._skill(name).version for name in names} == dict.fromkeys(names, 1)

        def edited_template(*args: Any) -> str | None:
            body = render_template_body(*args)
            return None if body is None else body + "\nA new template step."

        with patch("products.replay_vision.backend.scout_template_sync.render_template_body", edited_template):
            self._refresh(*names)
            # Applied once: the next run finds every untouched scout already current.
            self._refresh(*names)

            for name in ("signals-scout-x-daily-digest", "signals-scout-z-daily-digest"):
                skill = self._skill(name)
                assert skill.body.endswith("A new template step.")
                assert skill.version == 2
            assert self._skill("signals-scout-y-daily-digest").body.endswith("Only report checkout.")
            assert self._skill("signals-scout-w-scratch").version == 1

            # Someone edits a synced scout; from then on the template no longer overwrites it.
            publish_skill_version(
                self.team,
                user=self.user,
                skill_name="signals-scout-x-daily-digest",
                body="My own instructions.",
                base_version=2,
            )
            self._refresh("signals-scout-x-daily-digest")
            assert self._skill("signals-scout-x-daily-digest").body == "My own instructions."

    def test_a_scout_made_from_an_older_template_gets_the_current_one_on_its_first_run(self) -> None:
        old_body = f"Read `vision-scanners-get` with id `{self.scanner.id}` and file a digest."
        normalized = old_body.replace(str(self.scanner.id), "{scanner_id}")
        self._create("signals-scout-a-daily-digest", old_body, None)
        history = {ScoutTemplateKey.DAILY_DIGEST: frozenset({hashlib.sha256(normalized.encode()).hexdigest()})}

        with patch("products.replay_vision.backend.scout_template_sync.LEGACY_TEMPLATE_BODY_HASHES", history):
            self._refresh("signals-scout-a-daily-digest")

        assert self._skill("signals-scout-a-daily-digest").body == self._template_body("daily-digest")
