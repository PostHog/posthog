from django.test import SimpleTestCase, TestCase

import dagster
from parameterized import parameterized

from posthog.models import Organization, OrganizationMembership, Team, User
from posthog.models.oauth import OAuthApplication
from posthog.models.oauth_provisioning import ProvisioningConfig
from posthog.models.organization_provisioning import OrganizationProvisioning
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.team.team_provisioning_config import TeamProvisioningConfig
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.growth.dags.provisioned_personal_api_keys import (
    TagProvisionedPersonalAPIKeysConfig,
    label_matches_provisioned_pattern,
    tag_provisioned_personal_api_keys,
)

TEAM_NAME = "Acme Analytics"
LONG_TEAM_NAME = "A very long project name that the mint truncates"


class TestLabelMatchesProvisionedPattern(SimpleTestCase):
    @parameterized.expand(
        [
            ("bare_team_name", TEAM_NAME, TEAM_NAME, True),
            ("prefixed", f"Stripe - {TEAM_NAME}", TEAM_NAME, True),
            ("prefix_containing_separator", f"Acme - Prod - {TEAM_NAME}", TEAM_NAME, True),
            ("truncated_bare", LONG_TEAM_NAME[:40], LONG_TEAM_NAME, True),
            ("truncated_prefixed", f"Partner - {LONG_TEAM_NAME}"[:40], LONG_TEAM_NAME, True),
            ("user_label", "My laptop", TEAM_NAME, False),
            ("team_name_with_suffix", f"{TEAM_NAME} - copy", TEAM_NAME, False),
            ("empty_prefix", f" - {TEAM_NAME}", TEAM_NAME, False),
            ("other_team", "Stripe - Other project", TEAM_NAME, False),
        ]
    )
    def test_label_matches(self, _name: str, label: str, team_name: str, expected: bool) -> None:
        assert label_matches_provisioned_pattern(label, team_name) is expected


class TestTagProvisionedPersonalAPIKeys(TestCase):
    def setUp(self) -> None:
        self.organization = Organization.objects.create(name="Acme")
        self.team = Team.objects.create(organization=self.organization, name=TEAM_NAME)
        self.member = User.objects.create_and_join(self.organization, "member@example.com", "password")
        self.outsider = User.objects.create(email="outsider@example.com")

        self.stripe_app = self._app("Stripe", issues_personal_api_key=False)
        self.other_partner = self._app("Other partner", issues_personal_api_key=True)
        self.non_minting_partner = self._app("Non-minting partner", issues_personal_api_key=False)
        OrganizationProvisioning.objects.create(
            organization=self.organization,
            partner=OrganizationProvisioning.Partner.STRIPE_PROJECTS,
            application=self.stripe_app,
        )
        TeamProvisioningConfig.objects.create(team=self.team, application=self.stripe_app)

        self.ambiguous_organization = Organization.objects.create(name="Shared")
        self.ambiguous_team = Team.objects.create(organization=self.ambiguous_organization, name=TEAM_NAME)
        OrganizationMembership.objects.create(organization=self.ambiguous_organization, user=self.member)
        TeamProvisioningConfig.objects.create(team=self.ambiguous_team, application=self.stripe_app)
        OrganizationProvisioning.objects.create(
            organization=self.ambiguous_organization,
            partner=OrganizationProvisioning.Partner.PROVISIONING_API,
            application=self.other_partner,
        )

        self.non_minting_organization = Organization.objects.create(name="Non-minting")
        self.non_minting_team = Team.objects.create(organization=self.non_minting_organization, name=TEAM_NAME)
        OrganizationMembership.objects.create(organization=self.non_minting_organization, user=self.member)
        TeamProvisioningConfig.objects.create(team=self.non_minting_team, application=self.non_minting_partner)

    def _app(self, name: str, *, issues_personal_api_key: bool) -> OAuthApplication:
        return OAuthApplication.objects.create(
            name=name,
            client_id=f"{name}-client",
            client_secret="",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://partner.example.com/callback",
            algorithm="RS256",
            is_provisioning_partner=True,
            _provisioning_config=ProvisioningConfig(issues_personal_api_key=issues_personal_api_key).model_dump(
                mode="json"
            ),
        )

    def _key(
        self, user: User, label: str, scoped_teams: list[int], scoped_organizations: list[str] | None = None
    ) -> PersonalAPIKey:
        if scoped_organizations is None:
            scoped_organizations = [
                str(organization_id)
                for organization_id in Team.objects.filter(id__in=scoped_teams[:1]).values_list(
                    "organization_id", flat=True
                )
            ]
        return PersonalAPIKey.objects.create(
            user=user,
            label=label,
            secure_value=hash_key_value(generate_random_token_personal()),
            scopes=["query:read"],
            scoped_teams=scoped_teams,
            scoped_organizations=scoped_organizations,
        )

    def _run(self, *, dry_run: bool, key_ids: list[str] | None = None) -> dict:
        context = dagster.build_op_context()
        tag_provisioned_personal_api_keys(
            context, TagProvisionedPersonalAPIKeysConfig(dry_run=dry_run, key_ids=key_ids or [])
        )

        metadata = context.get_output_metadata("result")
        assert metadata is not None
        return {key: value.value for key, value in metadata.items()}

    @parameterized.expand([("dry_run", True), ("real_run", False)])
    def test_tags_only_keys_matching_a_single_minting_partner(self, _name: str, dry_run: bool) -> None:
        prefixed = self._key(self.member, f"Stripe - {TEAM_NAME}", [self.team.id])
        bare = self._key(self.member, TEAM_NAME, [self.team.id])
        untouched = [
            self._key(self.member, "My laptop", [self.team.id]),
            self._key(self.member, TEAM_NAME, [self.team.id], scoped_organizations=[]),
            self._key(self.member, TEAM_NAME, [self.team.id, self.ambiguous_team.id]),
            self._key(self.outsider, TEAM_NAME, [self.team.id]),
            self._key(self.member, TEAM_NAME, [self.ambiguous_team.id]),
            self._key(self.member, TEAM_NAME, [self.non_minting_team.id]),
        ]

        metadata = self._run(dry_run=dry_run)

        assert metadata["tagged_total"] == 2
        assert metadata["ambiguous_total"] == 1
        assert metadata["tagged_per_app"] == {f"{self.stripe_app.name} ({self.stripe_app.id})": 2}
        expected_app_id = None if dry_run else self.stripe_app.id
        for key in (prefixed, bare):
            key.refresh_from_db()
            assert key.provisioned_by_id == expected_app_id
        assert not PersonalAPIKey.objects.filter(
            id__in=[key.id for key in untouched], provisioned_by__isnull=False
        ).exists()

    def test_tags_only_the_listed_keys_when_given_key_ids(self) -> None:
        listed = self._key(self.member, f"Stripe - {TEAM_NAME}", [self.team.id])
        unlisted = self._key(self.member, TEAM_NAME, [self.team.id])

        metadata = self._run(dry_run=False, key_ids=[listed.id])

        assert metadata["tagged_total"] == 1
        listed.refresh_from_db()
        unlisted.refresh_from_db()
        assert listed.provisioned_by_id == self.stripe_app.id
        assert unlisted.provisioned_by_id is None
