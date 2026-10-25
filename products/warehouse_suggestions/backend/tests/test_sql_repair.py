from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.access_control.backend.models.access_control import AccessControl
from products.data_modeling.backend.facade.contracts import SavedQueryRepairPlan, SavedQueryRepairValidation
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.warehouse_suggestions.backend.presentation.serializers import ProposeSqlRepairSerializer

FLAG = "products.warehouse_suggestions.backend.presentation.views.is_warehouse_suggestions_enabled"
PREPARE = "products.warehouse_suggestions.backend.logic.sql_repair.prepare_saved_query_repair"
ORIGINAL_SQL = "SELECT 1 AS id"
PROPOSED_SQL = "SELECT 2 AS id"


class TestProposeSqlRepairSerializer(SimpleTestCase):
    def test_required_explanations_cannot_be_blank(self) -> None:
        serializer = ProposeSqlRepairSerializer(
            data={
                "saved_query_id": uuid4(),
                "proposed_query": PROPOSED_SQL,
                "failure_evidence": "",
                "reason": "",
                "expected_effect": "",
            }
        )

        assert not serializer.is_valid()
        assert set(serializer.errors) == {"failure_evidence", "reason", "expected_effect"}


class TestProposeSqlRepairAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(patch(FLAG, return_value=True))
        self.view = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="orders",
            query={"kind": "HogQLQuery", "query": ORIGINAL_SQL},
            columns={"id": {"clickhouse": "UInt8"}},
            column_order=["id"],
        )
        self.url = f"/api/projects/{self.team.id}/warehouse_suggestions/sql_repair/"

    def _authorization(self, scopes: list[str]) -> str:
        token = generate_random_token_personal()
        PersonalAPIKey.objects.create(label="k", user=self.user, secure_value=hash_key_value(token), scopes=scopes)
        self.client.logout()
        return f"Bearer {token}"

    def _body(self) -> dict[str, str]:
        return {
            "saved_query_id": str(self.view.id),
            "proposed_query": PROPOSED_SQL,
            "failure_evidence": "The refresh cannot convert the new source value.",
            "reason": "The explicit conversion keeps the current result type.",
            "expected_effect": "The next refresh can read the new value.",
        }

    def _plan(self) -> SavedQueryRepairPlan:
        return SavedQueryRepairPlan(
            saved_query_id=self.view.id,
            subject_name=self.view.name,
            original_query=ORIGINAL_SQL,
            original_query_revision=str(self.view.query_revision),
            original_query_hash="a" * 64,
            proposed_query=PROPOSED_SQL,
            validation=SavedQueryRepairValidation(
                syntax_valid=True,
                references_valid=True,
                result_schema_compatible=True,
                read_only=True,
                rows_read=0,
                business_equivalence_checked=False,
            ),
        )

    def test_authorized_producer_creates_one_reviewable_proposal_without_editing_the_view(self) -> None:
        authorization = self._authorization(["warehouse_suggestion_proposal:write", "warehouse_view:read"])

        with patch(PREPARE, return_value=self._plan()):
            first = self.client.post(self.url, self._body(), HTTP_AUTHORIZATION=authorization)
            second = self.client.post(self.url, self._body(), HTTP_AUTHORIZATION=authorization)

        self.view.refresh_from_db()
        assert first.status_code == status.HTTP_200_OK, first.json()
        assert second.status_code == status.HTTP_200_OK, second.json()
        assert second.json()["id"] == first.json()["id"]
        assert first.json()["kind"] == "sql_repair"
        assert first.json()["payload"]["validation"] == {
            "syntax_valid": True,
            "references_valid": True,
            "result_schema_compatible": True,
            "read_only": True,
            "rows_read": 0,
            "business_equivalence_checked": False,
        }
        assert self.view.query == {"kind": "HogQLQuery", "query": ORIGINAL_SQL}

    def test_producer_needs_the_internal_proposal_scope(self) -> None:
        authorization = self._authorization(["warehouse_view:read"])

        response = self.client.post(self.url, self._body(), HTTP_AUTHORIZATION=authorization)

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()

    def test_producer_needs_read_access_to_the_saved_view(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save(update_fields=["available_product_features"])
        AccessControl.objects.create(
            team=self.team,
            resource="warehouse_view",
            resource_id=str(self.view.id),
            organization_member=self.organization_membership,
            access_level="none",
        )
        authorization = self._authorization(["warehouse_suggestion_proposal:write", "warehouse_view:read"])

        response = self.client.post(self.url, self._body(), HTTP_AUTHORIZATION=authorization)

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()

    def test_producer_cannot_target_a_view_in_another_project(self) -> None:
        authorization = self._authorization(["warehouse_suggestion_proposal:write", "warehouse_view:read"])
        body = {**self._body(), "saved_query_id": str(uuid4())}

        response = self.client.post(self.url, body, HTTP_AUTHORIZATION=authorization)

        assert response.status_code == status.HTTP_404_NOT_FOUND, response.json()

    def test_endpoint_uses_the_payload_serializer(self) -> None:
        authorization = self._authorization(["warehouse_suggestion_proposal:write", "warehouse_view:read"])

        response = self.client.post(self.url, {**self._body(), "reason": ""}, HTTP_AUTHORIZATION=authorization)

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["attr"] == "reason"
