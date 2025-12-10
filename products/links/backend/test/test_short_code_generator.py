from posthog.test.base import BaseTest
from unittest.mock import Mock, patch


class TestShortCodeGenerator(BaseTest):
    @patch("products.links.backend.services.short_code_generator.AnthropicProvider")
    def test_generates_valid_short_code(self, mock_provider):
        """Test that generator produces valid short codes"""
        from products.links.backend.services.short_code_generator import generate_short_code

        # Mock the streaming response
        mock_instance = Mock()
        mock_instance.stream_response.return_value = [
            'data: {"type": "text", "text": "docs-analytics"}\n\n',
        ]
        mock_provider.return_value = mock_instance

        result = generate_short_code("https://posthog.com/docs/analytics")

        self.assertIsNotNone(result)
        self.assertRegex(result, r"^[a-z0-9-]{3,15}$")
        self.assertEqual(result, "docs-analytics")

    @patch("products.links.backend.services.short_code_generator.AnthropicProvider")
    def test_fallback_on_ai_error(self, mock_provider):
        """Test fallback when AI fails"""
        from products.links.backend.services.short_code_generator import generate_short_code

        mock_provider.side_effect = Exception("API error")

        result = generate_short_code("https://example.com")

        self.assertIsNotNone(result)
        self.assertRegex(result, r"^[a-z0-9-]+$")

    @patch("products.links.backend.services.short_code_generator.AnthropicProvider")
    def test_fallback_on_invalid_output(self, mock_provider):
        """Test fallback when AI returns invalid code"""
        from products.links.backend.services.short_code_generator import generate_short_code

        mock_instance = Mock()
        mock_instance.stream_response.return_value = [
            'data: {"type": "text", "text": "INVALID_CODE_WITH_UNDERSCORES!!!"}\n\n',
        ]
        mock_provider.return_value = mock_instance

        result = generate_short_code("https://example.com")

        self.assertIsNotNone(result)
        self.assertRegex(result, r"^[a-z0-9-]+$")

    def test_empty_url_returns_fallback(self):
        """Test empty URL returns fallback"""
        from products.links.backend.services.short_code_generator import generate_short_code

        result = generate_short_code("")

        self.assertIsNotNone(result)
        self.assertRegex(result, r"^[a-z0-9-]+$")
