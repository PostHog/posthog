from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from posthog.models import Organization, Team
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.managed_migrations.backend.models.batch_imports import BatchImport, ContentType


class TestBatchImportSupportAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.user.is_staff = True
        self.user.save()

    def _create_pat(self, scopes: list[str]) -> str:
        token = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            user=self.user,
            label="test",
            secure_value=hash_key_value(token),
            scopes=scopes,
        )
        return token

    def _create_import(self, team: Team | None = None, **kwargs) -> BatchImport:
        defaults: dict = {"import_config": {}, "secrets": {}}
        defaults.update(kwargs)
        return BatchImport.objects.create(team=team or self.team, **defaults)

    @parameterized.expand(
        [
            # The triple gate: PAT auth needs the explicit hidden scope AND is_staff; the
            # public sibling scope and the `*` wildcard must not unlock the staff surface.
            ("staff_pat_with_scope", True, ["batch_import_support:read"], status.HTTP_200_OK),
            ("staff_pat_public_sibling_scope", True, ["batch_import:read"], status.HTTP_403_FORBIDDEN),
            ("staff_pat_wildcard", True, ["*"], status.HTTP_403_FORBIDDEN),
            ("non_staff_pat_with_scope", False, ["batch_import_support:read"], status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_pat_auth_matrix(self, _name, is_staff, scopes, expected_status):
        self.user.is_staff = is_staff
        self.user.save()
        token = self._create_pat(scopes=scopes)
        self.client.logout()

        response = self.client.get("/api/managed_migrations_support/", headers={"authorization": f"Bearer {token}"})
        self.assertEqual(response.status_code, expected_status, response.content)

    @parameterized.expand(
        [
            # Sessions bypass the scope layer; is_staff is the only gate for the browser.
            ("staff_session", True, status.HTTP_200_OK),
            ("non_staff_session", False, status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_session_auth_requires_staff(self, _name, is_staff, expected_status):
        self.user.is_staff = is_staff
        self.user.save()

        response = self.client.get("/api/managed_migrations_support/")
        self.assertEqual(response.status_code, expected_status, response.content)

    def test_staff_can_see_imports_on_teams_they_do_not_belong_to(self):
        # The whole point of this endpoint: support staff must reach jobs on customer teams
        # they aren't members of. Guards against someone reintroducing membership scoping
        # (an org filter or TeamAndOrgViewSetMixin) on the viewset.
        other_org = Organization.objects.create(name="Unrelated Org")
        other_team = Team.objects.create(organization=other_org, name="Cross Org Team")
        self.assertFalse(self.user.organization_memberships.filter(organization=other_org).exists())
        batch_import = self._create_import(team=other_team)

        list_response = self.client.get("/api/managed_migrations_support/")
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        returned = next(r for r in list_response.json()["results"] if r["id"] == str(batch_import.id))
        self.assertEqual(returned["team_id"], other_team.id)
        self.assertEqual(returned["team_name"], "Cross Org Team")

        detail_response = self.client.get(f"/api/managed_migrations_support/{batch_import.id}/")
        self.assertEqual(detail_response.status_code, status.HTTP_200_OK)

    def test_secret_values_never_appear_in_responses(self):
        batch_import = BatchImport(team=self.team)
        batch_import.config.json_lines(ContentType.CAPTURED).from_s3(
            bucket="customer-bucket",
            prefix="events/",
            region="us-east-1",
            access_key_id="AKIA_SUPER_SECRET_ID",
            secret_access_key="s3cr3t-access-key-value",
        ).to_capture(send_rate=1000)
        batch_import.save()

        for url in ["/api/managed_migrations_support/", f"/api/managed_migrations_support/{batch_import.id}/"]:
            response = self.client.get(url)
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            content = response.content.decode()
            self.assertNotIn("AKIA_SUPER_SECRET_ID", content)
            self.assertNotIn("s3cr3t-access-key-value", content)
            self.assertNotIn('"secrets"', content)
            # The non-secret config referencing secrets by key name IS expected on detail.
            self.assertNotIn('aws_secret_access_key": "s3cr3t', content)

    def test_derived_diagnostic_fields(self):
        now = datetime.now(UTC)
        batch_import = self._create_import(
            status=BatchImport.Status.RUNNING,
            lease_id="worker-lease",
            leased_until=now - timedelta(minutes=10),
            state={
                "parts": [
                    {"key": "day-1", "current_offset": 1000, "total_size": 1000},
                    {"key": "day-2", "current_offset": 50, "total_size": 200},
                    {"key": "day-3"},  # partially shaped worker dict must not 500
                ]
            },
            import_config={
                "source": {"type": "mixpanel", "start": "2025-01-01", "end": "2025-02-01"},
                "data_format": {"content": {"type": "mixpanel"}},
                "sink": {"type": "capture", "send_rate": 500},
            },
        )

        response = self.client.get(f"/api/managed_migrations_support/{batch_import.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertEqual(data["display_status"], "running")  # leased, so not waiting_to_start
        self.assertTrue(data["lease_expired"])
        self.assertEqual(
            data["parts_progress"],
            {
                "done": 1,
                "total": 3,
                "inflight_key": "day-2",
                "inflight_offset": 50,
                "inflight_total_size": 200,
            },
        )
        self.assertEqual(data["source_type"], "mixpanel")
        self.assertEqual(data["content_type"], "mixpanel")
        self.assertEqual(data["source_start_date"], "2025-01-01")
        self.assertEqual(data["source_end_date"], "2025-02-01")
        self.assertEqual(data["sink_type"], "capture")
        self.assertEqual(data["sink_send_rate"], 500)
        self.assertEqual(data["created_by_email"], None)
        self.assertEqual(data["state"], batch_import.state)
        self.assertEqual(data["import_config"], batch_import.import_config)

    def test_unclaimed_running_job_is_waiting_to_start_and_empty_config_does_not_500(self):
        batch_import = self._create_import(status=BatchImport.Status.RUNNING, lease_id=None, state=None)

        response = self.client.get(f"/api/managed_migrations_support/{batch_import.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertEqual(data["display_status"], "waiting_to_start")
        self.assertFalse(data["lease_expired"])
        self.assertEqual(data["parts_progress"]["total"], 0)
        self.assertEqual(data["source_type"], "unknown")
        self.assertIsNone(data["sink_type"])

    def test_list_filters(self):
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        paused = self._create_import(status=BatchImport.Status.PAUSED, status_message="Invalid JSON syntax")
        running_other_team = self._create_import(team=other_team)

        by_status = self.client.get("/api/managed_migrations_support/", {"status": "paused"})
        self.assertEqual([r["id"] for r in by_status.json()["results"]], [str(paused.id)])

        by_team = self.client.get("/api/managed_migrations_support/", {"team_id": other_team.id})
        self.assertEqual([r["id"] for r in by_team.json()["results"]], [str(running_other_team.id)])

        by_search = self.client.get("/api/managed_migrations_support/", {"search": "Invalid JSON"})
        self.assertEqual([r["id"] for r in by_search.json()["results"]], [str(paused.id)])
