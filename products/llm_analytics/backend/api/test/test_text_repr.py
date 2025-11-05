"""
Tests for text_repr.py - Django REST API endpoint.

Tests cover request validation, response format, error handling, and integration
with formatters for different event types.
"""

from posthog.test.base import APIBaseTest

from rest_framework import status


class TestTextReprAPI(APIBaseTest):
    """Test text repr API endpoints."""

    def test_unauthenticated_user_cannot_access_text_repr(self):
        """Should require authentication to access text repr endpoints."""
        self.client.logout()
        response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/text_repr/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_stringify_generation_event(self):
        """Should stringify $ai_generation event."""
        request_data = {
            "event_type": "$ai_generation",
            "data": {
                "id": "gen123",
                "event": "$ai_generation",
                "properties": {
                    "$ai_input": [{"role": "user", "content": "Hello"}],
                    "$ai_output_choices": [{"message": {"role": "assistant", "content": "Hi there"}}],
                },
            },
            "options": {"truncated": True, "include_markers": True},
        }

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/text_repr/",
            request_data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data

        self.assertIn("text", data)
        self.assertIn("metadata", data)
        self.assertIn("INPUT:", data["text"])
        self.assertIn("OUTPUT:", data["text"])
        self.assertIn("Hello", data["text"])
        self.assertIn("Hi there", data["text"])

        # Check metadata
        self.assertEqual(data["metadata"]["event_type"], "$ai_generation")
        self.assertEqual(data["metadata"]["event_id"], "gen123")
        self.assertEqual(data["metadata"]["rendering"], "detailed")
        self.assertGreater(data["metadata"]["char_count"], 0)
        self.assertIsInstance(data["metadata"]["truncated"], bool)

    def test_stringify_span_event(self):
        """Should stringify $ai_span event."""
        request_data = {
            "event_type": "$ai_span",
            "data": {
                "id": "span123",
                "event": "$ai_span",
                "properties": {
                    "$ai_span_name": "test-span",
                    "$ai_input_state": {"query": "test"},
                    "$ai_output_state": {"result": "success"},
                },
            },
        }

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/text_repr/",
            request_data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data

        self.assertIn("text", data)
        self.assertIn("TEST-SPAN", data["text"])
        self.assertIn("INPUT STATE:", data["text"])
        self.assertIn("OUTPUT STATE:", data["text"])

    def test_stringify_trace(self):
        """Should stringify $ai_trace with hierarchy."""
        request_data = {
            "event_type": "$ai_trace",
            "data": {
                "trace": {
                    "properties": {
                        "$ai_trace_id": "trace123",
                        "$ai_span_name": "my-trace",
                    }
                },
                "hierarchy": [
                    {
                        "event": {
                            "id": "gen1",
                            "event": "$ai_generation",
                            "properties": {"$ai_span_name": "generation"},
                        },
                        "children": [],
                    }
                ],
            },
            "options": {"include_markers": True},
        }

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/text_repr/",
            request_data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data

        self.assertIn("text", data)
        self.assertIn("MY-TRACE", data["text"])
        self.assertIn("TRACE HIERARCHY:", data["text"])
        self.assertIn("[GEN]", data["text"])
        self.assertEqual(data["metadata"]["trace_id"], "trace123")

    def test_missing_event_type(self):
        """Should return 400 for missing event_type."""
        request_data = {"data": {}}

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/text_repr/",
            request_data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("event_type", str(response.data).lower())

    def test_missing_data(self):
        """Should return 400 for missing data."""
        request_data = {"event_type": "$ai_generation"}

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/text_repr/",
            request_data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("data", str(response.data).lower())

    def test_default_options(self):
        """Should use default options when not provided."""
        request_data = {
            "event_type": "$ai_generation",
            "data": {
                "id": "gen123",
                "event": "$ai_generation",
                "properties": {
                    "$ai_input": "Test input",
                },
            },
        }

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/text_repr/",
            request_data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should succeed with defaults

    def test_truncated_option(self):
        """Should respect truncated option."""
        long_content = "a" * 5000
        request_data = {
            "event_type": "$ai_generation",
            "data": {
                "id": "gen123",
                "event": "$ai_generation",
                "properties": {
                    "$ai_input": long_content,
                },
            },
            "options": {"truncated": True, "truncate_buffer": 1000},
        }

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/text_repr/",
            request_data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data
        # Should have truncation marker
        self.assertTrue("TRUNCATED" in data["text"] or "truncated" in data["text"].lower())

    def test_include_markers_option(self):
        """Should respect include_markers option."""
        long_content = "a" * 5000
        request_data = {
            "event_type": "$ai_generation",
            "data": {
                "id": "gen123",
                "event": "$ai_generation",
                "properties": {
                    "$ai_input": long_content,
                },
            },
            "options": {"truncated": True, "include_markers": False},
        }

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/text_repr/",
            request_data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data
        # Should not have interactive markers
        self.assertNotIn("<<<TRUNCATED|", data["text"])
        self.assertIn("chars truncated", data["text"])

    def test_collapsed_option(self):
        """Should respect collapsed option for traces."""
        request_data = {
            "event_type": "$ai_trace",
            "data": {
                "trace": {
                    "properties": {
                        "$ai_span_name": "test",
                    }
                },
                "hierarchy": [
                    {
                        "event": {
                            "id": "gen1",
                            "event": "$ai_generation",
                            "properties": {"$ai_span_name": "gen"},
                        },
                        "children": [],
                    }
                ],
            },
            "options": {"collapsed": True},
        }

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/text_repr/",
            request_data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data
        # Should show tree but not expandable markers
        self.assertIn("[GEN]", data["text"])
        self.assertNotIn("GEN_EXPANDABLE", data["text"])

    def test_team_isolation(self):
        """Should enforce team isolation."""
        # Create another team
        from posthog.models import Organization, Team

        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")

        request_data = {
            "event_type": "$ai_generation",
            "data": {"id": "gen123", "event": "$ai_generation", "properties": {}},
        }

        # Try to access other team's endpoint
        response = self.client.post(
            f"/api/environments/{other_team.id}/llm_analytics/text_repr/",
            request_data,
            format="json",
        )

        # Should be forbidden
        self.assertIn(response.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])


