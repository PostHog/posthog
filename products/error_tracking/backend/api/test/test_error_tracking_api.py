import os

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import ANY, Mock, patch

from boto3 import resource
from botocore.config import Config
from rest_framework import status

from posthog.models import User
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

    @patch("products.error_tracking.backend.api.symbol_sets.object_storage.get_presigned_url")
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

    @patch("products.error_tracking.backend.api.issues.dispatch_issue_assigned_realtime")
    @patch("products.error_tracking.backend.api.issues.send_error_tracking_issue_assigned")
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
        assert id_map[str(new_chunk_id)]["symbol_set_id"] == str(new_symbol_set.id)

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

    def test_bulk_start_upload_rejects_release_change(self) -> None:
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
                        "content_hash": symbol_set.content_hash,
                    }
                ]
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

        symbol_set.refresh_from_db()
        assert symbol_set.release_id == first_release.id

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
