"""
Test for the feature flag creation MaxTool.
"""

import os

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from asgiref.sync import sync_to_async
from langchain_core.runnables import RunnableConfig

from posthog.schema import FeatureFlagCreationSchema

from posthog.models import FeatureFlag

from .max_tools import CreateFeatureFlagTool

OPENAI_PATCH_PATH = "products.feature_flags.backend.max_tools.MaxChatOpenAI"


class TestCreateFeatureFlagTool(BaseTest):
    def setUp(self):
        super().setUp()
        # Set mock OpenAI API key for tests
        os.environ["OPENAI_API_KEY"] = "test-api-key"
        self._config: RunnableConfig = {
            "configurable": {
                "team": self.team,
                "user": self.user,
            },
        }

    def tearDown(self):
        super().tearDown()
        # Clean up the mock API key
        if "OPENAI_API_KEY" in os.environ:
            del os.environ["OPENAI_API_KEY"]

    def _setup_tool(self):
        """Helper to create a CreateFeatureFlagTool instance with mocked dependencies"""
        tool = CreateFeatureFlagTool(team=self.team, user=self.user)

        # Mock the internal state required by MaxTool
        tool._init_run(self._config)

        return tool

    def test_get_team_feature_flag_config(self):
        """Test team feature flag configuration function"""
        from products.feature_flags.backend.max_tools import get_team_feature_flag_config

        config = get_team_feature_flag_config(self.team)

        assert "default_settings" in config
        assert config["default_settings"]["evaluation_runtime"] == "all"
        assert config["default_settings"]["rollout_percentage"] == 0
        assert config["default_settings"]["active"]
        assert not config["default_settings"]["ensure_experience_continuity"]

    @pytest.mark.asyncio
    async def test_generate_feature_flag_key(self):
        """Test feature flag key generation"""
        from products.feature_flags.backend.max_tools import generate_feature_flag_key

        # First call should return base key
        key1 = await generate_feature_flag_key("New Feature", self.team)
        assert key1 == "new-feature"

        # Create a flag with that key to test uniqueness logic
        await FeatureFlag.objects.acreate(team=self.team, key=key1, name="Test Flag", created_by=self.user)

        # Second call should return numbered suffix since first key is taken
        key2 = await generate_feature_flag_key("New Feature", self.team)
        assert key2 == "new-feature-2"

    @patch.object(CreateFeatureFlagTool, "_create_feature_flag_from_instructions")
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_arun_impl_success(self, mock_create_flag):
        """Test successful feature flag creation through _arun_impl"""
        tool = self._setup_tool()

        # Mock the LLM response
        mock_output = FeatureFlagCreationSchema(
            key="test-flag-123",
            name="Test Feature Flag",
            active=True,
            filters={"groups": [{"properties": [], "rollout_percentage": 10}]},
            evaluation_runtime="client",
        )

        # Set up the mock to return our test data
        mock_create_flag.return_value = mock_output

        # Run the method
        content, artifact = await tool._arun_impl("Create a feature flag to test new features with 10% rollout")

        # Verify success response
        assert "Feature flag" in content
        assert "created" in content
        assert "successfully" in content
        assert "flag_id" in artifact
        assert "flag_key" in artifact
        assert "flag_name" in artifact

        # Verify feature flag was created in database
        flag = await sync_to_async(FeatureFlag.objects.get)(id=artifact["flag_id"])
        assert flag.key == "test-flag-123"
        assert flag.name == "Test Feature Flag"
        assert flag.active
        assert flag.filters["groups"][0]["rollout_percentage"] == 10
        assert flag.evaluation_runtime == "client"

    @patch.object(CreateFeatureFlagTool, "_create_feature_flag_from_instructions")
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_arun_impl_with_active_flag(self, mock_create_flag):
        """Test feature flag creation with active flag"""
        tool = self._setup_tool()

        # Mock the LLM response with active=True
        mock_output = FeatureFlagCreationSchema(
            key="active-flag-456",
            name="Active Feature Flag",
            active=True,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
            evaluation_runtime="all",
        )

        mock_create_flag.return_value = mock_output

        # Run the method
        content, artifact = await tool._arun_impl("Create an active feature flag for new dashboard")

        # Verify success response
        assert "Feature flag" in content
        assert "created" in content
        assert "successfully" in content

        # Verify feature flag was created as active
        flag = await sync_to_async(FeatureFlag.objects.get)(id=artifact["flag_id"])
        assert flag.active

    @patch.object(CreateFeatureFlagTool, "_create_feature_flag_from_instructions")
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_arun_impl_key_generation_from_name(self, mock_create_flag):
        """Test key generation when key is empty but name is provided"""
        tool = self._setup_tool()

        # Mock LLM response with no key but with name
        mock_output = FeatureFlagCreationSchema(
            key="",  # Empty key - should be generated
            name="My Awesome Feature",  # Name provided
            active=True,
            filters={"groups": [{"properties": [], "rollout_percentage": 0}]},
            evaluation_runtime="client",
        )

        mock_create_flag.return_value = mock_output

        # Run the method
        content, artifact = await tool._arun_impl("Create a feature flag")

        # Verify success response
        assert "Feature flag" in content
        assert "created" in content
        assert "successfully" in content

        # Verify key was generated from name
        flag = await sync_to_async(FeatureFlag.objects.get)(id=artifact["flag_id"])
        assert flag.key == "my-awesome-feature"  # Generated from "My awesome feature"

    @patch.object(CreateFeatureFlagTool, "_create_feature_flag_from_instructions")
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_arun_impl_key_generation_from_instructions(self, mock_create_flag):
        """Test key generation when key is empty"""
        tool = self._setup_tool()

        # Mock LLM response with no key but with name
        mock_output = FeatureFlagCreationSchema(
            key="",  # Empty key - should be generated
            name="Test feature flag",  # Required field
            active=True,
            filters={"groups": [{"properties": [], "rollout_percentage": 0}]},
            evaluation_runtime="client",
        )

        mock_create_flag.return_value = mock_output

        # Run the method with descriptive instructions
        content, artifact = await tool._arun_impl("Create a payment feature flag for new checkout")

        # Verify success response
        assert "Feature flag" in content
        assert "created" in content
        assert "successfully" in content

        # Verify key was generated from name (since name is provided)
        flag = await sync_to_async(FeatureFlag.objects.get)(id=artifact["flag_id"])
        assert flag.key == "test-feature-flag"  # Generated from "Test feature flag"

    @patch.object(CreateFeatureFlagTool, "_create_feature_flag_from_instructions")
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_arun_impl_no_key_provided(self, mock_create_flag):
        """Test key generation when no key is provided (empty string)"""
        tool = self._setup_tool()

        # Mock LLM response with empty key - should be generated from name
        mock_output = FeatureFlagCreationSchema(
            key="",  # Empty key - should be generated from name
            name="Dashboard feature",
            active=True,
            filters={"groups": [{"properties": [], "rollout_percentage": 0}]},
            evaluation_runtime="client",
        )

        mock_create_flag.return_value = mock_output

        # Run the method with descriptive instructions
        content, artifact = await tool._arun_impl("Create a flag for dashboard features")

        # Verify success response
        assert "Feature flag" in content
        assert "created" in content
        assert "successfully" in content

        # Verify key was generated from name
        flag = await sync_to_async(FeatureFlag.objects.get)(id=artifact["flag_id"])
        assert flag.key == "dashboard-feature"  # Generated from "Dashboard feature"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_prepare_feature_flag_data(self):
        """Test feature flag data preparation with defaults"""
        tool = self._setup_tool()

        # Test schema with minimal data
        schema = FeatureFlagCreationSchema(
            key="test-key",
            name="Test Flag",
            active=False,
            filters={"groups": []},
        )

        flag_data = tool._prepare_feature_flag_data(schema, self.team)

        # Verify defaults are applied
        assert flag_data["key"] == "test-key"
        assert flag_data["name"] == "Test Flag"
        assert not flag_data["active"]  # Explicitly set to False
        assert flag_data["filters"] == {"groups": []}
        assert flag_data["rollout_percentage"] == 0  # Team default
        assert not flag_data["ensure_experience_continuity"]  # Team default
        assert flag_data["evaluation_runtime"] == "all"  # Team default

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_prepare_feature_flag_data_with_variants(self):
        """Test feature flag data preparation with variants handling"""
        tool = self._setup_tool()

        # Test schema with variants (should be moved to filters.multivariate.variants)
        schema = FeatureFlagCreationSchema(
            key="test-multivariate",
            name="Test Multivariate Flag",
            active=True,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
            variants=[
                {"key": "control", "name": "Control", "rollout_percentage": 50.0},
                {"key": "test", "name": "Test", "rollout_percentage": 50.0},
            ],
        )

        flag_data = tool._prepare_feature_flag_data(schema, self.team)

        # Verify variants are moved to the correct location
        assert "variants" not in flag_data  # Should be removed from top level
        assert "multivariate" in flag_data["filters"]
        assert "variants" in flag_data["filters"]["multivariate"]

        # Verify variant structure
        variants = flag_data["filters"]["multivariate"]["variants"]
        assert len(variants) == 2
        assert variants[0] == {"key": "control", "name": "Control", "rollout_percentage": 50.0}
        assert variants[1] == {"key": "test", "name": "Test", "rollout_percentage": 50.0}

        # Verify other fields are still correct
        assert flag_data["key"] == "test-multivariate"
        assert flag_data["name"] == "Test Multivariate Flag"
        assert flag_data["active"]

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_prepare_feature_flag_data_default_evaluation_runtime(self):
        """Test that evaluation_runtime defaults to 'all' when not specified in schema"""
        tool = self._setup_tool()

        # Test schema without evaluation_runtime (should use team default)
        schema = FeatureFlagCreationSchema(
            key="test-default-runtime",
            name="Test Default Runtime",
            active=True,
            filters={"groups": [{"properties": [], "rollout_percentage": 50}]},
            # Note: evaluation_runtime is NOT specified
        )

        flag_data = tool._prepare_feature_flag_data(schema, self.team)

        # Verify evaluation_runtime uses team default ("all")
        assert flag_data["evaluation_runtime"] == "all"

        # Verify other defaults are applied correctly
        assert flag_data["key"] == "test-default-runtime"
        assert flag_data["name"] == "Test Default Runtime"
        assert flag_data["active"]
        assert flag_data["rollout_percentage"] == 0  # Team default

    @patch.object(CreateFeatureFlagTool, "_create_feature_flag_from_instructions")
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_arun_impl_with_deleted_flag_same_key(self, mock_create_flag):
        """Test creating a flag with the same key as a previously deleted flag"""
        tool = self._setup_tool()

        # First, create a flag that we'll delete
        existing_flag = await sync_to_async(FeatureFlag.objects.create)(
            team=self.team,
            created_by=self.user,
            key="test-deleted-flag",
            name="Original Flag",
            active=True,
            filters={"groups": []},
        )

        # Soft delete the flag
        existing_flag.deleted = True
        await sync_to_async(existing_flag.save)()

        # Mock LLM response to create a new flag with the same key
        mock_output = FeatureFlagCreationSchema(
            key="test-deleted-flag",  # Same key as deleted flag
            name="New Flag with Same Key",
            active=True,
            filters={"groups": [{"properties": [], "rollout_percentage": 50}]},
        )

        mock_create_flag.return_value = mock_output

        # Run the method - should succeed and cleanup the deleted flag
        content, artifact = await tool._arun_impl("Create a test flag")

        # Verify success response
        assert "Feature flag" in content
        assert "created" in content
        assert "successfully" in content

        # Verify the new flag was created
        new_flag = await sync_to_async(FeatureFlag.objects.get)(id=artifact["flag_id"])
        assert new_flag.key == "test-deleted-flag"
        assert new_flag.name == "New Flag with Same Key"
        assert not new_flag.deleted

        # Verify the old deleted flag was hard deleted (no longer in DB)
        deleted_flags_count = await sync_to_async(
            lambda: FeatureFlag.objects.filter(key="test-deleted-flag", deleted=True).count()
        )()
        assert deleted_flags_count == 0


