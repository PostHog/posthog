from products.llm_analytics.backend.providers.formatters.tools_handler import LLMToolsHandler, ToolFormat


class TestFormatConversions:
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
        assert result is not None
        parameters = result[0]["functionDeclarations"][0]["parameters"]
        assert "$schema" not in parameters
        assert "additionalProperties" not in parameters
        assert "additionalProperties" not in parameters["properties"]["location"]

        # Check that allowed fields remain
        assert parameters["type"] == "object"
        assert parameters["properties"]["location"]["type"] == "string"
        assert parameters["required"] == ["location"]
