from typing import Any

from posthog.test.base import BaseTest

from parameterized import parameterized
from rest_framework import serializers

from posthog.models import Team
from posthog.models.integration import ANY, Integration

from products.integrations.backend.presentation.fields import IntegrationReferenceField


class _Serializer(serializers.Serializer):
    integration = IntegrationReferenceField()
    github = IntegrationReferenceField(kinds=["github"], required=False, allow_null=True)


class TestIntegrationReferenceField(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.slack = Integration.objects._with_auth(ANY).create(team=self.team, kind="slack", integration_id="s")
        self.github = Integration.objects._with_auth(ANY).create(
            team=self.team, kind="github", integration_id="g", config={"auth_type": "token"}
        )
        other_team = Team.objects.create(organization=self.organization, name="Other")
        self.other = Integration.objects._with_auth(ANY).create(team=other_team, kind="slack", integration_id="s")

    def _validate(self, data: dict[str, Any], context: dict[str, Any] | None = None) -> _Serializer:
        serializer = _Serializer(data=data, context={"team_id": self.team.id} if context is None else context)
        serializer.is_valid()
        return serializer

    @parameterized.expand(
        [
            ("int", lambda self: self.slack.id),
            ("string", lambda self: str(self.slack.id)),
        ]
    )
    def test_accepts_an_id_of_the_team(self, _name: str, value: Any) -> None:
        serializer = self._validate({"integration": value(self), "github": self.github.id})

        assert serializer.errors == {}
        assert serializer.validated_data == {"integration": self.slack, "github": self.github}

    def test_reads_the_team_from_get_team(self) -> None:
        serializer = self._validate({"integration": self.slack.id}, context={"get_team": lambda: self.team})

        assert serializer.validated_data == {"integration": self.slack}

    @parameterized.expand(
        [
            ("other_team", lambda self: {"integration": self.other.id}, "integration", "does_not_exist"),
            ("missing", lambda self: {"integration": 10**9}, "integration", "does_not_exist"),
            (
                "other_kind",
                lambda self: {"integration": self.slack.id, "github": self.slack.id},
                "github",
                "does_not_exist",
            ),
            ("not_a_number", lambda self: {"integration": "abc"}, "integration", "incorrect_type"),
            ("bool", lambda self: {"integration": True}, "integration", "incorrect_type"),
            ("list", lambda self: {"integration": [1]}, "integration", "incorrect_type"),
        ]
    )
    def test_rejects(self, _name: str, data: Any, field: str, code: str) -> None:
        serializer = self._validate(data(self))

        assert [error.code for error in serializer.errors[field]] == [code]

    def test_needs_a_team_in_the_context(self) -> None:
        serializer = self._validate({"integration": self.slack.id}, context={})

        assert [error.code for error in serializer.errors["integration"]] == ["no_team"]

    def test_represents_the_id(self) -> None:
        field = IntegrationReferenceField()

        assert (field.to_representation(self.slack), field.to_representation(self.slack.id)) == (
            self.slack.id,
            self.slack.id,
        )
