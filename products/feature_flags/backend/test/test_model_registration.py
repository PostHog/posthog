from django.test import SimpleTestCase

from products.feature_flags.backend.models import FeatureFlag, FeatureFlagEvaluationContext


class TestFeatureFlagsModelRegistration(SimpleTestCase):
    def test_feature_flag_evaluation_context_reverse_relation_is_registered(self) -> None:
        relation = FeatureFlag._meta.get_field("flag_evaluation_contexts")

        assert relation.related_model is FeatureFlagEvaluationContext
