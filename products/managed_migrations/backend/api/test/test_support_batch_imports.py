from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest

from django.test import SimpleTestCase

import structlog.testing
from parameterized import parameterized
from rest_framework import status

from posthog.models import Organization, Team
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.managed_migrations.backend.api.support_batch_imports import BatchImportSupportDetailSerializer
from products.managed_migrations.backend.models.batch_import_utils import (
    redact_part_key,
    redact_urls_in_json,
    redact_urls_in_text,
)
from products.managed_migrations.backend.models.batch_imports import BatchImport, ContentType


class TestRedactPartKey(SimpleTestCase):
    @parameterized.expand(
        [
            ("s3_object_key", "2024/01/events-0001.jsonl.gz", "2024/01/events-0001.jsonl.gz"),
            (
                "date_range_key",
                "2025-01-01T00:00:00Z-2025-01-02T00:00:00Z",
                "2025-01-01T00:00:00Z-2025-01-02T00:00:00Z",
            ),
            (
                "presigned_query_stripped",
                "https://bucket.s3.amazonaws.com/exports/day-1.jsonl?X-Amz-Signature=abc&X-Amz-Credential=AKIA",
                "https://bucket.s3.amazonaws.com/exports/day-1.jsonl",
            ),
            ("basic_auth_stripped", "https://user:pass@example.com/d.jsonl", "https://example.com/d.jsonl"),
            ("port_kept", "https://example.com:8443/d.jsonl?token=x", "https://example.com:8443/d.jsonl"),
            ("fragment_stripped", "https://example.com/d.jsonl#frag", "https://example.com/d.jsonl"),
            ("non_string_passthrough", None, None),
            (
                # No netloc means it isn't a remote URL that could carry usable
                # credentials - it must pass through untouched, not get mangled
                # (query stripped) by the redaction path.
                "scheme_without_netloc_passthrough",
                "file:///2024/01/events.jsonl?checksum=abc",
                "file:///2024/01/events.jsonl?checksum=abc",
            ),
            (
                "unparseable_url_fails_closed",
                "https://example.com:99999999999/d.jsonl?token=x",
                "[unparseable-url-redacted]",
            ),
        ]
    )
    def test_redact_part_key(self, _name, key, expected):
        self.assertEqual(redact_part_key(key), expected)

    @parameterized.expand(
        [
            ("none_passthrough", None, None),
            ("empty_passthrough", "", ""),
            ("no_url_unchanged", "Invalid JSON syntax at offset 42", "Invalid JSON syntax at offset 42"),
            (
                # The worker's parse-failure shape: key quoted inside the message.
                "worker_parse_message",
                "Parsing data in file 'https://u:p@example.com/d.jsonl?X-Amz-Signature=abc' failed: bad utf-8",
                "Parsing data in file 'https://example.com/d.jsonl' failed: bad utf-8",
            ),
            (
                "multiple_urls",
                "Failed https://a.com/x?t=1 then https://u:p@b.com/y",
                "Failed https://a.com/x then https://b.com/y",
            ),
            (
                "trailing_punctuation_stays_outside_url",
                "Failed https://u:p@a.com/x?t=1, then https://b.com/y?s=2.",
                "Failed https://a.com/x, then https://b.com/y.",
            ),
        ]
    )
    def test_redact_urls_in_text(self, _name, text, expected):
        self.assertEqual(redact_urls_in_text(text), expected)

    def test_redact_urls_in_json_walks_nested_structures(self):
        blob = {
            "source": {"type": "s3", "endpoint_url": "https://u:p@minio.example.com?token=x", "prefix": "a/b"},
            "parts": [{"key": "https://a.com/x?sig=1", "current_offset": 0}],
            "count": 3,
            "flag": None,
        }
        self.assertEqual(
            redact_urls_in_json(blob),
            {
                "source": {"type": "s3", "endpoint_url": "https://minio.example.com", "prefix": "a/b"},
                "parts": [{"key": "https://a.com/x", "current_offset": 0}],
                "count": 3,
                "flag": None,
            },
        )


class TestBatchImportSupportAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.user.is_staff = True
        self.user.save()

    def _create_pat(self, scopes: list[str], **kwargs) -> str:
        token = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            user=self.user,
            label="test",
            secure_value=hash_key_value(token),
            scopes=scopes,
            **kwargs,
        )
        return token

    def _create_import(self, team: Team | None = None, **kwargs) -> BatchImport:
        defaults: dict = {"import_config": {}, "secrets": {"placeholder": "true"}}
        defaults.update(kwargs)
        batch_import = BatchImport(team=team or self.team, **defaults)
        # BatchImport.__init__ resets `secrets` to {} whenever import_config is falsy
        # (BatchImportConfigBuilder initialize_empty), and EncryptedJSONStringField
        # serializes {} to NULL, violating the NOT NULL constraint - so re-apply after
        # init to keep the row insertable while still exercising an empty config.
        batch_import.secrets = defaults["secrets"]
        batch_import.save()
        return batch_import

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
            # Tenant-scoped keys must be rejected even with staff + the exact scope: this
            # root route has no routed team/org for APIScopePermission to anchor on, and
            # an org-scoped key would otherwise fail OPEN and bypass its organization
            # ceiling onto every customer's jobs (team-scoped keys already fail closed
            # centrally; pinned here so this route never regresses either way).
            ("org_scoped", "scoped_organizations"),
            ("team_scoped", "scoped_teams"),
        ]
    )
    def test_tenant_scoped_keys_are_rejected(self, _name, scoped_field):
        scoped_value = [str(self.organization.id)] if scoped_field == "scoped_organizations" else [self.team.pk]
        token = self._create_pat(scopes=["batch_import_support:read"], **{scoped_field: scoped_value})
        self.client.logout()

        response = self.client.get("/api/managed_migrations_support/", headers={"authorization": f"Bearer {token}"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.content)

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

    @parameterized.expand(
        [
            # The paginator rebuilds next/previous links from the full request URL, so a
            # query-string key would be reflected into the response body - reject it no
            # matter which authenticator would otherwise win: PAT auth via the query
            # string itself, and a logged-in session carrying a stray key (which never
            # reaches the PAT authenticator's own rejection).
            ("pat_auth_via_query_string", False),
            ("session_auth_with_stray_query_key", True),
        ]
    )
    def test_query_string_api_key_is_rejected(self, _name, use_session):
        token = self._create_pat(scopes=["batch_import_support:read"])
        if not use_session:
            self.client.logout()

        response = self.client.get(f"/api/managed_migrations_support/?personal_api_key={token}")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED, response.content)

    def test_audit_log_never_contains_credentials(self):
        # The audit log must allowlist query params so credential-bearing params
        # (e.g. `personal_api_key`, which the base auth class reads from the query
        # string) can never reach centralized logs. `search` is allowlisted but matches
        # the unredacted status_message column, so a search for a full status message
        # can quote a credential-bearing URL - it must be logged redacted.
        token = self._create_pat(scopes=["batch_import_support:read"])
        self.client.logout()

        with structlog.testing.capture_logs() as logs:
            response = self.client.get(
                "/api/managed_migrations_support/",
                {
                    "status": "paused",
                    "unexpected_param": "sensitive",
                    "search": "Parsing data in file 'https://u:p@a.com/x?sig=verysecret' failed",
                },
                headers={"authorization": f"Bearer {token}"},
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        audit_logs = [log for log in logs if log.get("event") == "batch_import_support_api_request"]
        self.assertEqual(len(audit_logs), 1)
        self.assertNotIn(token, str(audit_logs[0]))
        self.assertNotIn("verysecret", str(audit_logs[0]))
        self.assertEqual(
            audit_logs[0]["query_params"],
            {"status": "paused", "search": "Parsing data in file 'https://a.com/x' failed"},
        )

    def test_detail_read_writes_activity_log_entry(self):
        # Staff detail reads of another team's job must leave a durable, queryable
        # trail in that team's activity log - guards against the audit write being
        # dropped from `retrieve`.
        batch_import = self._create_import(
            import_config={"source": {"type": "mixpanel"}, "data_format": {"content": {"type": "mixpanel"}}}
        )

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.get(f"/api/managed_migrations_support/{batch_import.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        entry = ActivityLog.objects.get(scope="BatchImport", activity="support_viewed")
        self.assertEqual(entry.item_id, str(batch_import.id))
        self.assertEqual(entry.team_id, self.team.id)
        self.assertEqual(entry.organization_id, self.organization.id)
        self.assertEqual(entry.user_id, self.user.id)
        assert entry.detail is not None
        self.assertEqual(entry.detail["name"], "mixpanel (mixpanel)")

    def test_secret_values_never_appear_in_responses(self):
        # Structural guarantee first: neither serializer declares the field at all
        # (detail inherits list, so this covers both endpoints).
        self.assertNotIn("secrets", BatchImportSupportDetailSerializer().fields)

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

    def test_url_list_part_keys_are_redacted_in_responses(self):
        # url_list part keys are full source URLs; presigned tokens (query string) and
        # basic-auth credentials (userinfo) must never surface through the support API,
        # while the DB row must keep the raw URL - the worker resolves keys against it.
        secret_url = "https://user:secretpass@bucket.s3.amazonaws.com/exports/day-1.jsonl?X-Amz-Signature=topsecret"
        batch_import = self._create_import(
            status=BatchImport.Status.RUNNING,
            lease_id="worker-lease",
            state={"parts": [{"key": secret_url, "current_offset": 0, "total_size": None}]},
            import_config={
                "source": {
                    "type": "url_list",
                    "urls_key": "urls",
                    "endpoint_url": "https://cfguser:cfgsecret@minio.example.com?token=topsecret",
                }
            },
            status_message=f"Parsing data in file '{secret_url}' failed: invalid JSON",
            display_status_message=f"Part {secret_url} begins with gzip-compressed data",
        )

        list_response = self.client.get("/api/managed_migrations_support/")
        detail_response = self.client.get(f"/api/managed_migrations_support/{batch_import.id}/")

        redacted = "https://bucket.s3.amazonaws.com/exports/day-1.jsonl"
        row = next(r for r in list_response.json()["results"] if r["id"] == str(batch_import.id))
        self.assertEqual(row["parts_progress"]["inflight_key"], redacted)
        self.assertEqual(detail_response.json()["state"]["parts"][0]["key"], redacted)
        self.assertEqual(detail_response.json()["import_config"]["source"]["endpoint_url"], "https://minio.example.com")
        for content in (list_response.content, detail_response.content):
            self.assertNotIn(b"secretpass", content)
            self.assertNotIn(b"topsecret", content)
            self.assertNotIn(b"cfgsecret", content)
        batch_import.refresh_from_db()
        assert batch_import.state is not None
        self.assertEqual(batch_import.state["parts"][0]["key"], secret_url)

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