class TestProviderFormats(APIBaseTest):
    """Test different LLM provider formats."""

    def test_openai_format(self):
        """Should handle OpenAI message format."""
        request_data = {
            "event_type": "$ai_generation",
            "data": {
                "id": "gen123",
                "event": "$ai_generation",
                "properties": {
                    "$ai_input": [{"role": "user", "content": "Test"}],
                    "$ai_output_choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "Response",
                                "tool_calls": [
                                    {
                                        "function": {
                                            "name": "test_func",
                                            "arguments": '{"arg": "val"}',
                                        }
                                    }
                                ],
                            }
                        }
                    ],
                },
            },
        }

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/text_repr/",
            request_data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data
        self.assertIn("Test", data["text"])
        self.assertIn("Response", data["text"])
        self.assertIn("test_func", data["text"])

    def test_anthropic_format(self):
        """Should handle Anthropic message format."""
        request_data = {
            "event_type": "$ai_generation",
            "data": {
                "id": "gen123",
                "event": "$ai_generation",
                "properties": {
                    "$ai_input": [{"role": "user", "content": "Test"}],
                    "$ai_output_choices": [
                        {
                            "role": "assistant",
                            "content": [
                                {"type": "text", "text": "I'll help"},
                                {
                                    "type": "function",
                                    "function": {
                                        "name": "get_weather",
                                        "arguments": {"location": "Dublin"},
                                    },
                                },
                            ],
                        }
                    ],
                },
            },
        }

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/text_repr/",
            request_data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data
        self.assertIn("I'll help", data["text"])
        self.assertIn("get_weather", data["text"])
        self.assertIn("Dublin", data["text"])


