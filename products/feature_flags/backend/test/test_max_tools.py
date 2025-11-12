from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, patch

from posthog.schema import FeatureFlagGroupType, GroupPropertyFilter, PersonPropertyFilter, PropertyOperator

from posthog.models import FeatureFlag
from posthog.models.group_type_mapping import GroupTypeMapping

from products.feature_flags.backend.max_tools import CreateFeatureFlagTool, FeatureFlagCreationSchema

from ee.hogai.utils.types import AssistantState


class TestCreateFeatureFlagTool(APIBaseTest):
    def _create_tool(self) -> CreateFeatureFlagTool:
        """Helper to create a tool instance."""
        return CreateFeatureFlagTool(
            team=self.team,
            user=self.user,
            tool_call_id="test-call",
            state=AssistantState(messages=[]),
        )

    async def test_create_flag_minimal(self):
        """Test creating a minimal feature flag via instructions."""
        tool = self._create_tool()

        # Mock the graph to return a simple schema
        mock_schema = FeatureFlagCreationSchema(
            key="test-flag",
            name="Test Flag",
        )

        with patch.object(tool, "_create_flag_from_instructions", new=AsyncMock(return_value=mock_schema)):
            result, artifact = await tool._arun_impl(instructions="Create a feature flag called test-flag")

            assert "Successfully created" in result
            assert artifact["flag_key"] == "test-flag"
            assert artifact["flag_name"] == "Test Flag"
            assert "/feature_flags/" in artifact["url"]

            flag = await FeatureFlag.objects.aget(key="test-flag", team=self.team)
            assert flag.name == "Test Flag"
            assert flag.active is True
            assert flag.filters == {"groups": []}

    async def test_create_flag_with_rollout_percentage(self):
        """Test creating a flag with rollout percentage."""
        tool = self._create_tool()

        mock_schema = FeatureFlagCreationSchema(
            key="gradual-rollout",
            name="Gradual Rollout Flag",
            groups=[
                FeatureFlagGroupType(
                    properties=[],
                    rollout_percentage=50,
                )
            ],
        )

        with patch.object(tool, "_create_flag_from_instructions", new=AsyncMock(return_value=mock_schema)):
            result, artifact = await tool._arun_impl(instructions="Create a flag with 50% rollout")

            assert "Successfully created" in result
            assert "50% rollout" in result
            assert artifact["flag_key"] == "gradual-rollout"

            flag = await FeatureFlag.objects.aget(key="gradual-rollout", team=self.team)
            assert flag.filters["groups"][0]["rollout_percentage"] == 50

    async def test_create_flag_with_tags(self):
        """Test creating a flag with tags."""
        tool = self._create_tool()

        mock_schema = FeatureFlagCreationSchema(
            key="tagged-flag",
            name="Tagged Flag",
            tags=["experiment", "frontend"],
        )

        with patch.object(tool, "_create_flag_from_instructions", new=AsyncMock(return_value=mock_schema)):
            result, artifact = await tool._arun_impl(instructions="Create a flag with tags")

            assert "Successfully created" in result

            flag = await FeatureFlag.objects.aget(key="tagged-flag", team=self.team)
            tag_names = await self._get_tag_names(flag)
            assert "experiment" in tag_names
            assert "frontend" in tag_names

    async def test_create_flag_duplicate_key(self):
        """Test error when creating a flag with duplicate key."""
        await FeatureFlag.objects.acreate(
            team=self.team,
            created_by=self.user,
            key="existing-flag",
            name="Existing",
        )

        tool = self._create_tool()

        mock_schema = FeatureFlagCreationSchema(
            key="existing-flag",
            name="Duplicate",
        )

        with patch.object(tool, "_create_flag_from_instructions", new=AsyncMock(return_value=mock_schema)):
            result, artifact = await tool._arun_impl(instructions="Create a duplicate flag")

            assert "already exists" in result
            assert artifact.get("flag_id")

    async def test_create_flag_with_property_filter(self):
        """Test creating a flag with property filter."""
        tool = self._create_tool()

        mock_schema = FeatureFlagCreationSchema(
            key="email-filter-flag",
            name="Email Filter Flag",
            groups=[
                FeatureFlagGroupType(
                    properties=[
                        PersonPropertyFilter(
                            key="email",
                            value="@company.com",
                            operator=PropertyOperator.ICONTAINS,
                        )
                    ],
                    rollout_percentage=None,
                )
            ],
        )

        with patch.object(tool, "_create_flag_from_instructions", new=AsyncMock(return_value=mock_schema)):
            result, artifact = await tool._arun_impl(
                instructions="Create a flag for users where email contains @company.com"
            )

            assert "Successfully created" in result
            assert "1 property filter(s)" in result

            flag = await FeatureFlag.objects.aget(key="email-filter-flag", team=self.team)
            assert len(flag.filters["groups"]) == 1
            assert len(flag.filters["groups"][0]["properties"]) == 1
            assert flag.filters["groups"][0]["properties"][0]["key"] == "email"
            assert flag.filters["groups"][0]["properties"][0]["operator"] == "icontains"

    async def test_create_flag_with_property_filter_and_rollout(self):
        """Test creating a flag with both property filter and rollout percentage."""
        tool = self._create_tool()

        mock_schema = FeatureFlagCreationSchema(
            key="combined-flag",
            name="Combined Flag",
            groups=[
                FeatureFlagGroupType(
                    properties=[
                        PersonPropertyFilter(
                            key="country",
                            value="US",
                            operator=PropertyOperator.EXACT,
                        )
                    ],
                    rollout_percentage=25,
                )
            ],
        )

        with patch.object(tool, "_create_flag_from_instructions", new=AsyncMock(return_value=mock_schema)):
            result, artifact = await tool._arun_impl(instructions="Create a flag for 25% of US users")

            assert "Successfully created" in result
            assert "1 property filter(s)" in result
            assert "25% rollout" in result

            flag = await FeatureFlag.objects.aget(key="combined-flag", team=self.team)
            assert flag.filters["groups"][0]["rollout_percentage"] == 25
            assert len(flag.filters["groups"][0]["properties"]) == 1

    async def test_create_flag_with_group_type(self):
        """Test creating a group-based feature flag."""
        # Setup: Create a group type mapping
        await GroupTypeMapping.objects.acreate(
            team=self.team,
            project_id=self.team.project_id,
            group_type="organization",
            group_type_index=0,
            name_plural="Organizations",
        )

        tool = self._create_tool()

        mock_schema = FeatureFlagCreationSchema(
            key="org-flag",
            name="Organization Flag",
            group_type="organization",
        )

        with patch.object(tool, "_create_flag_from_instructions", new=AsyncMock(return_value=mock_schema)):
            result, artifact = await tool._arun_impl(instructions="Create a flag for organizations")

            assert "Successfully created" in result
            assert "Organizations" in result or "organization" in result
            assert artifact["flag_key"] == "org-flag"

            flag = await FeatureFlag.objects.aget(key="org-flag", team=self.team)
            assert flag.filters["aggregation_group_type_index"] == 0
            assert flag.filters["groups"] == []

    async def test_create_flag_with_group_and_property(self):
        """Test creating a group-based flag with property filter."""
        await GroupTypeMapping.objects.acreate(
            team=self.team,
            project_id=self.team.project_id,
            group_type="organization",
            group_type_index=0,
            name_plural="Organizations",
        )

        tool = self._create_tool()

        mock_schema = FeatureFlagCreationSchema(
            key="enterprise-orgs",
            name="Enterprise Organizations",
            group_type="organization",
            groups=[
                FeatureFlagGroupType(
                    properties=[
                        GroupPropertyFilter(
                            key="plan",
                            value="enterprise",
                            operator=PropertyOperator.EXACT,
                            group_type_index=0,
                        )
                    ],
                    rollout_percentage=None,
                )
            ],
        )

        with patch.object(tool, "_create_flag_from_instructions", new=AsyncMock(return_value=mock_schema)):
            result, artifact = await tool._arun_impl(instructions="Create a flag for enterprise organizations")

            assert "Successfully created" in result
            assert "1 property filter(s)" in result
            assert "Organizations" in result or "organization" in result

            flag = await FeatureFlag.objects.aget(key="enterprise-orgs", team=self.team)
            assert flag.filters["aggregation_group_type_index"] == 0
            assert len(flag.filters["groups"][0]["properties"]) == 1
            assert flag.filters["groups"][0]["properties"][0]["key"] == "plan"
            assert flag.filters["groups"][0]["properties"][0]["type"] == "group"

    async def test_create_flag_with_nonexistent_group_type(self):
        """Test error when group type doesn't exist."""
        tool = self._create_tool()

        mock_schema = FeatureFlagCreationSchema(
            key="invalid-group",
            name="Invalid Group",
            group_type="nonexistent",
        )

        with patch.object(tool, "_create_flag_from_instructions", new=AsyncMock(return_value=mock_schema)):
            result, artifact = await tool._arun_impl(instructions="Create a flag for nonexistent group")

            assert "does not exist" in result
            assert artifact.get("error") == "group_type_not_found"

            # Ensure flag was not created
            exists = await FeatureFlag.objects.filter(key="invalid-group", team=self.team).aexists()
            assert not exists

    async def test_create_flag_key_validation(self):
        """Test that feature flag keys follow the required regex pattern: ^[a-zA-Z0-9_-]+$"""
        import re

        tool = self._create_tool()

        # Test valid keys
        valid_keys = [
            "simple-flag",
            "flag_with_underscores",
            "Flag-With-Mixed-CASE-123",
            "123-numeric-start",
            "a",
            "flag-123_test",
        ]

        for key in valid_keys:
            mock_schema = FeatureFlagCreationSchema(
                key=key,
                name=f"Test Flag {key}",
            )

            with patch.object(tool, "_create_flag_from_instructions", new=AsyncMock(return_value=mock_schema)):
                result, artifact = await tool._arun_impl(instructions=f"Create a flag called {key}")

                assert "Successfully created" in result, f"Valid key '{key}' should be accepted"
                assert artifact["flag_key"] == key
                assert re.match(r"^[a-zA-Z0-9_-]+$", artifact["flag_key"]), f"Key '{key}' should match regex pattern"

                # Clean up for next iteration
                await FeatureFlag.objects.filter(key=key, team=self.team).adelete()

        # Test invalid keys that should be rejected
        invalid_keys = [
            "flag with spaces",
            "flag@special",
            "flag#chars",
            "flag.dot",
            "flag!exclamation",
            "flag$dollar",
            "flag%percent",
            "flag&ampersand",
            "flag(paren",
            "flag+plus",
        ]

        for key in invalid_keys:
            mock_schema = FeatureFlagCreationSchema(
                key=key,
                name=f"Test Flag {key}",
            )

            with patch.object(tool, "_create_flag_from_instructions", new=AsyncMock(return_value=mock_schema)):
                result, artifact = await tool._arun_impl(instructions=f"Create a flag called {key}")

                # Either the key should be rejected with an error, or it should be sanitized
                if artifact.get("error"):
                    assert (
                        "invalid" in result.lower() or "key" in result.lower()
                    ), f"Invalid key '{key}' should produce an error message"
                else:
                    # If not rejected, the key must be sanitized to match the regex
                    assert re.match(
                        r"^[a-zA-Z0-9_-]+$", artifact["flag_key"]
                    ), f"Invalid key '{key}' should be sanitized to match regex pattern, got '{artifact['flag_key']}'"

                # Clean up if flag was created
                if not artifact.get("error"):
                    await FeatureFlag.objects.filter(key=artifact["flag_key"], team=self.team).adelete()

    @staticmethod
    async def _get_tag_names(flag: FeatureFlag) -> list[str]:
        """Helper to get tag names for a flag."""
        from posthog.models import TaggedItem
        from posthog.sync import database_sync_to_async

        @database_sync_to_async
        def get_tags():
            return list(TaggedItem.objects.filter(feature_flag=flag).values_list("tag__name", flat=True))

        return await get_tags()
