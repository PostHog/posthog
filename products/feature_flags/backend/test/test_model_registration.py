from django.test import SimpleTestCase

from products.feature_flags.backend.models import FeatureFlag, FeatureFlagEvaluationContext


class TestFeatureFlagsModelRegistration(SimpleTestCase):
    def test_feature_flag_evaluation_context_reverse_relation_is_registered(self) -> None:
        # get_feature_flags() annotates on the `flag_evaluation_contexts` reverse relation, which
        # only resolves once FeatureFlagEvaluationContext is registered at app load. Look it up via
        # related_objects rather than _meta.get_field("flag_evaluation_contexts"): django-stubs can't
        # see reverse relations declared via related_name on another model and rejects the literal.
        relations = {rel.name: rel.related_model for rel in FeatureFlag._meta.related_objects}

        assert relations.get("flag_evaluation_contexts") is FeatureFlagEvaluationContext