class TestEdgeCases(APIBaseTest):
    """Test edge cases and error handling."""

    def test_empty_properties(self):
        """Should handle empty properties."""
        request_data = {
            "event_type": "$ai_generation",
            "data": {
                "id": "gen123",
                "event": "$ai_generation",
                "properties": {},
            },
        }

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/text_repr/",
            request_data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should not crash

    def test_malformed_json(self):
        """Should handle malformed JSON gracefully."""
        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/text_repr/",
            "not json",
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_very_long_content(self):
        """Should handle very long content."""
        very_long = "a" * 100000
        request_data = {
            "event_type": "$ai_generation",
            "data": {
                "id": "gen123",
                "event": "$ai_generation",
                "properties": {
                    "$ai_input": very_long,
                },
            },
            "options": {"max_length": 50000},
        }

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/text_repr/",
            request_data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data
        # Should be truncated to max_length
        self.assertLessEqual(data["metadata"]["char_count"], 50000 + 100)  # Allow for truncation message
        self.assertEqual(data["metadata"]["truncated"], True)

    def test_default_max_length(self):
        """Should use 3MB default max_length when not specified."""
        # Test content under 3MB - should NOT truncate at max_length level
        under_limit = "a" * 2500000  # 2.5MB
        request_data = {
            "event_type": "$ai_generation",
            "data": {
                "id": "gen123",
                "event": "$ai_generation",
                "properties": {
                    "$ai_input": under_limit,
                },
            },
            "options": {"truncated": False},  # Disable internal truncation to test max_length
        }

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/text_repr/",
            request_data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data
        self.assertEqual(data["metadata"]["truncated"], False)
        self.assertGreater(data["metadata"]["char_count"], 2500000)

        # Test content over 3MB - should truncate at max_length level
        over_limit = "a" * 3500000  # 3.5MB
        request_data["data"]["properties"]["$ai_input"] = over_limit
        request_data["options"] = {"truncated": False}  # Disable internal truncation to test max_length

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/text_repr/",
            request_data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data
        self.assertEqual(data["metadata"]["truncated"], True)
        self.assertLessEqual(data["metadata"]["char_count"], 4000000 + 200)

    def test_unicode_content(self):
        """Should handle Unicode content correctly."""
        request_data = {
            "event_type": "$ai_generation",
            "data": {
                "id": "gen123",
                "event": "$ai_generation",
                "properties": {
                    "$ai_input": "Hello 世界 🌍 émojis",
                },
            },
        }

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/text_repr/",
            request_data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data
        self.assertIn("世界", data["text"])
        self.assertIn("🌍", data["text"])
        self.assertIn("émojis", data["text"])

    def test_null_values(self):
        """Should handle null values gracefully."""
        request_data = {
            "event_type": "$ai_generation",
            "data": {
                "id": "gen123",
                "event": "$ai_generation",
                "properties": {
                    "$ai_input": None,
                    "$ai_output": None,
                },
            },
        }

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/text_repr/",
            request_data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should not crash

    def test_complex_nested_structures(self):
        """Should handle complex nested structures."""
        request_data = {
            "event_type": "$ai_span",
            "data": {
                "id": "span123",
                "event": "$ai_span",
                "properties": {
                    "$ai_span_name": "test",
                    "$ai_input_state": {
                        "level1": {"level2": {"level3": {"level4": "deep"}}},
                    },
                },
            },
        }

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/text_repr/",
            request_data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data
        self.assertIn("deep", data["text"])

    def test_available_tools_dictionary_format(self):
        """Should handle available tools in dictionary format."""
        request_data = {
            "event_type": "$ai_generation",
            "data": {
                "id": "gen123",
                "event": "$ai_generation",
                "properties": {
                    "$ai_tools": {
                        "lov-view": {
                            "name": "lov-view",
                            "description": "Use this tool to read the contents of a file.",
                            "input_schema": {
                                "type": "object",
                                "properties": {
                                    "file_path": {"type": "string"},
                                    "lines": {"type": "string"},
                                },
                                "required": ["file_path"],
                            },
                        },
                        "supabase--migration": {
                            "name": "supabase--migration",
                            "description": "Create a Supabase migration file.",
                            "input_schema": {
                                "type": "object",
                                "properties": {
                                    "migration_name": {"type": "string"},
                                },
                                "required": ["migration_name"],
                            },
                        },
                    },
                    "$ai_input": "Test input",
                },
            },
        }

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/text_repr/",
            request_data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data
        # Should show available tools section
        self.assertIn("AVAILABLE TOOLS: 2", data["text"])
        self.assertIn("lov-view(file_path: string, lines?: string)", data["text"])
        self.assertIn("Use this tool to read the contents of a file.", data["text"])
        self.assertIn("supabase--migration(migration_name: string)", data["text"])
        self.assertIn("Create a Supabase migration file.", data["text"])

    def test_available_tools_array_format(self):
        """Should handle available tools in array format."""
        request_data = {
            "event_type": "$ai_generation",
            "data": {
                "id": "gen123",
                "event": "$ai_generation",
                "properties": {
                    "$ai_tools": [
                        {
                            "type": "function",
                            "function": {
                                "name": "get_weather",
                                "description": "Get current weather for a location.",
                                "parameters": {
                                    "type": "object",
                                    "properties": {
                                        "location": {"type": "string"},
                                    },
                                    "required": ["location"],
                                },
                            },
                        }
                    ],
                    "$ai_input": "Test input",
                },
            },
        }

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/text_repr/",
            request_data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data
        # Should show available tools section
        self.assertIn("AVAILABLE TOOLS: 1", data["text"])
        self.assertIn("get_weather(location: string)", data["text"])
        self.assertIn("Get current weather for a location.", data["text"])

    def test_long_tools_list_collapsed(self):
        """Should collapse long tool lists (>5 tools) with expandable marker."""
        # Create 10 tools
        tools = {}
        for i in range(10):
            tools[f"tool{i}"] = {
                "name": f"tool{i}",
                "description": f"Tool number {i} description.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "param": {"type": "string"},
                    },
                    "required": ["param"],
                },
            }

        request_data = {
            "event_type": "$ai_generation",
            "data": {
                "id": "gen123",
                "event": "$ai_generation",
                "properties": {
                    "$ai_tools": tools,
                    "$ai_input": "Test input",
                },
            },
            "options": {"include_markers": True},
        }

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/text_repr/",
            request_data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data
        # Should show collapsed marker
        self.assertIn("<<<TOOLS_EXPANDABLE|", data["text"])
        self.assertIn("AVAILABLE TOOLS: 10", data["text"])
        # Should not show individual tools in main output
        self.assertNotIn("tool0(param: string)", data["text"])

    def test_long_tools_list_collapsed_without_markers(self):
        """Should collapse long tool lists with plain text when include_markers=False."""
        # Create 10 tools
        tools = {}
        for i in range(10):
            tools[f"tool{i}"] = {
                "name": f"tool{i}",
                "description": f"Tool number {i} description.",
            }

        request_data = {
            "event_type": "$ai_generation",
            "data": {
                "id": "gen123",
                "event": "$ai_generation",
                "properties": {
                    "$ai_tools": tools,
                    "$ai_input": "Test input",
                },
            },
            "options": {"include_markers": False},
        }

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/text_repr/",
            request_data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data
        # Should show plain text indicator
        self.assertIn("[+] AVAILABLE TOOLS: 10", data["text"])
        # Should not have interactive marker
        self.assertNotIn("<<<TOOLS_EXPANDABLE|", data["text"])
