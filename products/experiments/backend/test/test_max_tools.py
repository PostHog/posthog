from posthog.test.base import APIBaseTest

from posthog.models import Experiment, FeatureFlag

from products.experiments.backend.max_tools import CreateExperimentTool

from ee.hogai.utils.types import AssistantState


class TestCreateExperimentTool(APIBaseTest):
    async def test_create_experiment_minimal(self):
        # Create feature flag first (as the tool expects)
        await FeatureFlag.objects.acreate(
            team=self.team,
            created_by=self.user,
            key="test-experiment-flag",
            name="Test Experiment Flag",
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "name": "Control", "rollout_percentage": 50},
                        {"key": "test", "name": "Test", "rollout_percentage": 50},
                    ]
                },
            },
        )

        tool = await CreateExperimentTool.create_tool_class(
            team=self.team,
            user=self.user,
            tool_call_id="test-call-1",
            state=AssistantState(messages=[]),
        )

        result, artifact = await tool._arun_impl(
            name="Test Experiment",
            feature_flag_key="test-experiment-flag",
        )

        assert "Successfully created" in result
        assert artifact["experiment_name"] == "Test Experiment"
        assert artifact["feature_flag_key"] == "test-experiment-flag"
        assert "/experiments/" in artifact["url"]

        from posthog.sync import database_sync_to_async

        @database_sync_to_async
        def get_experiment():
            return Experiment.objects.select_related("feature_flag").get(name="Test Experiment", team=self.team)

        experiment = await get_experiment()
        assert experiment.description == ""
        assert experiment.type == "product"
        assert experiment.start_date is None  # Draft
        assert experiment.feature_flag.key == "test-experiment-flag"

    async def test_create_experiment_with_description(self):
        # Create feature flag first
        await FeatureFlag.objects.acreate(
            team=self.team,
            created_by=self.user,
            key="checkout-test",
            name="Checkout Test Flag",
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "name": "Control", "rollout_percentage": 50},
                        {"key": "test", "name": "Test", "rollout_percentage": 50},
                    ]
                },
            },
        )

        tool = await CreateExperimentTool.create_tool_class(
            team=self.team,
            user=self.user,
            tool_call_id="test-call-2",
            state=AssistantState(messages=[]),
        )

        result, artifact = await tool._arun_impl(
            name="Checkout Experiment",
            feature_flag_key="checkout-test",
            description="Testing new checkout flow to improve conversion rates",
        )

        assert "Successfully created" in result

        experiment = await Experiment.objects.aget(name="Checkout Experiment", team=self.team)
        assert experiment.description == "Testing new checkout flow to improve conversion rates"

    async def test_create_experiment_web_type(self):
        # Create feature flag first
        await FeatureFlag.objects.acreate(
            team=self.team,
            created_by=self.user,
            key="homepage-redesign",
            name="Homepage Redesign Flag",
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "name": "Control", "rollout_percentage": 50},
                        {"key": "test", "name": "Test", "rollout_percentage": 50},
                    ]
                },
            },
        )

        tool = await CreateExperimentTool.create_tool_class(
            team=self.team,
            user=self.user,
            tool_call_id="test-call-3",
            state=AssistantState(messages=[]),
        )

        result, artifact = await tool._arun_impl(
            name="Homepage Redesign",
            feature_flag_key="homepage-redesign",
            type="web",
        )

        assert "Successfully created" in result
        assert artifact["type"] == "web"

        experiment = await Experiment.objects.aget(name="Homepage Redesign", team=self.team)
        assert experiment.type == "web"

    async def test_create_experiment_duplicate_name(self):
        flag = await FeatureFlag.objects.acreate(
            team=self.team,
            created_by=self.user,
            key="existing-flag",
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "name": "Control", "rollout_percentage": 50},
                        {"key": "test", "name": "Test", "rollout_percentage": 50},
                    ]
                },
            },
        )
        await Experiment.objects.acreate(
            team=self.team,
            created_by=self.user,
            name="Existing Experiment",
            feature_flag=flag,
        )

        # Create another flag for the duplicate attempt
        await FeatureFlag.objects.acreate(
            team=self.team,
            created_by=self.user,
            key="another-flag",
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "name": "Control", "rollout_percentage": 50},
                        {"key": "test", "name": "Test", "rollout_percentage": 50},
                    ]
                },
            },
        )

        tool = await CreateExperimentTool.create_tool_class(
            team=self.team,
            user=self.user,
            tool_call_id="test-call-4",
            state=AssistantState(messages=[]),
        )

        result, artifact = await tool._arun_impl(
            name="Existing Experiment",
            feature_flag_key="another-flag",
        )

        assert "Failed to create" in result
        assert "already exists" in result
        assert artifact.get("error")

    async def test_create_experiment_with_existing_flag(self):
        # Create a feature flag first
        await FeatureFlag.objects.acreate(
            team=self.team,
            created_by=self.user,
            key="existing-flag",
            name="Existing Flag",
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "name": "Control", "rollout_percentage": 50},
                        {"key": "test", "name": "Test", "rollout_percentage": 50},
                    ]
                },
            },
        )

        tool = await CreateExperimentTool.create_tool_class(
            team=self.team,
            user=self.user,
            tool_call_id="test-call-5",
            state=AssistantState(messages=[]),
        )

        result, artifact = await tool._arun_impl(
            name="New Experiment",
            feature_flag_key="existing-flag",
        )

        assert "Successfully created" in result

        from posthog.sync import database_sync_to_async

        @database_sync_to_async
        def get_experiment():
            return Experiment.objects.select_related("feature_flag").get(name="New Experiment", team=self.team)

        experiment = await get_experiment()
        assert experiment.feature_flag.key == "existing-flag"

    async def test_create_experiment_flag_already_used(self):
        # Create a flag and experiment
        flag = await FeatureFlag.objects.acreate(
            team=self.team,
            created_by=self.user,
            key="used-flag",
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "name": "Control", "rollout_percentage": 50},
                        {"key": "test", "name": "Test", "rollout_percentage": 50},
                    ]
                },
            },
        )
        await Experiment.objects.acreate(
            team=self.team,
            created_by=self.user,
            name="First Experiment",
            feature_flag=flag,
        )

        tool = await CreateExperimentTool.create_tool_class(
            team=self.team,
            user=self.user,
            tool_call_id="test-call-6",
            state=AssistantState(messages=[]),
        )

        result, artifact = await tool._arun_impl(
            name="Second Experiment",
            feature_flag_key="used-flag",
        )

        assert "Failed to create" in result
        assert "already used by experiment" in result
        assert artifact.get("error")

    async def test_create_experiment_default_parameters(self):
        # Create feature flag first
        await FeatureFlag.objects.acreate(
            team=self.team,
            created_by=self.user,
            key="param-test",
            name="Param Test Flag",
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "name": "Control", "rollout_percentage": 50},
                        {"key": "test", "name": "Test", "rollout_percentage": 50},
                    ]
                },
            },
        )

        tool = await CreateExperimentTool.create_tool_class(
            team=self.team,
            user=self.user,
            tool_call_id="test-call-7",
            state=AssistantState(messages=[]),
        )

        result, artifact = await tool._arun_impl(
            name="Parameter Test",
            feature_flag_key="param-test",
        )

        assert "Successfully created" in result

        experiment = await Experiment.objects.aget(name="Parameter Test", team=self.team)
        # Variants should come from the feature flag, not hardcoded
        assert experiment.parameters["feature_flag_variants"] == [
            {"key": "control", "name": "Control", "rollout_percentage": 50},
            {"key": "test", "name": "Test", "rollout_percentage": 50},
        ]
        assert experiment.parameters["minimum_detectable_effect"] == 30
        assert experiment.metrics == []
        assert experiment.metrics_secondary == []

    async def test_create_experiment_missing_flag(self):
        """Test error when trying to create experiment with non-existent flag."""
        tool = await CreateExperimentTool.create_tool_class(
            team=self.team,
            user=self.user,
            tool_call_id="test-call-8",
            state=AssistantState(messages=[]),
        )

        result, artifact = await tool._arun_impl(
            name="Test Experiment",
            feature_flag_key="non-existent-flag",
        )

        assert "Failed to create" in result
        assert "does not exist" in result
        assert artifact.get("error")

    async def test_create_experiment_flag_without_variants(self):
        """Test error when flag doesn't have multivariate variants."""
        # Create a flag without multivariate
        await FeatureFlag.objects.acreate(
            team=self.team,
            created_by=self.user,
            key="no-variants-flag",
            name="No Variants Flag",
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        tool = await CreateExperimentTool.create_tool_class(
            team=self.team,
            user=self.user,
            tool_call_id="test-call-9",
            state=AssistantState(messages=[]),
        )

        result, artifact = await tool._arun_impl(
            name="Test Experiment",
            feature_flag_key="no-variants-flag",
        )

        assert "Failed to create" in result
        assert "must have multivariate variants" in result
        assert artifact.get("error")

    async def test_create_experiment_flag_with_one_variant(self):
        """Test error when flag has only 1 variant (need at least 2)."""
        # Create a flag with only 1 variant
        await FeatureFlag.objects.acreate(
            team=self.team,
            created_by=self.user,
            key="one-variant-flag",
            name="One Variant Flag",
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "only_one", "name": "Only Variant", "rollout_percentage": 100},
                    ]
                },
            },
        )

        tool = await CreateExperimentTool.create_tool_class(
            team=self.team,
            user=self.user,
            tool_call_id="test-call-10",
            state=AssistantState(messages=[]),
        )

        result, artifact = await tool._arun_impl(
            name="Test Experiment",
            feature_flag_key="one-variant-flag",
        )

        assert "Failed to create" in result
        assert "at least 2 variants" in result
        assert artifact.get("error")

    async def test_create_experiment_uses_flag_variants(self):
        """Test that experiment uses the actual variants from the feature flag."""
        # Create a flag with 3 custom variants
        await FeatureFlag.objects.acreate(
            team=self.team,
            created_by=self.user,
            key="custom-variants-flag",
            name="Custom Variants Flag",
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "variant_a", "name": "Variant A", "rollout_percentage": 33},
                        {"key": "variant_b", "name": "Variant B", "rollout_percentage": 33},
                        {"key": "variant_c", "name": "Variant C", "rollout_percentage": 34},
                    ]
                },
            },
        )

        tool = await CreateExperimentTool.create_tool_class(
            team=self.team,
            user=self.user,
            tool_call_id="test-call-11",
            state=AssistantState(messages=[]),
        )

        result, artifact = await tool._arun_impl(
            name="Custom Variants Test",
            feature_flag_key="custom-variants-flag",
        )

        assert "Successfully created" in result

        experiment = await Experiment.objects.aget(name="Custom Variants Test", team=self.team)
        assert len(experiment.parameters["feature_flag_variants"]) == 3
        assert experiment.parameters["feature_flag_variants"][0]["key"] == "variant_a"
        assert experiment.parameters["feature_flag_variants"][0]["name"] == "Variant A"
        assert experiment.parameters["feature_flag_variants"][0]["rollout_percentage"] == 33
        assert experiment.parameters["feature_flag_variants"][1]["key"] == "variant_b"
        assert experiment.parameters["feature_flag_variants"][2]["key"] == "variant_c"
