from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.db import connection
from django.test.utils import CaptureQueriesContext

from parameterized import parameterized
from rest_framework import status

from products.error_tracking.backend.logic import team_flags
from products.error_tracking.backend.logic.issue_tags.runner import run_issue_taggers
from products.error_tracking.backend.models import ErrorTrackingIssue, ErrorTrackingIssueTag, ErrorTrackingIssueTagRule

Source = ErrorTrackingIssueTag.Source


def _event_filter(key: str, value: Any, *, filter_type: str = "event", operator: str = "exact") -> dict[str, Any]:
    leaf = {"key": key, "type": filter_type, "operator": operator, "value": value}
    return {"type": "AND", "values": [{"type": "AND", "values": [leaf]}]}


ENTERPRISE_PLAN = _event_filter("plan", ["enterprise"])
CHECKOUT_PAGE = _event_filter("$pathname", ["/checkout"])
DISABLED = {"message": "Rule timed out"}


@patch.object(team_flags, "feature_enabled_or_false", new=lambda *args, **kwargs: True)
class TestIssueTagRuleAPI(APIBaseTest):
    def _url(self, rule_id: str | None = None) -> str:
        base = f"/api/projects/{self.team.id}/error_tracking/tag_rules/"
        return f"{base}{rule_id}/" if rule_id else base

    def _create(self, label: str = "Enterprise", filters: dict[str, Any] = ENTERPRISE_PLAN) -> dict[str, Any]:
        response = self.client.post(self._url(), data={"label": label, "filters": filters}, format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        return response.json()

    def _tag(self, rule: dict[str, Any], issue: ErrorTrackingIssue) -> ErrorTrackingIssueTag:
        return ErrorTrackingIssueTag.objects.for_team(self.team.id).create(
            team=self.team, issue=issue, key=rule["key"], value=True, source=Source.RULE, question_version=1
        )

    def test_a_created_rule_labels_a_new_issue_that_matches(self) -> None:
        rule = self._create()
        matching = ErrorTrackingIssue.objects.create(team=self.team)
        other = ErrorTrackingIssue.objects.create(team=self.team)

        run_issue_taggers(self.team.id, matching.id, lambda team: {"plan": "enterprise"})
        run_issue_taggers(self.team.id, other.id, lambda team: {"plan": "free"})

        tags = ErrorTrackingIssueTag.objects.for_team(self.team.id).filter(key=rule["key"])
        assert list(tags.values_list("issue_id", "value", "question_version")) == [(matching.id, True, 1)]
        assert (rule["label"], rule["version"], rule["disabled_data"]) == ("Enterprise", 1, None)

    @parameterized.expand(
        [
            ("person_filter", _event_filter("email", ["a@example.com"], filter_type="person")),
            ("cohort_filter", _event_filter("id", 1, filter_type="cohort", operator="in")),
            (
                "hogql_filter",
                {"type": "AND", "values": [{"type": "AND", "values": [{"key": "1 = 1", "type": "hogql"}]}]},
            ),
            (
                "person_filter_beside_an_event_filter",
                {
                    "type": "OR",
                    "values": [
                        ENTERPRISE_PLAN,
                        _event_filter("email", ["a@example.com"], filter_type="person"),
                    ],
                },
            ),
            ("compile_error", _event_filter("plan", "(", operator="regex")),
            ("oversized_bytecode", _event_filter("plan", [f"plan-{i}" for i in range(5_000)])),
            ("not_a_filter_group", {"not": "valid"}),
            ("no_filters", {"type": "AND", "values": [{"type": "AND", "values": []}]}),
        ]
    )
    def test_create_and_edit_reject_filters_a_rule_cannot_run(self, _name: str, filters: dict[str, Any]) -> None:
        rule = ErrorTrackingIssueTagRule.objects.for_team(self.team.id).create(
            team=self.team, label="Enterprise", filters=ENTERPRISE_PLAN, bytecode=[], order_key=0
        )

        created = self.client.post(self._url(), data={"label": "Enterprise", "filters": filters}, format="json")
        edited = self.client.patch(self._url(str(rule.id)), data={"filters": filters}, format="json")

        for response in (created, edited):
            assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
            assert response.json()["attr"] == "filters"
        assert list(ErrorTrackingIssueTagRule.objects.unscoped().values_list("id", "filters")) == [
            (rule.id, ENTERPRISE_PLAN)
        ]

    @parameterized.expand(
        [
            ("label", {"label": "Big customer"}, "Big customer", 1, DISABLED, []),
            ("same_filters", {"filters": ENTERPRISE_PLAN}, "Enterprise", 1, None, []),
            ("new_filters", {"filters": CHECKOUT_PAGE}, "Enterprise", 2, None, [2]),
        ]
    )
    def test_only_a_filter_edit_restarts_the_rule(
        self,
        _name: str,
        payload: dict[str, Any],
        label: str,
        version: int,
        disabled_data: dict[str, Any] | None,
        checkout_tag_versions: list[int],
    ) -> None:
        rule = self._create()
        tag = self._tag(rule, ErrorTrackingIssue.objects.create(team=self.team))
        ErrorTrackingIssueTagRule.objects.for_team(self.team.id).filter(id=rule["id"]).update(disabled_data=DISABLED)

        response = self.client.patch(self._url(rule["id"]), data=payload, format="json")

        assert response.status_code == status.HTTP_204_NO_CONTENT, response.json()
        updated = self.client.get(self._url(rule["id"])).json()
        assert (updated["key"], updated["label"], updated["version"], updated["disabled_data"]) == (
            rule["key"],
            label,
            version,
            disabled_data,
        )
        assert ErrorTrackingIssueTag.objects.for_team(self.team.id).filter(id=tag.id).exists()
        checkout = ErrorTrackingIssue.objects.create(team=self.team)
        run_issue_taggers(self.team.id, checkout.id, lambda team: {"$pathname": "/checkout"})
        checkout_tags = ErrorTrackingIssueTag.objects.for_team(self.team.id).filter(issue=checkout)
        assert list(checkout_tags.values_list("question_version", flat=True)) == checkout_tag_versions

    def test_delete_removes_the_rule_and_only_its_tags(self) -> None:
        deleted, kept = self._create(), self._create("Checkout", CHECKOUT_PAGE)
        issue = ErrorTrackingIssue.objects.create(team=self.team)
        self._tag(deleted, issue)
        kept_tag = self._tag(kept, issue)

        response = self.client.delete(self._url(deleted["id"]))

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert [
            str(rule_id) for rule_id in ErrorTrackingIssueTagRule.objects.unscoped().values_list("id", flat=True)
        ] == [kept["id"]]
        assert list(ErrorTrackingIssueTag.objects.unscoped().values_list("id", flat=True)) == [kept_tag.id]

    def test_reorder_sets_the_list_order(self) -> None:
        first, second = self._create(), self._create("Checkout", CHECKOUT_PAGE)

        reorder = self.client.patch(
            self._url("reorder"), data={"orders": {first["id"]: 1, second["id"]: 0}}, format="json"
        )

        assert reorder.status_code == status.HTTP_204_NO_CONTENT
        assert [rule["id"] for rule in self.client.get(self._url()).json()["results"]] == [second["id"], first["id"]]

    @parameterized.expand([("get",), ("patch",), ("delete",)])
    def test_another_projects_rule_is_not_found(self, method: str) -> None:
        other_team = self.create_team_with_organization(organization=self.organization)
        other_rule = ErrorTrackingIssueTagRule.objects.for_team(other_team.id).create(
            team=other_team, label="Theirs", filters=ENTERPRISE_PLAN, bytecode=[], order_key=0
        )

        response = getattr(self.client, method)(self._url(str(other_rule.id)), data={"label": "Mine"}, format="json")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert ErrorTrackingIssueTagRule.objects.unscoped().get(id=other_rule.id).label == "Theirs"

    @parameterized.expand(
        [
            ("list", "get", None, None),
            ("retrieve", "get", "rule", None),
            ("create", "post", None, {"label": "Enterprise", "filters": ENTERPRISE_PLAN}),
            ("update", "patch", "rule", {"label": "Big customer"}),
            ("delete", "delete", "rule", None),
            ("reorder", "patch", "reorder", {"orders": {}}),
        ]
    )
    def test_reads_no_rules_while_issue_tags_are_off(
        self, _name: str, method: str, target: str | None, payload: dict[str, Any] | None
    ) -> None:
        rule = ErrorTrackingIssueTagRule.objects.for_team(self.team.id).create(
            team=self.team, label="Enterprise", filters=ENTERPRISE_PLAN, bytecode=[], order_key=0
        )
        url = {None: self._url(), "rule": self._url(str(rule.id)), "reorder": self._url("reorder")}[target]

        with (
            patch.object(team_flags, "feature_enabled_or_false", return_value=False),
            CaptureQueriesContext(connection) as queries,
        ):
            response = getattr(self.client, method)(url, data=payload, format="json")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()["detail"] == "Issue tags are off for this project."
        assert not [query for query in queries if ErrorTrackingIssueTagRule._meta.db_table in query["sql"]]
