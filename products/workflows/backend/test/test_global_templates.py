from django.test import SimpleTestCase

from products.workflows.backend.templates import clear_template_cache, load_global_templates


class TestGlobalTemplateCache(SimpleTestCase):
    def setUp(self):
        super().setUp()
        clear_template_cache()
        self.addCleanup(clear_template_cache)

    def test_caller_cannot_reorder_the_shared_cache(self):
        loaded = load_global_templates()
        assert len(loaded) > 1
        expected_ids = [template["id"] for template in loaded]

        loaded.reverse()

        assert [template["id"] for template in load_global_templates()] == expected_ids
