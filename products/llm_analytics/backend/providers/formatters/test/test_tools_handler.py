import pytest

from parameterized import parameterized

from products.llm_analytics.backend.providers.formatters.tools_handler import LLMToolsHandler, ToolFormat


class TestLLMToolsHandler:
    @parameterized.expand(
        [
            (None, None),
            ([], None),
            ({}, None),
        ]
    )
    def test_detect_format_returns_none_for_empty_input(self, tools_data, expected):
        handler = LLMToolsHandler(tools_data)
        assert handler.format == expected

    @parameterized.expand(
        [
            (None, ToolFormat.OPENAI, None),
            (None, ToolFormat.ANTHROPIC, None),
            (None, ToolFormat.GEMINI, None),
            ([], ToolFormat.OPENAI, None),
            ([], ToolFormat.ANTHROPIC, None),
            ([], ToolFormat.GEMINI, None),
        ]
    )
    def test_convert_to_returns_none_for_empty_input(self, tools_data, target_format, expected):
        handler = LLMToolsHandler(tools_data)
        assert handler.convert_to(target_format) == expected

    def test_dictionary_tools_flattened_to_array(self):
        tools_dict = {
            "tool1": {"name": "test1", "input_schema": {"type": "object"}},
            "tool2": {"name": "test2", "input_schema": {"type": "object"}},
        }
        handler = LLMToolsHandler(tools_dict)
        assert len(handler.tools) == 2
        assert handler.tools[0].name == "test1"
        assert handler.tools[1].name == "test2"

    @parameterized.expand(
        [
            (
                [{"type": "function", "function": {"name": "get_weather", "parameters": {"type": "object"}}}],
                ToolFormat.OPENAI,
            ),
            ([{"name": "get_weather", "input_schema": {"type": "object"}}], ToolFormat.ANTHROPIC),
            (
                [{"functionDeclarations": [{"name": "get_weather", "parameters": {"type": "object"}}]}],
                ToolFormat.GEMINI,
            ),
            ([{"name": "get_weather", "parameters": {"type": "object"}}], ToolFormat.GEMINI),
        ]
    )
    def test_format_detection(self, tools_data, expected_format):
        handler = LLMToolsHandler(tools_data)
        assert handler.format == expected_format

    def test_detect_format_raises_error_for_unknown_format(self):
        with pytest.raises(ValueError, match="Unknown tool format"):
            LLMToolsHandler([{"unknown": "format"}])

    def test_detect_format_raises_error_for_invalid_structure(self):
        with pytest.raises(ValueError, match="Each tool must be a dictionary"):
            LLMToolsHandler(["not_a_dict"])

    def test_skip_conversion_when_already_in_target_format(self):
        openai_tools = [
            {"type": "function", "function": {"name": "test", "description": "", "parameters": {"type": "object"}}}
        ]
        handler = LLMToolsHandler(openai_tools)
        result = handler.convert_to(ToolFormat.OPENAI)
        assert result == openai_tools

    def test_anthropic_to_openai_conversion(self):
        anthropic_tools = [
            {
                "name": "get_weather",
                "description": "Get current weather",
                "input_schema": {
                    "type": "object",
                    "properties": {"location": {"type": "string", "description": "City name"}},
                    "required": ["location"],
                },
            }
        ]

        handler = LLMToolsHandler(anthropic_tools)
        result = handler.convert_to(ToolFormat.OPENAI)

        expected = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get current weather",
                    "parameters": {
                        "type": "object",
                        "properties": {"location": {"type": "string", "description": "City name"}},
                        "required": ["location"],
                    },
                },
            }
        ]

        assert result == expected

    def test_openai_to_anthropic_conversion(self):
        openai_tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get current weather",
                    "parameters": {
                        "type": "object",
                        "properties": {"location": {"type": "string", "description": "City name"}},
                        "required": ["location"],
                    },
                },
            }
        ]

        handler = LLMToolsHandler(openai_tools)
        result = handler.convert_to(ToolFormat.ANTHROPIC)

        expected = [
            {
                "name": "get_weather",
                "description": "Get current weather",
                "input_schema": {
                    "type": "object",
                    "properties": {"location": {"type": "string", "description": "City name"}},
                    "required": ["location"],
                },
            }
        ]

        assert result == expected

    def test_openai_to_gemini_conversion(self):
        openai_tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get current weather",
                    "parameters": {
                        "type": "object",
                        "properties": {"location": {"type": "string", "description": "City name"}},
                        "required": ["location"],
                    },
                },
            }
        ]

        handler = LLMToolsHandler(openai_tools)
        result = handler.convert_to(ToolFormat.GEMINI)

        expected = [
            {
                "functionDeclarations": [
                    {
                        "name": "get_weather",
                        "description": "Get current weather",
                        "parameters": {
                            "type": "object",
                            "properties": {"location": {"type": "string", "description": "City name"}},
                            "required": ["location"],
                        },
                    }
                ]
            }
        ]

        assert result == expected

    def test_gemini_wrapped_to_openai_conversion(self):
        gemini_tools = [
            {
                "functionDeclarations": [
                    {
                        "name": "get_weather",
                        "description": "Get current weather",
                        "parameters": {
                            "type": "object",
                            "properties": {"location": {"type": "string", "description": "City name"}},
                            "required": ["location"],
                        },
                    }
                ]
            }
        ]

        handler = LLMToolsHandler(gemini_tools)
        result = handler.convert_to(ToolFormat.OPENAI)

        expected = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get current weather",
                    "parameters": {
                        "type": "object",
                        "properties": {"location": {"type": "string", "description": "City name"}},
                        "required": ["location"],
                    },
                },
            }
        ]

        assert result == expected

    def test_gemini_direct_to_openai_conversion(self):
        gemini_tools = [
            {
                "name": "get_weather",
                "description": "Get current weather",
                "parameters": {
                    "type": "object",
                    "properties": {"location": {"type": "string", "description": "City name"}},
                    "required": ["location"],
                },
            }
        ]

        handler = LLMToolsHandler(gemini_tools)
        result = handler.convert_to(ToolFormat.OPENAI)

        expected = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get current weather",
                    "parameters": {
                        "type": "object",
                        "properties": {"location": {"type": "string", "description": "City name"}},
                        "required": ["location"],
                    },
                },
            }
        ]

        assert result == expected

    def test_anthropic_to_gemini_conversion_via_openai(self):
        anthropic_tools = [
            {
                "name": "get_weather",
                "description": "Get current weather",
                "input_schema": {
                    "type": "object",
                    "properties": {"location": {"type": "string", "description": "City name"}},
                    "required": ["location"],
                },
            }
        ]

        handler = LLMToolsHandler(anthropic_tools)
        result = handler.convert_to(ToolFormat.GEMINI)

        expected = [
            {
                "functionDeclarations": [
                    {
                        "name": "get_weather",
                        "description": "Get current weather",
                        "parameters": {
                            "type": "object",
                            "properties": {"location": {"type": "string", "description": "City name"}},
                            "required": ["location"],
                        },
                    }
                ]
            }
        ]

        assert result == expected

    def test_gemini_to_anthropic_conversion_via_openai(self):
        gemini_tools = [
            {
                "functionDeclarations": [
                    {
                        "name": "get_weather",
                        "description": "Get current weather",
                        "parameters": {
                            "type": "object",
                            "properties": {"location": {"type": "string", "description": "City name"}},
                            "required": ["location"],
                        },
                    }
                ]
            }
        ]

        handler = LLMToolsHandler(gemini_tools)
        result = handler.convert_to(ToolFormat.ANTHROPIC)

        expected = [
            {
                "name": "get_weather",
                "description": "Get current weather",
                "input_schema": {
                    "type": "object",
                    "properties": {"location": {"type": "string", "description": "City name"}},
                    "required": ["location"],
                },
            }
        ]

        assert result == expected

    def test_multiple_tools_conversion(self):
        anthropic_tools = [
            {
                "name": "get_weather",
                "description": "Get current weather",
                "input_schema": {"type": "object", "properties": {"location": {"type": "string"}}},
            },
            {
                "name": "send_email",
                "description": "Send an email",
                "input_schema": {
                    "type": "object",
                    "properties": {"to": {"type": "string"}, "subject": {"type": "string"}},
                },
            },
        ]

        handler = LLMToolsHandler(anthropic_tools)
        result = handler.convert_to(ToolFormat.OPENAI)

        assert len(result) == 2
        assert result[0]["function"]["name"] == "get_weather"
        assert result[1]["function"]["name"] == "send_email"

    def test_tools_with_missing_description_handled_gracefully(self):
        anthropic_tools = [{"name": "get_weather", "input_schema": {"type": "object"}}]

        handler = LLMToolsHandler(anthropic_tools)
        result = handler.convert_to(ToolFormat.OPENAI)

        assert result[0]["function"]["description"] == ""

    def test_tools_with_missing_parameters_handled_gracefully(self):
        gemini_tools = [{"name": "get_weather", "description": "Get current weather"}]

        handler = LLMToolsHandler(gemini_tools)
        result = handler.convert_to(ToolFormat.OPENAI)

        assert result[0]["function"]["parameters"] == {"type": "object", "properties": {}}

    def test_tools_property_exposed(self):
        tools_data = [{"name": "test", "input_schema": {"type": "object"}}]
        handler = LLMToolsHandler(tools_data)
        assert len(handler.tools) == 1
        assert handler.tools[0].name == "test"

    def test_tools_none_property_exposed(self):
        handler = LLMToolsHandler(None)
        assert handler.tools is None

    def test_openai_to_gemini_cleans_schema_fields(self):
        openai_tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get current weather",
                    "parameters": {
                        "$schema": "http://json-schema.org/draft-07/schema#",
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "location": {"type": "string", "description": "City name", "additionalProperties": False}
                        },
                        "required": ["location"],
                    },
                },
            }
        ]

        handler = LLMToolsHandler(openai_tools)
        result = handler.convert_to(ToolFormat.GEMINI)

        # Check that forbidden fields are removed
        parameters = result[0]["functionDeclarations"][0]["parameters"]
        assert "$schema" not in parameters
        assert "additionalProperties" not in parameters
        assert "additionalProperties" not in parameters["properties"]["location"]

        # Check that allowed fields remain
        assert parameters["type"] == "object"
        assert parameters["properties"]["location"]["type"] == "string"
        assert parameters["required"] == ["location"]
