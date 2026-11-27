from posthog.test.base import BaseTest

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models import Team

from products.event_definitions.backend.facade import api
from products.event_definitions.backend.facade.enums import PropertyDefinitionType, PropertyType
from products.event_definitions.backend.facade.testing import create_property_definition, find_property_definitions
from products.event_definitions.backend.property_type import PropertyType as ModelPropertyType


class TestFacadeEnums(SimpleTestCase):
    def test_property_type_matches_the_model_choices(self) -> None:
        assert PropertyType.choices == ModelPropertyType.choices
        assert PropertyType.names == ModelPropertyType.names


class TestUpsertGroupPropertyDefinition(BaseTest):
    @parameterized.expand(
        [
            ("numeric", PropertyType.Numeric, True),
            ("string", PropertyType.String, False),
        ]
    )
    def test_creates_the_definition(self, _name: str, property_type: PropertyType, is_numerical: bool) -> None:
        api.upsert_group_property_definition(
            team_id=self.team.id,
            project_id=self.team.project_id,
            group_type_index=1,
            name="industry",
            property_type=property_type,
        )

        [definition] = find_property_definitions(project_id=self.team.project_id, name="industry")
        assert (definition.team_id, definition.type, definition.group_type_index) == (
            self.team.id,
            PropertyDefinitionType.GROUP,
            1,
        )
        assert (definition.property_type, definition.is_numerical) == (property_type, is_numerical)

    def test_updates_the_definition_another_environment_of_the_project_created(self) -> None:
        sibling = Team.objects.create(organization=self.organization, project=self.team.project)
        existing = create_property_definition(
            team_id=sibling.id,
            project_id=self.team.project_id,
            name="industry",
            type=PropertyDefinitionType.GROUP,
            group_type_index=0,
            property_type=PropertyType.Numeric,
            is_numerical=True,
        )

        api.upsert_group_property_definition(
            team_id=self.team.id,
            project_id=self.team.project_id,
            group_type_index=0,
            name="industry",
            property_type=PropertyType.String,
        )

        [definition] = find_property_definitions(project_id=self.team.project_id, name="industry")
        assert (definition.id, definition.team_id, definition.property_type, definition.is_numerical) == (
            existing.id,
            sibling.id,
            PropertyType.String,
            False,
        )


class TestGetPropertyType(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        create_property_definition(team_id=self.team.id, name="plan", property_type=PropertyType.String)
        create_property_definition(team_id=self.team.id, name="untyped")
        create_property_definition(
            team_id=self.team.id,
            name="plan",
            type=PropertyDefinitionType.GROUP,
            group_type_index=2,
            property_type=PropertyType.Numeric,
        )

    @parameterized.expand(
        [
            ("an_event_property", "plan", PropertyDefinitionType.EVENT, None, PropertyType.String),
            ("ignores_the_group_index_outside_groups", "plan", PropertyDefinitionType.EVENT, 2, PropertyType.String),
            ("a_group_property", "plan", PropertyDefinitionType.GROUP, 2, PropertyType.Numeric),
            ("another_group_type", "plan", PropertyDefinitionType.GROUP, 1, None),
            ("another_definition_type", "plan", PropertyDefinitionType.PERSON, None, None),
            ("a_definition_without_a_type", "untyped", PropertyDefinitionType.EVENT, None, None),
            ("a_missing_definition", "missing", PropertyDefinitionType.EVENT, None, None),
        ]
    )
    def test_reads_the_type_of_the_matching_definition(
        self,
        _name: str,
        name: str,
        type: PropertyDefinitionType,
        group_type_index: int | None,
        expected: PropertyType | None,
    ) -> None:
        assert (
            api.get_property_type(
                project_id=self.team.project_id, name=name, type=type, group_type_index=group_type_index
            )
            == expected
        )

    def test_reads_a_definition_another_environment_of_the_project_created(self) -> None:
        sibling = Team.objects.create(organization=self.organization, project=self.team.project)
        create_property_definition(
            team_id=sibling.id, project_id=self.team.project_id, name="tier", property_type=PropertyType.Boolean
        )

        assert (
            api.get_property_type(project_id=self.team.project_id, name="tier", type=PropertyDefinitionType.EVENT)
            == PropertyType.Boolean
        )
