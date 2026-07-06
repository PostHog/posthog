import os

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import ANY, Mock, patch

from django.db import connection
from django.test.utils import CaptureQueriesContext

from boto3 import resource
from botocore.config import Config
from parameterized import parameterized
from rest_framework import status

from posthog.models import User
from posthog.models.integration import Integration
from posthog.models.utils import uuid7
from posthog.settings import (
    OBJECT_STORAGE_ACCESS_KEY_ID,
    OBJECT_STORAGE_BUCKET,
    OBJECT_STORAGE_ENDPOINT,
    OBJECT_STORAGE_SECRET_ACCESS_KEY,
)

from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueAssignment,
    ErrorTrackingIssueFingerprintV2,
    ErrorTrackingRelease,
    ErrorTrackingStackFrame,
    ErrorTrackingSymbolSet,
)

from ee.models.rbac.role import Role

TEST_BUCKET = "test_storage_bucket-TestErrorTracking"


def get_path_to(fixture_file: str) -> str:
    file_dir = os.path.dirname(__file__)
    return os.path.join(file_dir, "fixtures", fixture_file)


class TestErrorTracking(APIBaseTest):
    def create_issue(self, fingerprints=None) -> ErrorTrackingIssue:
        issue = ErrorTrackingIssue.objects.create(team=self.team)
        fingerprints = fingerprints if fingerprints else []
        for fingerprint in fingerprints:
            ErrorTrackingIssueFingerprintV2.objects.create(team=self.team, issue=issue, fingerprint=fingerprint)
        return issue

    def test_external_reference_create_returns_provider_config_validation_error(self):
        issue = self.create_issue()
        integration = Integration.objects.create(
            team=self.team,
            kind=Integration.IntegrationKind.JIRA.value,
            config={"cloud_id": "cloud-id"},
            sensitive_config={"access_token": "access-token"},
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/external_references/",
            data={
                "issue": str(issue.id),
                "integration_id": integration.id,
                "config": {"title": "Checkout TypeError", "description": ""},
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["detail"] == "Missing required config fields for jira: project_key."

    def teardown_method(self, method) -> None:
        s3 = resource(
            "s3",
            endpoint_url=OBJECT_STORAGE_ENDPOINT,
            aws_access_key_id=OBJECT_STORAGE_ACCESS_KEY_ID,
            aws_secret_access_key=OBJECT_STORAGE_SECRET_ACCESS_KEY,
            config=Config(signature_version="s3v4"),
            region_name="us-east-1",
        )
        bucket = s3.Bucket(OBJECT_STORAGE_BUCKET)
        bucket.objects.filter(Prefix=TEST_BUCKET).delete()

    def test_issue_not_found_fingerprint_redirect(self):
        deleted_issue_id = uuid7()
        merged_fingerprint = "merged_fingerprint"

        merged_issue = self.create_issue()
        ErrorTrackingIssueFingerprintV2.objects.create(
            team=self.team, issue=merged_issue, fingerprint=merged_fingerprint
        )

        # no fingerprint
        response = self.client.get(
            f"/api/environments/{self.team.id}/error_tracking/issues/{deleted_issue_id}",
        )
        assert response.status_code == 404

        # with fingerprint hint
        response = self.client.get(
            f"/api/environments/{self.team.id}/error_tracking/issues/{deleted_issue_id}?fingerprint={merged_fingerprint}",
        )
        assert response.status_code == 308
        assert response.json() == {"issue_id": str(merged_issue.id)}

    def test_issue_fingerprint_does_not_redirect_when_not_merged(self):
        issue = self.create_issue(fingerprints=["fingerprint"])

        # with fingerprint hint
        response = self.client.get(
            f"/api/environments/{self.team.id}/error_tracking/issues/{issue.id}?fingerprint=fingerprint",
        )
        assert response.status_code == 200
        assert response.json().get("id") == str(issue.id)

    @freeze_time("2025-01-01")
    def test_issue_fetch(self):
        issue = self.create_issue(["fingerprint"])

        response = self.client.get(f"/api/environments/{self.team.id}/error_tracking/issues/{issue.id}")

        assert response.status_code == 200
        assert response.json() == {
            "id": str(issue.id),
            "name": None,
            "cohort": None,
            "description": None,
            "status": "active",
            "assignee": None,
            "first_seen": "2025-01-01T00:00:00Z",
            "external_issues": [],
        }

    @parameterized.expand(["user", "role"])
    def test_issue_fetch_assignee_id_preserves_type(self, assignee_type):
        # The frontend resolves the assignee by strict-comparing the numeric member id with
        # `assignee.id`; if retrieve serializes the user id as a string the issue renders as
        # "Unassigned" despite being assigned. User ids must stay integers, role ids strings.
        issue = self.create_issue(["fingerprint"])
        expected_id: int | str
        expected_python_type: type
        if assignee_type == "user":
            ErrorTrackingIssueAssignment.objects.create(issue=issue, user=self.user)
            expected_id, expected_python_type = self.user.id, int
        else:
            role = Role.objects.create(name="Eng role", organization=self.organization)
            ErrorTrackingIssueAssignment.objects.create(issue=issue, role=role)
            expected_id, expected_python_type = str(role.id), str

        response = self.client.get(f"/api/environments/{self.team.id}/error_tracking/issues/{issue.id}")

        assert response.status_code == 200
        assignee = response.json()["assignee"]
        assert assignee == {"id": expected_id, "type": assignee_type}
        assert isinstance(assignee["id"], expected_python_type)

    @freeze_time("2025-01-01")
    def test_issue_update(self):
        issue = self.create_issue(["fingerprint"])

        response = self.client.patch(
            f"/api/environments/{self.team.id}/error_tracking/issues/{issue.id}", data={"status": "resolved"}
        )
        issue.refresh_from_db()

        assert response.status_code == 200
        assert response.json() == {
            "id": str(issue.id),
            "name": None,
            "cohort": None,
            "description": None,
            "status": "resolved",
            "assignee": None,
            "first_seen": "2025-01-01T00:00:00Z",
            "external_issues": [],
        }
        assert issue.status == ErrorTrackingIssue.Status.RESOLVED

        self._assert_logs_the_activity(
            issue.id,
            [
                {
                    "activity": "updated",
                    "created_at": ANY,
                    "detail": {
                        "changes": [
                            {
                                "action": "changed",
                                "after": "resolved",
                                "before": "active",
                                "field": "status",
                                "type": "ErrorTrackingIssue",
                            }
                        ],
                        "name": issue.name,
                        "short_id": None,
                        "trigger": None,
                        "type": None,
                    },
                    "item_id": str(issue.id),
                    "scope": "ErrorTrackingIssue",
                    "user": {"email": "user1@posthog.com", "first_name": ""},
                }
            ],
        )

    def test_issue_update_rejects_deprecated_status(self):
        issue = self.create_issue(["fingerprint"])

        for deprecated_status in ("archived", "pending_release"):
            response = self.client.patch(
                f"/api/environments/{self.team.id}/error_tracking/issues/{issue.id}",
                data={"status": deprecated_status},
            )
            assert response.status_code == 400, response.json()
            body = response.json()
            assert body["type"] == "validation_error", body
            assert body["attr"] == "status", body
            assert deprecated_status in body["detail"], body

        issue.refresh_from_db()
        assert issue.status == ErrorTrackingIssue.Status.ACTIVE

    def test_issue_bulk_rejects_deprecated_status(self):
        issue = self.create_issue()

        for deprecated_status in ("archived", "pending_release"):
            response = self.client.post(
                f"/api/environments/{self.team.id}/error_tracking/issues/bulk",
                data={"ids": [issue.id], "action": "set_status", "status": deprecated_status},
            )
            assert response.status_code == 400, response.json()

        issue.refresh_from_db()
        assert issue.status == ErrorTrackingIssue.Status.ACTIVE

    def test_issue_update_serializes_legacy_status_for_reads(self):
        # Legacy rows that still hold archived/pending_release should still serialize OK on read,
        # so the cleanup is decoupled from the backfill.
        issue = self.create_issue()
        ErrorTrackingIssue.objects.filter(id=issue.id).update(status=ErrorTrackingIssue.Status.ARCHIVED)

        response = self.client.get(f"/api/environments/{self.team.id}/error_tracking/issues/{issue.id}")
        assert response.status_code == 200, response.json()
        assert response.json()["status"] == "archived"

    def test_issue_merge(self):
        issue_one = self.create_issue(fingerprints=["fingerprint_one"])
        issue_two = self.create_issue(fingerprints=["fingerprint_two"])

        assert ErrorTrackingIssue.objects.count() == 2

        repsonse = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/issues/{issue_one.id}/merge", data={"ids": [issue_two.id]}
        )

        assert repsonse.status_code == 200
        assert ErrorTrackingIssueFingerprintV2.objects.filter(issue_id=issue_one.id).count() == 2
        assert ErrorTrackingIssueFingerprintV2.objects.filter(fingerprint="fingerprint_one", version=0).exists()
        assert ErrorTrackingIssueFingerprintV2.objects.filter(fingerprint="fingerprint_two", version=1).exists()
        assert ErrorTrackingIssue.objects.count() == 1

    def test_issue_merge_returns_not_found_when_source_issue_is_stale(self):
        issue_one = self.create_issue(fingerprints=["fingerprint_one"])
        issue_two = self.create_issue(fingerprints=["fingerprint_two"])
        ErrorTrackingIssue.objects.filter(id=issue_two.id).delete()

        response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/issues/{issue_one.id}/merge",
            data={"ids": [issue_two.id]},
        )

        assert response.status_code == 404
        assert ErrorTrackingIssue.objects.filter(id=issue_one.id).exists()
        assert ErrorTrackingIssueFingerprintV2.objects.get(fingerprint="fingerprint_one").issue_id == issue_one.id

    def test_issue_merge_requires_ids(self):
        issue = self.create_issue(fingerprints=["fingerprint_one"])

        response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/issues/{issue.id}/merge",
            data={},
            format="json",
        )

        assert response.status_code == 400
        assert response.json() == {
            "type": "validation_error",
            "code": "required",
            "detail": "This field is required.",
            "attr": "ids",
        }

    def test_issue_split(self):
        issue = self.create_issue(fingerprints=["fingerprint_one", "fingerprint_two"])

        assert ErrorTrackingIssue.objects.count() == 1

        response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/issues/{issue.id}/split",
            data={"fingerprints": [{"fingerprint": "fingerprint_two", "name": "Split issue"}]},
            format="json",
        )

        assert response.status_code == 200
        assert response.json()["success"] is True
        assert len(response.json()["new_issue_ids"]) == 1
        assert ErrorTrackingIssueFingerprintV2.objects.filter(issue_id=issue.id).count() == 1
        assert ErrorTrackingIssueFingerprintV2.objects.filter(issue_id=issue.id, fingerprint="fingerprint_one").exists()
        assert ErrorTrackingIssue.objects.count() == 2

    def test_issue_split_requires_fingerprint_on_each_entry(self):
        issue = self.create_issue(fingerprints=["fingerprint_one"])

        response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/issues/{issue.id}/split",
            data={"fingerprints": [{"name": "Missing fingerprint"}]},
            format="json",
        )

        assert response.status_code == 400
        assert response.json()["type"] == "validation_error"
        assert response.json()["code"] == "required"

    def test_can_start_symbol_set_upload(self) -> None:
        chunk_id = uuid7()
        response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/symbol_sets/start_upload?chunk_id={chunk_id}"
        )
        response_json = response.json()

        assert response_json["presigned_url"] is not None

        symbol_set = ErrorTrackingSymbolSet.objects.get(id=response_json["symbol_set_id"])
        assert symbol_set.content_hash is None
        assert symbol_set.last_used is None

    def test_finish_upload_fails_if_file_not_found(self):
        symbol_set = ErrorTrackingSymbolSet.objects.create(
            team=self.team, ref=str(uuid7()), storage_ptr=f"symbolsets/{uuid7()}"
        )

        response = self.client.put(
            f"/api/environments/{self.team.id}/error_tracking/symbol_sets/{symbol_set.pk}/finish_upload",
            data={"content_hash": "this_is_a_content_hash"},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["code"] == "file_not_found"

    @patch("posthog.storage.object_storage._client")
    def test_finish_upload_fails_if_uploaded_file_is_too_large(self, patched_s3_client):
        patched_s3_client.head_object.return_value = {"ContentLength": 1073741824}  # 1GB
        symbol_set = ErrorTrackingSymbolSet.objects.create(
            team=self.team, ref=str(uuid7()), storage_ptr=f"symbolsets/{uuid7()}"
        )

        response = self.client.put(
            f"/api/environments/{self.team.id}/error_tracking/symbol_sets/{symbol_set.pk}/finish_upload",
            data={"content_hash": "this_is_a_content_hash"},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["code"] == "file_too_large"

    @patch("posthog.storage.object_storage._client")
    def test_finish_upload_updates_the_content_hash(self, patched_s3_client):
        patched_s3_client.head_object.return_value = {"ContentLength": 1048576}  # 1MB
        symbol_set = ErrorTrackingSymbolSet.objects.create(
            team=self.team, ref=str(uuid7()), storage_ptr=f"symbolsets/{uuid7()}"
        )

        response = self.client.put(
            f"/api/environments/{self.team.id}/error_tracking/symbol_sets/{symbol_set.pk}/finish_upload",
            data={"content_hash": "this_is_a_content_hash"},
        )

        symbol_set.refresh_from_db()

        assert response.status_code == status.HTTP_200_OK
        assert symbol_set.content_hash == "this_is_a_content_hash"
        assert symbol_set.last_used is None

    def test_can_bulk_delete_symbol_sets(self) -> None:
        ss1 = ErrorTrackingSymbolSet.objects.create(ref="source_1", team=self.team, storage_ptr=None)
        ss2 = ErrorTrackingSymbolSet.objects.create(ref="source_2", team=self.team, storage_ptr=None)
        ss3 = ErrorTrackingSymbolSet.objects.create(ref="source_3", team=self.team, storage_ptr=None)

        response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/symbol_sets/bulk_delete",
            data={"ids": [str(ss1.id), str(ss2.id)]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(response.json()["deleted"], 2)
        self.assertFalse(ErrorTrackingSymbolSet.objects.filter(id=ss1.id).exists())
        self.assertFalse(ErrorTrackingSymbolSet.objects.filter(id=ss2.id).exists())
        self.assertTrue(ErrorTrackingSymbolSet.objects.filter(id=ss3.id).exists())

    def test_bulk_delete_ignores_other_teams(self) -> None:
        other_team = self.create_team_with_organization(organization=self.organization)
        ss1 = ErrorTrackingSymbolSet.objects.create(ref="source_1", team=self.team, storage_ptr=None)
        other_ss = ErrorTrackingSymbolSet.objects.create(ref="source_2", team=other_team, storage_ptr=None)

        response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/symbol_sets/bulk_delete",
            data={"ids": [str(ss1.id), str(other_ss.id)]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(response.json()["deleted"], 1)
        self.assertTrue(ErrorTrackingSymbolSet.objects.filter(id=other_ss.id).exists())

    def test_bulk_delete_requires_ids(self) -> None:
        response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/symbol_sets/bulk_delete",
            data={},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_fetching_symbol_sets(self):
        other_team = self.create_team_with_organization(organization=self.organization)
        ErrorTrackingSymbolSet.objects.create(ref="source_1", team=self.team, storage_ptr=None)
        ErrorTrackingSymbolSet.objects.create(
            ref="source_2", team=self.team, storage_ptr="https://app-static-prod.posthog.com/static/chunk-BPTF6YBO.js"
        )
        ErrorTrackingSymbolSet.objects.create(
            ref="source_2", team=other_team, storage_ptr="https://app-static-prod.posthog.com/static/chunk-BPTF6YBO.js"
        )

        self.assertEqual(ErrorTrackingSymbolSet.objects.count(), 3)

        # it only fetches symbol sets for the specified team
        response = self.client.get(f"/api/environments/{self.team.id}/error_tracking/symbol_sets")
        self.assertEqual(len(response.json()["results"]), 2)

    def test_fetching_symbol_sets_filters_by_status_ref_and_order(self) -> None:
        ErrorTrackingSymbolSet.objects.create(ref="source_b", team=self.team, storage_ptr="symbolsets/source_b")
        ErrorTrackingSymbolSet.objects.create(
            ref="source_a", team=self.team, storage_ptr=None, failure_reason="Source map not found"
        )

        response = self.client.get(
            f"/api/environments/{self.team.id}/error_tracking/symbol_sets",
            data={"status": "valid", "order_by": "ref"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([symbol_set["ref"] for symbol_set in response.json()["results"]], ["source_b"])
        self.assertEqual([symbol_set["has_uploaded_file"] for symbol_set in response.json()["results"]], [True])
        self.assertNotIn("storage_ptr", response.json()["results"][0])
        self.assertNotIn("content_hash", response.json()["results"][0])

        response = self.client.get(
            f"/api/environments/{self.team.id}/error_tracking/symbol_sets",
            data={"ref": "source_a"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([symbol_set["ref"] for symbol_set in response.json()["results"]], ["source_a"])

    @parameterized.expand(
        [
            ("ref_substring", "chunk-abc123", ["frontend-chunk-abc123"]),
            ("release_version", "special", ["set_b"]),
            ("release_project", "checkout", ["set_c"]),
            ("release_commit_sha", "feedface", ["set_d"]),
            ("case_insensitive", "CHECKOUT", ["set_c"]),
            ("no_match", "zzznope", []),
        ]
    )
    def test_fetching_symbol_sets_search(self, _name: str, search: str, expected_refs: list[str]) -> None:
        release_b = ErrorTrackingRelease.objects.create(
            team=self.team, hash_id="hash_b", version="9.9.9-special", project="proj_b", metadata=None
        )
        release_c = ErrorTrackingRelease.objects.create(
            team=self.team, hash_id="hash_c", version="1.0.0", project="checkout-service", metadata=None
        )
        release_d = ErrorTrackingRelease.objects.create(
            team=self.team,
            hash_id="hash_d",
            version="2.0.0",
            project="proj_d",
            metadata={"git": {"commit_id": "feedface999abc"}},
        )
        ErrorTrackingSymbolSet.objects.create(ref="frontend-chunk-abc123", team=self.team, storage_ptr="symbolsets/a")
        ErrorTrackingSymbolSet.objects.create(
            ref="set_b", team=self.team, storage_ptr="symbolsets/b", release=release_b
        )
        ErrorTrackingSymbolSet.objects.create(
            ref="set_c", team=self.team, storage_ptr="symbolsets/c", release=release_c
        )
        ErrorTrackingSymbolSet.objects.create(
            ref="set_d", team=self.team, storage_ptr="symbolsets/d", release=release_d
        )

        response = self.client.get(
            f"/api/environments/{self.team.id}/error_tracking/symbol_sets",
            data={"search": search},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(sorted(symbol_set["ref"] for symbol_set in response.json()["results"]), sorted(expected_refs))

    def test_fetching_symbol_set_by_id(self) -> None:
        other_team = self.create_team_with_organization(organization=self.organization)
        symbol_set = ErrorTrackingSymbolSet.objects.create(ref="source_1", team=self.team, storage_ptr=None)
        other_symbol_set = ErrorTrackingSymbolSet.objects.create(ref="source_2", team=other_team, storage_ptr=None)

        response = self.client.get(f"/api/environments/{self.team.id}/error_tracking/symbol_sets/{symbol_set.id}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["id"], str(symbol_set.id))
        self.assertEqual(response.json()["ref"], "source_1")
        self.assertEqual(response.json()["has_uploaded_file"], False)
        self.assertNotIn("storage_ptr", response.json())
        self.assertNotIn("content_hash", response.json())

        response = self.client.get(f"/api/environments/{self.team.id}/error_tracking/symbol_sets/{other_symbol_set.id}")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_symbol_set_list_query_validation_does_not_apply_to_retrieve(self) -> None:
        symbol_set = ErrorTrackingSymbolSet.objects.create(
            ref="source_1", team=self.team, storage_ptr="symbolsets/source_1"
        )

        response = self.client.get(
            f"/api/environments/{self.team.id}/error_tracking/symbol_sets",
            data={"order_by": "storage_ptr"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        response = self.client.get(
            f"/api/environments/{self.team.id}/error_tracking/symbol_sets/{symbol_set.id}",
            data={"order_by": "storage_ptr"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_symbol_set_storage_ptr_is_read_only(self) -> None:
        symbol_set = ErrorTrackingSymbolSet.objects.create(
            ref="source_1", team=self.team, storage_ptr="symbolsets/source_1"
        )

        response = self.client.patch(
            f"/api/environments/{self.team.id}/error_tracking/symbol_sets/{symbol_set.id}",
            data={"storage_ptr": "symbolsets/other_team_file"},
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        symbol_set.refresh_from_db()
        self.assertEqual(symbol_set.storage_ptr, "symbolsets/source_1")

    @patch("products.error_tracking.backend.logic.symbol_sets.object_storage.get_presigned_url")
    def test_download_symbol_set(self, patched_get_presigned_url: Mock) -> None:
        patched_get_presigned_url.return_value = "https://example.com/source.map"
        symbol_set = ErrorTrackingSymbolSet.objects.create(
            ref="source_1", team=self.team, storage_ptr="symbolsets/source_1"
        )

        response = self.client.get(
            f"/api/environments/{self.team.id}/error_tracking/symbol_sets/{symbol_set.id}/download"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"url": "https://example.com/source.map"})
        patched_get_presigned_url.assert_called_once_with(file_key="symbolsets/source_1", expiration=3600)

    def test_download_symbol_set_without_file_returns_404(self) -> None:
        symbol_set = ErrorTrackingSymbolSet.objects.create(ref="source_1", team=self.team, storage_ptr=None)

        response = self.client.get(
            f"/api/environments/{self.team.id}/error_tracking/symbol_sets/{symbol_set.id}/download"
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.json(), {"detail": "Symbol set has no uploaded file."})

    def test_fetching_stack_frames(self):
        other_team = self.create_team_with_organization(organization=self.organization)
        symbol_set = ErrorTrackingSymbolSet.objects.create(ref="source_1", team=self.team, storage_ptr=None)
        other_symbol_set = ErrorTrackingSymbolSet.objects.create(ref="source_2", team=self.team, storage_ptr=None)
        ErrorTrackingStackFrame.objects.create(
            raw_id="raw_id", team=self.team, symbol_set=symbol_set, resolved=True, contents={}
        )
        ErrorTrackingStackFrame.objects.create(
            raw_id="other_raw_id", team=self.team, symbol_set=other_symbol_set, resolved=True, contents={}
        )
        ErrorTrackingStackFrame.objects.create(
            raw_id="raw_id", team=other_team, symbol_set=symbol_set, resolved=True, contents={}
        )

        self.assertEqual(ErrorTrackingStackFrame.objects.count(), 3)

        # it only fetches stack traces for the specified team
        response = self.client.post(f"/api/environments/{self.team.id}/error_tracking/stack_frames/batch_get")
        self.assertEqual(len(response.json()["results"]), 2)

        # fetching can be filtered by raw_ids
        data = {"raw_ids": ["raw_id"]}
        response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/stack_frames/batch_get", data=data
        )
        self.assertEqual(len(response.json()["results"]), 1)

        # fetching can be filtered by symbol set
        data = {"symbol_set": symbol_set.id}
        response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/stack_frames/batch_get", data=data
        )
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual(response.json()["results"][0]["symbol_set_ref"], symbol_set.ref)

        # a malformed raw_id (non-integer part) is handled gracefully, not a 500
        data = {"raw_ids": ["abc/not-an-int"]}
        response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/stack_frames/batch_get", data=data
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["results"], [])

    def test_assigning_issues(self):
        issue = self.create_issue()

        self.assertEqual(ErrorTrackingIssueAssignment.objects.count(), 0)
        self.client.patch(
            f"/api/environments/{self.team.id}/error_tracking/issues/{issue.id}/assign",
            data={"assignee": {"id": self.user.id, "type": "user"}},
        )
        # assigns the issue
        self.assertEqual(ErrorTrackingIssueAssignment.objects.count(), 1)
        self.assertEqual(ErrorTrackingIssueAssignment.objects.filter(issue=issue, user_id=self.user.id).count(), 1)

        self._assert_logs_the_activity(
            issue.id,
            [
                {
                    "activity": "assigned",
                    "created_at": ANY,
                    "detail": {
                        "changes": [
                            {
                                "action": "changed",
                                "after": {"id": self.user.id, "type": "user"},
                                "before": None,
                                "field": "assignee",
                                "type": "ErrorTrackingIssue",
                            }
                        ],
                        "name": issue.name,
                        "short_id": None,
                        "trigger": None,
                        "type": None,
                    },
                    "item_id": str(issue.id),
                    "scope": "ErrorTrackingIssue",
                    "user": {"email": "user1@posthog.com", "first_name": ""},
                }
            ],
        )

        self.client.patch(
            f"/api/environments/{self.team.id}/error_tracking/issues/{issue.id}/assign",
            data={"assignee": None},
        )
        # deletes the assignment
        self.assertEqual(ErrorTrackingIssueAssignment.objects.count(), 0)

        other_team = self.create_team_with_organization(organization=self.organization)
        response = self.client.patch(
            f"/api/environments/{other_team.id}/error_tracking/issues/{issue.id}/assign",
            data={"assignee": None},
        )
        # cannot assign issues from other teams
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @patch("products.error_tracking.backend.logic.issue_mutations.dispatch_issue_assigned_realtime")
    @patch("products.error_tracking.backend.logic.issue_mutations.send_error_tracking_issue_assigned")
    def test_assign_issue_dispatches_realtime_after_assignment(self, _send_email, mock_realtime):
        issue = self.create_issue()
        other_user = User.objects.create_and_join(self.organization, "other@test.com", "password")
        response = self.client.patch(
            f"/api/environments/{self.team.id}/error_tracking/issues/{issue.id}/assign",
            data={"assignee": {"id": other_user.id, "type": "user"}},
        )
        assert response.status_code in (200, 202), response.json()
        mock_realtime.assert_called_once()

    def test_error_tracking_issue_bulk_resolve(self):
        issue_one = self.create_issue()
        issue_two = self.create_issue()

        self.assertEqual(issue_one.status, ErrorTrackingIssue.Status.ACTIVE)
        self.assertEqual(issue_two.status, ErrorTrackingIssue.Status.ACTIVE)

        self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/issues/bulk",
            data={"ids": [issue_one.id, issue_two.id], "action": "set_status", "status": "resolved"},
        )

        issue_one.refresh_from_db()
        issue_two.refresh_from_db()

        self.assertEqual(issue_one.status, ErrorTrackingIssue.Status.RESOLVED)
        self.assertEqual(issue_two.status, ErrorTrackingIssue.Status.RESOLVED)

    def test_error_tracking_issue_bulk_assign(self):
        issue_one = self.create_issue()
        issue_two = self.create_issue()

        ErrorTrackingIssueAssignment.objects.create(issue=issue_one, user=self.user)
        role = Role.objects.create(name="Team role", organization=self.organization)
        role.members.set([self.user])

        self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/issues/bulk",
            data={
                "ids": [issue_one.id, issue_two.id],
                "action": "assign",
                "assignee": {"id": role.id, "type": "role"},
            },
        )

        self.assertEqual(len(ErrorTrackingIssueAssignment.objects.filter(issue=issue_one, user=self.user)), 0)
        self.assertEqual(
            len(ErrorTrackingIssueAssignment.objects.filter(issue__in=[issue_one, issue_two], role=role)), 2
        )

    def test_can_start_bulk_symbol_set_upload(self) -> None:
        chunk_id_one = uuid7()
        chunk_id_two = uuid7()
        response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/symbol_sets/bulk_start_upload",
            data={"chunk_ids": [chunk_id_one, chunk_id_two]},
        )
        response_json = response.json()
        id_map = response_json["id_map"]

        assert len(id_map.keys()) == 2

        symbol_set = ErrorTrackingSymbolSet.objects.get(ref=chunk_id_one)
        symbol_set_upload_response = id_map[str(chunk_id_one)]

        assert str(symbol_set.id) == symbol_set_upload_response["symbol_set_id"]
        assert symbol_set_upload_response["presigned_url"]["fields"]["key"] == symbol_set.storage_ptr
        assert symbol_set.last_used is None

    def test_bulk_start_upload_skips_uploaded_symbol_sets(self) -> None:
        release = ErrorTrackingRelease.objects.create(
            team=self.team,
            hash_id="test-release",
            version="1.0.0",
            project="test",
        )
        existing_chunk_id = str(uuid7())
        existing_symbol_set = ErrorTrackingSymbolSet.objects.create(
            team=self.team,
            ref=existing_chunk_id,
            storage_ptr="existing",
            content_hash="already_uploaded",
            release=release,
        )

        new_chunk_id = str(uuid7())

        response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/symbol_sets/bulk_start_upload",
            data={
                "symbol_sets": [
                    {
                        "chunk_id": existing_chunk_id,
                        "release_id": str(release.id),
                        "content_hash": existing_symbol_set.content_hash,
                    },
                    {
                        "chunk_id": new_chunk_id,
                        "release_id": str(release.id),
                        "content_hash": "new_hash",
                    },
                ]
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        id_map = response.json()["id_map"]

        assert str(new_chunk_id) in id_map
        assert existing_chunk_id not in id_map

        existing_symbol_set.refresh_from_db()
        assert existing_symbol_set.storage_ptr == "existing"
        assert existing_symbol_set.release_id == release.id

        new_symbol_set = ErrorTrackingSymbolSet.objects.get(ref=new_chunk_id)
        assert new_symbol_set.release_id == release.id
        assert new_symbol_set.last_used is None
        assert id_map[str(new_chunk_id)]["symbol_set_id"] == str(new_symbol_set.id)

    @parameterized.expand(
        [
            ("default_rejects", {}, status.HTTP_400_BAD_REQUEST, "content_hash_mismatch", "unchanged"),
            ("skip_on_conflict", {"skip_on_conflict": True}, status.HTTP_201_CREATED, None, "unchanged"),
            ("force", {"force": True}, status.HTTP_201_CREATED, None, "overwritten"),
            (
                "force_and_skip_rejected",
                {"force": True, "skip_on_conflict": True},
                status.HTTP_400_BAD_REQUEST,
                "invalid_conflict_handling",
                "unchanged",
            ),
        ]
    )
    def test_bulk_start_upload_handles_content_mismatch(
        self,
        _name: str,
        request_flags: dict[str, bool],
        expected_status: int,
        expected_code: str | None,
        expected_outcome: str,
    ) -> None:
        chunk_id = str(uuid7())
        symbol_set = ErrorTrackingSymbolSet.objects.create(
            team=self.team,
            ref=chunk_id,
            storage_ptr="existing",
            content_hash="already_uploaded",
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/symbol_sets/bulk_start_upload",
            data={
                "symbol_sets": [
                    {
                        "chunk_id": chunk_id,
                        "content_hash": "different_hash",
                    }
                ],
                **request_flags,
            },
            format="json",
        )

        assert response.status_code == expected_status
        if expected_code:
            assert response.json()["code"] == expected_code
        if expected_outcome == "overwritten":
            assert response.json()["id_map"][chunk_id]["symbol_set_id"] == str(symbol_set.id)

        symbol_set.refresh_from_db()
        if expected_outcome == "unchanged":
            assert symbol_set.storage_ptr == "existing"
            assert symbol_set.content_hash == "already_uploaded"
        else:
            assert symbol_set.storage_ptr != "existing"
            assert symbol_set.content_hash is None

    def test_bulk_start_upload_fail_restart_with_no_content_hash(self) -> None:
        existing_chunk_id = str(uuid7())
        _ = ErrorTrackingSymbolSet.objects.create(
            team=self.team,
            ref=existing_chunk_id,
            storage_ptr="existing",
            content_hash="already_uploaded",
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/symbol_sets/bulk_start_upload",
            data={"chunk_ids": [existing_chunk_id]},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_bulk_start_upload_rejects_unknown_release(self) -> None:
        chunk_id = str(uuid7())
        missing_release_id = str(uuid7())

        response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/symbol_sets/bulk_start_upload",
            data={
                "symbol_sets": [
                    {
                        "chunk_id": chunk_id,
                        "release_id": missing_release_id,
                        "content_hash": "hash",
                    }
                ]
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not ErrorTrackingSymbolSet.objects.filter(ref=chunk_id).exists()

    def test_bulk_start_upload_allows_no_release(self) -> None:
        response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/symbol_sets/bulk_start_upload",
            data={
                "symbol_sets": [
                    {
                        "chunk_id": str(uuid7()),
                        "release_id": None,
                        "content_hash": "hash",
                    },
                    {
                        "chunk_id": str(uuid7()),
                        "content_hash": "hash",
                    },
                    {
                        "chunk_id": str(uuid7()),
                        "content_hash": None,
                    },
                    {
                        "chunk_id": str(uuid7()),
                    },
                ]
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED

    def test_bulk_start_upload_updates_release_for_pending_symbol_set(self) -> None:
        chunk_id = str(uuid7())

        initial_response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/symbol_sets/bulk_start_upload",
            data={"chunk_ids": [chunk_id]},
            format="json",
        )

        assert initial_response.status_code == status.HTTP_201_CREATED

        symbol_set = ErrorTrackingSymbolSet.objects.get(ref=chunk_id)
        initial_storage_ptr = symbol_set.storage_ptr

        release = ErrorTrackingRelease.objects.create(
            team=self.team,
            hash_id="later-release",
            version="1.0.1",
            project="test",
        )

        updated_response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/symbol_sets/bulk_start_upload",
            data={
                "symbol_sets": [
                    {
                        "chunk_id": str(chunk_id),
                        "release_id": str(release.id),
                        "content_hash": "pending_hash",
                    }
                ]
            },
            format="json",
        )

        assert updated_response.status_code == status.HTTP_201_CREATED
        id_map = updated_response.json()["id_map"]

        symbol_set.refresh_from_db()
        assert symbol_set.release_id == release.id
        assert symbol_set.storage_ptr != initial_storage_ptr
        assert id_map[str(chunk_id)]["symbol_set_id"] == str(symbol_set.id)

    def test_bulk_start_upload_updates_release_for_uploaded_symbol_set(self) -> None:
        chunk_id = str(uuid7())
        storage_ptr = "uploaded_ptr"
        content_hash = "uploaded_hash"

        symbol_set = ErrorTrackingSymbolSet.objects.create(
            team=self.team,
            ref=chunk_id,
            storage_ptr=storage_ptr,
            content_hash=content_hash,
        )

        release = ErrorTrackingRelease.objects.create(
            team=self.team,
            hash_id="retro-release",
            version="1.0.2",
            project="test",
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/symbol_sets/bulk_start_upload",
            data={
                "symbol_sets": [
                    {
                        "chunk_id": chunk_id,
                        "release_id": str(release.id),
                        "content_hash": content_hash,
                    }
                ]
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        id_map = response.json()["id_map"]

        symbol_set.refresh_from_db()
        assert symbol_set.release_id == release.id
        assert symbol_set.storage_ptr == storage_ptr
        assert chunk_id not in id_map

    def test_bulk_start_upload_restarts_pending_upload(self) -> None:
        chunk_id = str(uuid7())

        first_response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/symbol_sets/bulk_start_upload",
            data={"chunk_ids": [chunk_id]},
            format="json",
        )

        assert first_response.status_code == status.HTTP_201_CREATED

        symbol_set = ErrorTrackingSymbolSet.objects.get(ref=chunk_id)
        initial_storage_ptr = symbol_set.storage_ptr

        second_response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/symbol_sets/bulk_start_upload",
            data={"chunk_ids": [chunk_id]},
            format="json",
        )

        assert second_response.status_code == status.HTTP_201_CREATED
        id_map = second_response.json()["id_map"]

        symbol_set.refresh_from_db()
        assert symbol_set.storage_ptr != initial_storage_ptr
        assert id_map[str(chunk_id)]["symbol_set_id"] == str(symbol_set.id)

    @parameterized.expand(
        [
            ("identical_content_skips", "hash", {}, status.HTTP_201_CREATED, None),
            ("changed_content_rejects", "different_hash", {}, status.HTTP_400_BAD_REQUEST, "release_id_mismatch"),
            (
                "changed_content_skip_release_flag",
                "different_hash",
                {"skip_release_on_conflict": True, "skip_on_conflict": True},
                status.HTTP_201_CREATED,
                None,
            ),
        ]
    )
    def test_bulk_start_upload_handles_release_change(
        self,
        _name: str,
        upload_content_hash: str,
        request_flags: dict[str, bool],
        expected_status: int,
        expected_code: str | None,
    ) -> None:
        chunk_id = str(uuid7())

        first_release = ErrorTrackingRelease.objects.create(
            team=self.team,
            hash_id="first-release",
            version="1.0.0",
            project="test",
        )
        second_release = ErrorTrackingRelease.objects.create(
            team=self.team,
            hash_id="second-release",
            version="1.0.1",
            project="test",
        )

        symbol_set = ErrorTrackingSymbolSet.objects.create(
            team=self.team,
            ref=chunk_id,
            storage_ptr="stored",
            content_hash="hash",
            release=first_release,
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/symbol_sets/bulk_start_upload",
            data={
                "symbol_sets": [
                    {
                        "chunk_id": chunk_id,
                        "release_id": str(second_release.id),
                        "content_hash": upload_content_hash,
                    }
                ],
                **request_flags,
            },
            format="json",
        )

        assert response.status_code == expected_status
        if expected_code:
            assert response.json()["code"] == expected_code
        else:
            # The conflicting chunk is skipped, not re-uploaded or re-associated
            assert chunk_id not in response.json()["id_map"]

        symbol_set.refresh_from_db()
        assert symbol_set.release_id == first_release.id
        assert symbol_set.content_hash == "hash"
        assert symbol_set.storage_ptr == "stored"

    def test_bulk_start_upload_release_conflict_does_not_poison_batch(self) -> None:
        conflicting_chunk_id = str(uuid7())
        new_chunk_id = str(uuid7())

        first_release = ErrorTrackingRelease.objects.create(
            team=self.team,
            hash_id="first-release",
            version="1.0.0",
            project="test",
        )
        second_release = ErrorTrackingRelease.objects.create(
            team=self.team,
            hash_id="second-release",
            version="1.0.1",
            project="test",
        )

        ErrorTrackingSymbolSet.objects.create(
            team=self.team,
            ref=conflicting_chunk_id,
            storage_ptr="stored",
            content_hash="hash",
            release=first_release,
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/symbol_sets/bulk_start_upload",
            data={
                "symbol_sets": [
                    {
                        "chunk_id": conflicting_chunk_id,
                        "release_id": str(second_release.id),
                        "content_hash": "different_hash",
                    },
                    {
                        "chunk_id": new_chunk_id,
                        "release_id": str(second_release.id),
                        "content_hash": "new_hash",
                    },
                ],
                "skip_release_on_conflict": True,
                "skip_on_conflict": True,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        id_map = response.json()["id_map"]
        assert conflicting_chunk_id not in id_map
        assert new_chunk_id in id_map

        conflicting = ErrorTrackingSymbolSet.objects.get(ref=conflicting_chunk_id)
        assert conflicting.release_id == first_release.id

        created = ErrorTrackingSymbolSet.objects.get(ref=new_chunk_id)
        assert created.release_id == second_release.id

    @patch("posthog.storage.object_storage.head_object")
    def test_can_finish_bulk_symbol_set_upload(self, patched_object_storage) -> None:
        symbol_set_one = ErrorTrackingSymbolSet.objects.create(
            team=self.team, ref=str(uuid7()), storage_ptr="file/name1"
        )
        symbol_set_two = ErrorTrackingSymbolSet.objects.create(
            team=self.team, ref=str(uuid7()), storage_ptr="file/name2"
        )

        patched_object_storage.return_value = {"ContentLength": 1000}  # 1KB

        self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/symbol_sets/bulk_finish_upload",
            data={"content_hashes": {str(symbol_set_one.id): "hash_one", str(symbol_set_two.id): "hash_two"}},
        )

        assert ErrorTrackingSymbolSet.objects.get(id=symbol_set_one.id).content_hash == "hash_one"
        assert ErrorTrackingSymbolSet.objects.get(id=symbol_set_two.id).content_hash == "hash_two"

    @patch("products.error_tracking.backend.logic.symbol_sets.posthoganalytics.capture")
    def test_bulk_finish_upload_rejects_unknown_symbol_set_ids(self, patched_capture: Mock) -> None:
        response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/symbol_sets/bulk_finish_upload",
            data={"content_hashes": {str(uuid7()): "hash"}},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["code"] == "symbol_set_not_found"
        assert patched_capture.call_args.args[0] == "error_tracking_symbol_set_uploaded"
        assert patched_capture.call_args.kwargs["properties"] == {
            "file_size": 0,
            "success": False,
            "file_count": 1,
            "failure_reason": "ValidationError",
            "failure_code": "symbol_set_not_found",
        }

    @patch("products.error_tracking.backend.logic.symbol_sets.posthoganalytics.capture")
    @patch("posthog.storage.object_storage.head_object")
    def test_bulk_finish_upload_preserves_pending_symbol_set_when_file_is_not_found(
        self, patched_object_storage, patched_capture: Mock
    ) -> None:
        symbol_set = ErrorTrackingSymbolSet.objects.create(team=self.team, ref=str(uuid7()), storage_ptr="file/name")
        request_data = {"content_hashes": {str(symbol_set.id): "hash"}}

        patched_object_storage.side_effect = [None, {"ContentLength": 1000}]

        response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/symbol_sets/bulk_finish_upload",
            data=request_data,
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["code"] == "file_not_found"
        failure_call = patched_capture.call_args_list[0]
        assert failure_call.args[0] == "error_tracking_symbol_set_uploaded"
        assert failure_call.kwargs["properties"] == {
            "file_size": 0,
            "success": False,
            "file_count": 1,
            "failure_reason": "ValidationError",
            "failure_code": "file_not_found",
        }

        symbol_set.refresh_from_db()
        assert symbol_set.content_hash is None

        retry_response = self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/symbol_sets/bulk_finish_upload",
            data=request_data,
            format="json",
        )

        assert retry_response.status_code == status.HTTP_201_CREATED
        symbol_set.refresh_from_db()
        assert symbol_set.content_hash == "hash"

    def _assert_logs_the_activity(self, error_tracking_issue_id: int, expected: list[dict]) -> None:
        activity_response = self._get_error_tracking_issue_activity(error_tracking_issue_id)
        activity: list[dict] = activity_response["results"]
        for item in activity:
            item.pop("id", None)
        self.maxDiff = None
        self.assertEqual(activity, expected)

    def _get_error_tracking_issue_activity(
        self, error_tracking_issue_id: int, expected_status: int = status.HTTP_200_OK
    ) -> dict:
        url = f"/api/environments/{self.team.id}/error_tracking/issues/{error_tracking_issue_id}/activity"
        activity = self.client.get(url)
        self.assertEqual(activity.status_code, expected_status)
        return activity.json()

    def test_fetch_release_by_hash_id(self) -> None:
        release = ErrorTrackingRelease.objects.create(
            team=self.team,
            hash_id="test-hash-123",
            version="1.0.0",
            project="my-project",
            metadata={"commit": "abc123"},
        )

        response = self.client.get(f"/api/environments/{self.team.id}/error_tracking/releases/hash/{release.hash_id}")
        assert response.status_code == status.HTTP_200_OK

        response_json = response.json()
        assert response_json["id"] == str(release.id)
        assert response_json["hash_id"] == "test-hash-123"
        assert response_json["version"] == "1.0.0"
        assert response_json["project"] == "my-project"
        assert response_json["metadata"] == {"commit": "abc123"}

    def test_fetch_release_by_hash_id_not_found(self) -> None:
        response = self.client.get(f"/api/environments/{self.team.id}/error_tracking/releases/hash/nonexistent-hash")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_releases_list_paginates_in_sql(self) -> None:
        for i in range(5):
            ErrorTrackingRelease.objects.create(team=self.team, hash_id=f"hash-{i}", version=f"1.0.{i}", project="proj")

        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(
                f"/api/environments/{self.team.id}/error_tracking/releases", data={"limit": 2, "offset": 1}
            )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["count"] == 5
        assert len(body["results"]) == 2

        # The page is sliced in SQL (LIMIT 2), not by materializing all rows and slicing in Python.
        table = ErrorTrackingRelease._meta.db_table
        limited_selects = [
            q["sql"] for q in ctx.captured_queries if table in q["sql"] and "LIMIT 2" in q["sql"].upper()
        ]
        assert limited_selects, "expected a LIMIT 2 SELECT on the release table"


class TestIssueStateSync(ClickhouseTestMixin, APIBaseTest):
    def _create_issue(self, fingerprints=None, **kwargs) -> ErrorTrackingIssue:
        issue = ErrorTrackingIssue.objects.create(team=self.team, **kwargs)
        for fp in fingerprints or []:
            ErrorTrackingIssueFingerprintV2.objects.create(team=self.team, issue=issue, fingerprint=fp)
        return issue

    def _get_issue_state_rows(self, team_id=None):
        from posthog.clickhouse.client import sync_execute

        return sync_execute(
            """
            SELECT fingerprint, issue_id, issue_name, issue_status, assigned_user_id, assigned_role_id
            FROM error_tracking_fingerprint_issue_state FINAL
            WHERE team_id = %(team_id)s AND is_deleted = 0
            ORDER BY fingerprint
            """,
            {"team_id": team_id or self.team.pk},
        )

    def setUp(self):
        super().setUp()
        from posthog.clickhouse.client import sync_execute

        from products.error_tracking.backend.sql import TRUNCATE_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_TABLE_SQL

        sync_execute(TRUNCATE_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_TABLE_SQL())

    def test_name_change_syncs(self):
        issue = self._create_issue(fingerprints=["fp_1"], name="Original")

        self.client.patch(
            f"/api/environments/{self.team.id}/error_tracking/issues/{issue.id}",
            data={"name": "Updated"},
        )

        rows = self._get_issue_state_rows()
        assert len(rows) == 1
        assert rows[0][0] == "fp_1"
        assert rows[0][2] == "Updated"

    def test_assign_user_syncs(self):
        issue = self._create_issue(fingerprints=["fp_1"])

        self.client.patch(
            f"/api/environments/{self.team.id}/error_tracking/issues/{issue.id}/assign",
            data={"assignee": {"id": self.user.id, "type": "user"}},
        )

        rows = self._get_issue_state_rows()
        assert len(rows) == 1
        assert rows[0][4] == self.user.id  # assigned_user_id

    def test_clear_assignment_syncs(self):
        issue = self._create_issue(fingerprints=["fp_1"])

        self.client.patch(
            f"/api/environments/{self.team.id}/error_tracking/issues/{issue.id}/assign",
            data={"assignee": {"id": self.user.id, "type": "user"}},
        )

        rows = self._get_issue_state_rows()
        assert rows[0][4] == self.user.id  # assigned_user_id

        self.client.patch(
            f"/api/environments/{self.team.id}/error_tracking/issues/{issue.id}/assign",
            data={},
        )

        rows = self._get_issue_state_rows()
        assert len(rows) == 1
        assert rows[0][4] is None  # assigned_user_id cleared
        assert rows[0][5] is None  # assigned_role_id cleared

    def test_assign_role_syncs(self):
        issue = self._create_issue(fingerprints=["fp_1"])
        role = Role.objects.create(name="Eng role", organization=self.organization)

        self.client.patch(
            f"/api/environments/{self.team.id}/error_tracking/issues/{issue.id}/assign",
            data={"assignee": {"id": str(role.id), "type": "role"}},
        )

        rows = self._get_issue_state_rows()
        assert len(rows) == 1
        assert str(rows[0][5]) == str(role.id)  # assigned_role_id

    def test_status_change_syncs(self):
        issue = self._create_issue(fingerprints=["fp_1"])

        self.client.patch(
            f"/api/environments/{self.team.id}/error_tracking/issues/{issue.id}",
            data={"status": "resolved"},
        )

        rows = self._get_issue_state_rows()
        assert len(rows) == 1
        assert rows[0][3] == "resolved"  # issue_status

    def test_bulk_status_change_syncs(self):
        issue_one = self._create_issue(fingerprints=["fp_one"])
        issue_two = self._create_issue(fingerprints=["fp_two"])

        self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/issues/bulk",
            data={"ids": [str(issue_one.id), str(issue_two.id)], "action": "set_status", "status": "resolved"},
        )

        rows = self._get_issue_state_rows()
        assert len(rows) == 2
        for row in rows:
            assert row[3] == "resolved"  # issue_status

    def test_bulk_assign_syncs(self):
        issue_one = self._create_issue(fingerprints=["fp_one"])
        issue_two = self._create_issue(fingerprints=["fp_two"])

        self.client.post(
            f"/api/environments/{self.team.id}/error_tracking/issues/bulk",
            data={
                "ids": [str(issue_one.id), str(issue_two.id)],
                "action": "assign",
                "assignee": {"id": self.user.id, "type": "user"},
            },
        )

        rows = self._get_issue_state_rows()
        assert len(rows) == 2
        for row in rows:
            assert row[4] == self.user.id  # assigned_user_id

    def test_merge_syncs(self):
        issue_one = self._create_issue(fingerprints=["fp_one"])
        issue_two = self._create_issue(fingerprints=["fp_two"])

        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                f"/api/environments/{self.team.id}/error_tracking/issues/{issue_one.id}/merge",
                data={"ids": [str(issue_two.id)]},
            )

        rows = self._get_issue_state_rows()
        assert len(rows) == 2
        for row in rows:
            assert str(row[1]) == str(issue_one.id)  # both fingerprints point to issue_one

    def test_split_syncs(self):
        issue = self._create_issue(fingerprints=["fp_keep", "fp_split"])

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                f"/api/environments/{self.team.id}/error_tracking/issues/{issue.id}/split",
                data={"fingerprints": [{"fingerprint": "fp_split", "name": "Split issue"}]},
                format="json",
            )
        new_issue_id = response.json()["new_issue_ids"][0]

        rows = self._get_issue_state_rows()
        rows_by_fp = {r[0]: r for r in rows}

        assert str(rows_by_fp["fp_keep"][1]) == str(issue.id)
        assert str(rows_by_fp["fp_split"][1]) == new_issue_id