class TestFeatureFlagToolHelpers(BaseTest):
    """Test helper methods used by CreateFeatureFlagTool"""

    def setUp(self):
        super().setUp()
        self._config: RunnableConfig = {
            "configurable": {
                "team": self.team,
                "user": self.user,
            },
        }

    def _setup_tool(self):
        """Helper to create a CreateFeatureFlagTool instance"""
        tool = CreateFeatureFlagTool(team=self.team, user=self.user)
        tool._init_run(self._config)
        return tool

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_get_existing_feature_flags_summary_empty(self):
        """Test getting existing feature flags summary when no flags exist"""
        tool = self._setup_tool()

        summary = await tool._get_existing_feature_flags_summary()

        assert summary == "No existing feature flags"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_get_existing_feature_flags_summary_with_flags(self):
        """Test getting existing feature flags summary with existing flags"""
        tool = self._setup_tool()

        # Create test feature flags
        await sync_to_async(FeatureFlag.objects.create)(
            team=self.team,
            key="inactive-flag",
            name="Inactive Flag",
            active=False,
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 0}]},
        )

        await sync_to_async(FeatureFlag.objects.create)(
            team=self.team,
            key="active-flag",
            name="Active Flag",
            active=True,
            rollout_percentage=50,
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 50}]},
        )

        summary = await tool._get_existing_feature_flags_summary()

        # Verify both flags are included
        assert "Inactive Flag" in summary
        assert "Active Flag" in summary
        assert "inactive" in summary
        assert "active" in summary
        assert "50%" in summary
        assert "0%" in summary

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_get_existing_feature_flags_summary_excludes_deleted(self):
        """Test that deleted feature flags are excluded from the summary"""
        tool = self._setup_tool()

        # Create a regular flag
        await sync_to_async(FeatureFlag.objects.create)(
            team=self.team,
            key="regular-flag",
            name="Regular Flag",
            active=True,
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Create a deleted flag (should be excluded)
        await sync_to_async(FeatureFlag.objects.create)(
            team=self.team,
            key="deleted-flag",
            name="Deleted Flag",
            active=True,
            created_by=self.user,
            deleted=True,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        summary = await tool._get_existing_feature_flags_summary()

        # Only the non-deleted flag should be included
        assert "Regular Flag" in summary
        assert "Deleted Flag" not in summary

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_get_existing_feature_flags_summary_limits_to_five(self):
        """Test that the summary is limited to 5 feature flags"""
        tool = self._setup_tool()

        # Create 6 feature flags
        for i in range(6):
            await sync_to_async(FeatureFlag.objects.create)(
                team=self.team,
                key=f"flag-{i+1}",
                name=f"Flag {i+1}",
                active=True,
                created_by=self.user,
                filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
            )

        summary = await tool._get_existing_feature_flags_summary()

        # Count the number of flag entries (lines starting with "- '")
        summary_lines = [line for line in summary.split("\n") if line.strip().startswith("- '")]
        assert len(summary_lines) == 5  # Should be limited to 5

        # Verify it contains flag information
        assert "Flag" in summary
        assert "active" in summary
