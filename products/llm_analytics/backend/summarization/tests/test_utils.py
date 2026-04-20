import pytest

from django.template import TemplateDoesNotExist
from django.utils.safestring import SafeString

from products.llm_analytics.backend.summarization.utils import load_summarization_template


class TestLoadSummarizationTemplate:
    def test_loads_user_template_with_context(self):
        result = load_summarization_template(
            "prompts/user.djt",
            {"text_repr": "L1: Hello World"},
        )
        assert "Analyze and summarize" in result
        assert "L1: Hello World" in result

    def test_loads_system_minimal_template(self):
        result = load_summarization_template("prompts/system_minimal.djt", {})
        assert isinstance(result, str)
        assert len(result) > 0

    def test_loads_system_detailed_template(self):
        result = load_summarization_template("prompts/system_detailed.djt", {})
        assert isinstance(result, str)
        assert len(result) > 0

    def test_returns_plain_str_not_safestring(self):
        result = load_summarization_template(
            "prompts/user.djt",
            {"text_repr": "test content"},
        )
        assert type(result) is str
        assert not isinstance(result, SafeString)

    def test_handles_special_characters_in_context(self):
        result = load_summarization_template(
            "prompts/user.djt",
            {"text_repr": "<script>alert('xss')</script> & \"quotes\""},
        )
        # Since autoescape is False, special chars should remain unescaped
        assert "<script>" in result
        assert "&" in result
        assert '"quotes"' in result

    def test_handles_unicode_in_context(self):
        result = load_summarization_template(
            "prompts/user.djt",
            {"text_repr": "Unicode: \u2192 \u2713 \u2717 \u4e2d\u6587"},
        )
        assert "\u2192" in result
        assert "\u2713" in result
        assert "\u4e2d\u6587" in result

    def test_nonexistent_template_raises(self):
        with pytest.raises(TemplateDoesNotExist):
            load_summarization_template("prompts/nonexistent.djt", {})

    def test_empty_context(self):
        result = load_summarization_template("prompts/system_minimal.djt", {})
        assert isinstance(result, str)

    @pytest.mark.parametrize(
        "template_path",
        [
            "prompts/user.djt",
            "prompts/system_minimal.djt",
            "prompts/system_detailed.djt",
        ],
    )
    def test_all_templates_load_without_error(self, template_path):
        result = load_summarization_template(template_path, {"text_repr": "test"})
        assert isinstance(result, str)
        assert len(result) > 0
