from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.db import connection
from django.test.utils import CaptureQueriesContext

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature

from products.access_control.backend.facade.api import upsert_property_access_control
from products.access_control.backend.facade.contracts import PropertyAccessLevel, UpsertPropertyAccessControlInput
from products.error_tracking.backend.logic import team_flags
from products.error_tracking.backend.logic.issue_tags.rules import (
    MAX_ISSUE_TAG_RULE_FILTERS_BYTES,
    MAX_ISSUE_TAG_RULES_PER_TEAM,
)
from products.error_tracking.backend.logic.issue_tags.runner import run_issue_taggers
from products.error_tracking.backend.models import ErrorTrackingIssue, ErrorTrackingIssueTag, ErrorTrackingIssueTagRule
from products.event_definitions.backend.models import PropertyDefinition

from common.hogvm.python.utils import MAX_REGEX_PATTERN_LENGTH

Source = ErrorTrackingIssueTag.Source


def _event_filter(key: str, value: Any, *, filter_type: str = "event", operator: str = "exact") -> dict[str, Any]:
    leaf = {"key": key, "type": filter_type, "operator": operator, "value": value}
    return {"type": "AND", "values": [{"type": "AND", "values": [leaf]}]}


ENTERPRISE_PLAN = _event_filter("plan", ["enterprise"])
BIG_ORDER = _event_filter("revenue", 10, operator="gt")
# No filter type, which the compiler reads as an event property.
UNTYPED_PRO_PLAN = {"type": "AND", "values": [{"type": "AND", "values": [{"key": "plan", "value": ["pro"]}]}]}
CHECKOUT_PAGE = _event_filter("$pathname", ["/checkout"])
ENTERPRISE_OR_PRO_PLAN = _event_filter("plan", ["enterprise", "pro"])
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
                        ENTERPRISE_PLAN["values"][0],
                        _event_filter("email", ["a@example.com"], filter_type="person")["values"][0],
                    ],
                },
            ),
            ("compile_error", _event_filter("plan", "(", operator="regex")),
            ("oversized_filters", _event_filter("plan", ["x" * MAX_ISSUE_TAG_RULE_FILTERS_BYTES])),
            ("not_a_filter_group", {"not": "valid"}),
            ("no_filters", {"type": "AND", "values": [{"type": "AND", "values": []}]}),
            ("empty_property_key", _event_filter("", "4", operator="icontains")),
            ("empty_filter_beside_an_event_filter", {"type": "OR", "values": [{}, ENTERPRISE_PLAN]}),
            ("date_operator_with_a_number", _event_filter("plan", 5, operator="is_date_exact")),
            ("regex_over_the_vm_limit", _event_filter("plan", "a" * (MAX_REGEX_PATTERN_LENGTH + 1), operator="regex")),
            # The compiler wraps a contains value in two wildcards, which puts this pattern one over the limit.
            (
                "contains_over_the_vm_limit",
                _event_filter("plan", "a" * (MAX_REGEX_PATTERN_LENGTH - 1), operator="icontains"),
            ),
            ("three_levels_of_groups", {"type": "AND", "values": [ENTERPRISE_PLAN]}),
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
            ("label", {"label": "Big customer"}, "Big customer", "", 1, DISABLED, True, []),
            ("description", {"description": "Pays yearly"}, "Enterprise", "Pays yearly", 1, DISABLED, True, []),
            ("same_filters", {"filters": ENTERPRISE_PLAN}, "Enterprise", "", 1, None, True, []),
            ("same_property", {"filters": ENTERPRISE_OR_PRO_PLAN}, "Enterprise", "", 2, None, True, []),
            ("new_property", {"filters": CHECKOUT_PAGE}, "Enterprise", "", 2, None, False, [2]),
        ]
    )
    def test_only_a_filter_edit_restarts_the_rule(
        self,
        _name: str,
        payload: dict[str, Any],
        label: str,
        description: str,
        version: int,
        disabled_data: dict[str, Any] | None,
        keeps_key_and_labels: bool,
        checkout_tag_versions: list[int],
    ) -> None:
        rule = self._create()
        tag = self._tag(rule, ErrorTrackingIssue.objects.create(team=self.team))
        ErrorTrackingIssueTagRule.objects.for_team(self.team.id).filter(id=rule["id"]).update(disabled_data=DISABLED)

        response = self.client.patch(self._url(rule["id"]), data=payload, format="json")

        assert response.status_code == status.HTTP_204_NO_CONTENT, response.json()
        updated = self.client.get(self._url(rule["id"])).json()
        assert (
            updated["key"] == rule["key"],
            updated["label"],
            updated["description"],
            updated["version"],
            updated["disabled_data"],
        ) == (keeps_key_and_labels, label, description, version, disabled_data)
        assert ErrorTrackingIssueTag.objects.for_team(self.team.id).filter(id=tag.id).exists() == keeps_key_and_labels
        # The issue list filters and shows only the keys in the team's tag definitions, so a key left out matches nothing.
        definitions = self.client.get(f"/api/projects/{self.team.id}/error_tracking/issues/tag_definitions/").json()
        defined_keys = {definition["key"] for definition in definitions["results"]}
        active = disabled_data is None
        assert (rule["key"] in defined_keys, updated["key"] in defined_keys) == (
            keeps_key_and_labels and active,
            active,
        )
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

    def test_create_rejects_a_rule_above_the_project_limit(self) -> None:
        ErrorTrackingIssueTagRule.objects.for_team(self.team.id).bulk_create(
            [
                ErrorTrackingIssueTagRule(team=self.team, label=f"Rule {index}", filters={}, bytecode=[], order_key=0)
                for index in range(MAX_ISSUE_TAG_RULES_PER_TEAM)
            ]
        )

        response = self.client.post(self._url(), data={"label": "One more", "filters": ENTERPRISE_PLAN}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert ErrorTrackingIssueTagRule.objects.for_team(self.team.id).count() == MAX_ISSUE_TAG_RULES_PER_TEAM

    @parameterized.expand(
        [("canonical", str), ("uppercase", str.upper), ("no_hyphens", lambda key: key.replace("-", ""))]
    )
    def test_reorder_sets_the_list_order(self, _name: str, key_form: Any) -> None:
        first, second = self._create(), self._create("Checkout", CHECKOUT_PAGE)

        reorder = self.client.patch(
            self._url("reorder"),
            data={"orders": {key_form(first["id"]): 1, key_form(second["id"]): 0}},
            format="json",
        )

        assert reorder.status_code == status.HTTP_204_NO_CONTENT
        assert [rule["id"] for rule in self.client.get(self._url()).json()["results"]] == [second["id"], first["id"]]

    @parameterized.expand(
        [
            ("order_key_above_the_column", {"order_key": 2**31}),
            ("order_key_below_the_column", {"order_key": -(2**31) - 1}),
            ("description_over_the_limit", {"description": "x" * 1001}),
        ]
    )
    def test_create_and_change_reject_a_value_the_rule_cannot_store(self, _name: str, value: dict[str, Any]) -> None:
        rule = self._create()

        create = self.client.post(
            self._url(), data={"label": "Far", "filters": ENTERPRISE_PLAN, **value}, format="json"
        )
        if "order_key" in value:
            change = self.client.patch(
                self._url("reorder"), data={"orders": {rule["id"]: value["order_key"]}}, format="json"
            )
        else:
            change = self.client.patch(self._url(rule["id"]), data=value, format="json")

        assert (create.status_code, change.status_code) == (status.HTTP_400_BAD_REQUEST, status.HTTP_400_BAD_REQUEST)
        stored = ErrorTrackingIssueTagRule.objects.for_team(self.team.id).get()
        assert (stored.order_key, stored.description) == (0, "")

    def test_a_member_cannot_see_or_change_a_rule_on_a_property_they_may_not_read(self) -> None:
        hidden = ErrorTrackingIssueTagRule.objects.for_team(self.team.id).create(
            team=self.team, label="Big order", filters=BIG_ORDER, bytecode=[], order_key=5
        )
        visible = self._create()
        self._restrict_revenue_and_email_for_the_user()

        listed = [rule["id"] for rule in self.client.get(self._url()).json()["results"]]
        statuses = {
            "get": self.client.get(self._url(str(hidden.id))).status_code,
            "edit": self.client.patch(self._url(str(hidden.id)), data={"label": "Mine"}, format="json").status_code,
            "delete": self.client.delete(self._url(str(hidden.id))).status_code,
            "create": self.client.post(
                self._url(), data={"label": "Big order", "filters": BIG_ORDER}, format="json"
            ).status_code,
            "edit_into": self.client.patch(
                self._url(visible["id"]), data={"filters": BIG_ORDER}, format="json"
            ).status_code,
            "reorder": self.client.patch(
                self._url("reorder"), data={"orders": {str(hidden.id): 0}}, format="json"
            ).status_code,
            "create_untyped": self.client.post(
                self._url(), data={"label": "Pro plan", "filters": UNTYPED_PRO_PLAN}, format="json"
            ).status_code,
            "create_on_person_properties_in_set": self.client.post(
                self._url(),
                data={"label": "Acme", "filters": _event_filter("$set", "@acme.com", operator="icontains")},
                format="json",
            ).status_code,
        }

        assert listed == [visible["id"]]
        assert statuses == {
            "get": status.HTTP_404_NOT_FOUND,
            "edit": status.HTTP_404_NOT_FOUND,
            "delete": status.HTTP_404_NOT_FOUND,
            "create": status.HTTP_400_BAD_REQUEST,
            "edit_into": status.HTTP_400_BAD_REQUEST,
            "reorder": status.HTTP_204_NO_CONTENT,
            "create_untyped": status.HTTP_201_CREATED,
            "create_on_person_properties_in_set": status.HTTP_400_BAD_REQUEST,
        }
        rules = ErrorTrackingIssueTagRule.objects.for_team(self.team.id)
        assert {(rule.label, rule.order_key, rule.filters == BIG_ORDER) for rule in rules} == {
            ("Big order", 5, True),
            ("Enterprise", 0, False),
            ("Pro plan", 0, False),
        }
        assert rules.get(label="Pro plan").filters["values"][0]["values"][0]["type"] == "event"

    @parameterized.expand(
        [(method, target) for method in ("get", "patch", "delete") for target in ("another_project", "malformed_id")]
    )
    def test_a_rule_outside_the_project_is_not_found(self, method: str, target: str) -> None:
        other_team = self.create_team_with_organization(organization=self.organization)
        other_rule = ErrorTrackingIssueTagRule.objects.for_team(other_team.id).create(
            team=other_team, label="Theirs", filters=ENTERPRISE_PLAN, bytecode=[], order_key=0
        )
        rule_id = str(other_rule.id) if target == "another_project" else "not-a-uuid"

        response = getattr(self.client, method)(self._url(rule_id), data={"label": "Mine"}, format="json")

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

    def _restrict_revenue_and_email_for_the_user(self) -> None:
        self.organization.available_product_features = [
            {"name": AvailableFeature.PROPERTY_ACCESS_CONTROL, "key": AvailableFeature.PROPERTY_ACCESS_CONTROL}
        ]
        self.organization.save()
        for name, property_type in (
            ("revenue", PropertyDefinition.Type.EVENT),
            ("email", PropertyDefinition.Type.PERSON),
        ):
            definition = PropertyDefinition.objects.create(team=self.team, name=name, type=property_type)
            upsert_property_access_control(
                team_id=self.team.id,
                created_by_id=self.user.id,
                input=UpsertPropertyAccessControlInput(
                    property_definition_id=str(definition.id),
                    access_level=PropertyAccessLevel.NONE,
                    organization_member_id=self.organization_membership.id,
                ),
            )
