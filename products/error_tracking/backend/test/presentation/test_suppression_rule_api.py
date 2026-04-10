from posthog.test.base import APIBaseTest

from rest_framework import status

from products.error_tracking.backend.models import ErrorTrackingSuppressionRule

VALID_FILTERS = {
    "type": "AND",
    "values": [
        {
            "type": "AND",
            "values": [
                {
                    "key": "$exception_type",
                    "type": "event",
                    "value": ["TypeError"],
                    "operator": "exact",
                }
            ],
        }
    ],
}


class TestSuppressionRuleAPI(APIBaseTest):
    def _url(self, rule_id: str | None = None) -> str:
        base = f"/api/environments/{self.team.id}/error_tracking/suppression_rules/"
        if rule_id:
            return f"{base}{rule_id}/"
        return base

    def test_create_with_valid_filters(self) -> None:
        response = self.client.post(
            self._url(),
            data={"filters": VALID_FILTERS},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["filters"] == VALID_FILTERS

        rule = ErrorTrackingSuppressionRule.objects.get(id=data["id"])
        assert rule.bytecode is not None
        assert len(rule.bytecode) > 0

    def test_create_without_filters_creates_match_all_rule(self) -> None:
        response = self.client.post(
            self._url(),
            data={"sampling_rate": 0.5},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["filters"] == {"type": "AND", "values": []}
        assert data["sampling_rate"] == 0.5

        rule = ErrorTrackingSuppressionRule.objects.get(id=data["id"])
        assert rule.bytecode is not None

    def test_create_with_empty_filters_creates_match_all_rule(self) -> None:
        response = self.client.post(
            self._url(),
            data={"filters": {"type": "OR", "values": []}},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["filters"] == {"type": "OR", "values": []}

        rule = ErrorTrackingSuppressionRule.objects.get(id=data["id"])
        assert rule.bytecode is not None

    def test_create_invalid_filters(self) -> None:
        response = self.client.post(
            self._url(),
            data={"filters": {"not": "valid"}},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["error"] == "Invalid filters"

    def test_update_changes_bytecode(self) -> None:
        create_response = self.client.post(
            self._url(),
            data={"filters": VALID_FILTERS},
            format="json",
        )
        rule_id = create_response.json()["id"]
        original_bytecode = ErrorTrackingSuppressionRule.objects.get(id=rule_id).bytecode

        new_filters = {
            "type": "AND",
            "values": [
                {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$exception_message",
                            "type": "event",
                            "value": ["something went wrong"],
                            "operator": "icontains",
                        }
                    ],
                }
            ],
        }

        response = self.client.put(
            self._url(rule_id),
            data={"filters": new_filters},
            format="json",
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT

        rule = ErrorTrackingSuppressionRule.objects.get(id=rule_id)
        assert rule.bytecode != original_bytecode
        assert rule.filters == new_filters

    def test_update_disabled_rule_without_filter_change_clears_disabled_data(self) -> None:
        rule = ErrorTrackingSuppressionRule.objects.create(
            team=self.team,
            filters=VALID_FILTERS,
            bytecode=[1, 2, 3],
            order_key=0,
            disabled_data={"message": "Rule disabled due to error"},
        )

        response = self.client.put(
            self._url(str(rule.id)),
            data={},
            format="json",
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT

        rule.refresh_from_db()
        assert rule.disabled_data is None

    def test_update_disabled_rule_with_filter_change_clears_disabled_data(self) -> None:
        rule = ErrorTrackingSuppressionRule.objects.create(
            team=self.team,
            filters=VALID_FILTERS,
            bytecode=[1, 2, 3],
            order_key=0,
            disabled_data={"message": "Rule disabled due to error"},
        )

        new_filters = {
            "type": "AND",
            "values": [
                {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$exception_message",
                            "type": "event",
                            "value": ["something went wrong"],
                            "operator": "icontains",
                        }
                    ],
                }
            ],
        }

        response = self.client.put(
            self._url(str(rule.id)),
            data={"filters": new_filters},
            format="json",
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT

        rule.refresh_from_db()
        assert rule.disabled_data is None
        assert rule.filters == new_filters
        assert rule.bytecode != [1, 2, 3]

    def test_create_with_sampling_rate(self) -> None:
        response = self.client.post(
            self._url(),
            data={"filters": VALID_FILTERS, "sampling_rate": 0.5},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["sampling_rate"] == 0.5

    def test_create_defaults_sampling_rate_to_one(self) -> None:
        response = self.client.post(
            self._url(),
            data={"filters": VALID_FILTERS},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["sampling_rate"] == 1.0

    def test_create_rejects_invalid_sampling_rate(self) -> None:
        response = self.client.post(
            self._url(),
            data={"filters": VALID_FILTERS, "sampling_rate": 1.5},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "sampling_rate" in response.json()["error"]

    def test_update_sampling_rate(self) -> None:
        create_response = self.client.post(
            self._url(),
            data={"filters": VALID_FILTERS},
            format="json",
        )
        rule_id = create_response.json()["id"]

        response = self.client.put(
            self._url(rule_id),
            data={"sampling_rate": 0.25},
            format="json",
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT

        rule = ErrorTrackingSuppressionRule.objects.get(id=rule_id)
        assert rule.sampling_rate == 0.25

    def test_partial_update_sampling_rate(self) -> None:
        create_response = self.client.post(
            self._url(),
            data={"filters": VALID_FILTERS},
            format="json",
        )
        rule_id = create_response.json()["id"]

        response = self.client.patch(
            self._url(rule_id),
            data={"sampling_rate": 0.25},
            format="json",
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT

        rule = ErrorTrackingSuppressionRule.objects.get(id=rule_id)
        assert rule.sampling_rate == 0.25
