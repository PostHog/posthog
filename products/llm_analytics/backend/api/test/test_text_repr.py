"""
Tests for text_repr.py - Django REST API endpoint.

Tests cover request validation, response format, error handling, and integration
with formatters for different event types.
"""

from typing import Any

from posthog.test.base import APIBaseTest

from rest_framework import status


class TestTextReprAPI(APIBaseTest):
    """Test text repr API endpoints."""

    def test_unauthenticated_user_cannot_access_text_repr(self):
        """Should require authentication to access text repr endpoints."""
        self.client.logout()
        response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/text_repr/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

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

        assert response.status_code == status.HTTP_200_OK
        data = response.data

        assert "text" in data
        assert "metadata" in data
        assert "INPUT:" in data["text"]
        assert "OUTPUT:" in data["text"]
        assert "Hello" in data["text"]
        assert "Hi there" in data["text"]

        # Check metadata
        assert data["metadata"]["event_type"] == "$ai_generation"
        assert data["metadata"]["event_id"] == "gen123"
        assert data["metadata"]["rendering"] == "detailed"
        assert data["metadata"]["char_count"] > 0
        assert isinstance(data["metadata"]["truncated"], bool)

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

        assert response.status_code == status.HTTP_200_OK
        data = response.data

        assert "text" in data
        assert "TEST-SPAN" in data["text"]
        assert "INPUT STATE:" in data["text"]
        assert "OUTPUT STATE:" in data["text"]

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

        assert response.status_code == status.HTTP_200_OK
        data = response.data

        assert "text" in data
        assert "MY-TRACE" in data["text"]
        assert "TRACE HIERARCHY:" in data["text"]
        assert "[GEN]" in data["text"]
        assert data["metadata"]["trace_id"] == "trace123"

    def test_missing_event_type(self):
        """Should return 400 for missing event_type."""
        request_data: dict[str, Any] = {"data": {}}

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/text_repr/",
            request_data,
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "event_type" in str(response.data).lower()

    def test_missing_data(self):
        """Should return 400 for missing data."""
        request_data = {"event_type": "$ai_generation"}

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/text_repr/",
            request_data,
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "data" in str(response.data).lower()

    def test_missing_event_id(self):
        """Should return 400 when event ID is missing to prevent cache collisions."""
        request_data = {
            "event_type": "$ai_generation",
            "data": {
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

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "id" in str(response.data).lower()

    def test_missing_trace_id(self):
        """Should return 400 when trace ID is missing to prevent cache collisions."""
        request_data = {
            "event_type": "$ai_trace",
            "data": {
                "trace": {
                    "properties": {
                        "$ai_span_name": "test",
                    }
                },
                "hierarchy": [],
            },
        }

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/text_repr/",
            request_data,
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "id" in str(response.data).lower()

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

        assert response.status_code == status.HTTP_200_OK
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

        assert response.status_code == status.HTTP_200_OK
        data = response.data
        # Should have truncation marker
        assert "TRUNCATED" in data["text"] or "truncated" in data["text"].lower()

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

        assert response.status_code == status.HTTP_200_OK
        data = response.data
        # Should not have interactive markers
        assert "<<<TRUNCATED|" not in data["text"]
        assert "chars truncated" in data["text"]

    def test_collapsed_option(self):
        """Should respect collapsed option for traces."""
        request_data = {
            "event_type": "$ai_trace",
            "data": {
                "trace": {
                    "id": "trace1",
                    "properties": {
                        "$ai_span_name": "test",
                    },
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

        assert response.status_code == status.HTTP_200_OK
        data = response.data
        # Should show tree but not expandable markers
        assert "[GEN]" in data["text"]
        assert "GEN_EXPANDABLE" not in data["text"]

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
        assert response.status_code in [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND]


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

        assert response.status_code == status.HTTP_200_OK
        data = response.data
        assert "Test" in data["text"]
        assert "Response" in data["text"]
        assert "test_func" in data["text"]

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

        assert response.status_code == status.HTTP_200_OK
        data = response.data
        assert "I'll help" in data["text"]
        assert "get_weather" in data["text"]
        assert "Dublin" in data["text"]


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

        assert response.status_code == status.HTTP_200_OK
        # Should not crash

    def test_malformed_json(self):
        """Should handle malformed JSON gracefully."""
        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/text_repr/",
            "not json",
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_very_long_content(self):
        """Should handle very long multi-line content via uniform sampling."""
        # Create realistic multi-line content (like a long conversation)
        lines = [f"Line {i}: " + "x" * 100 for i in range(1000)]
        very_long = "\n".join(lines)  # ~110KB of multi-line content
        request_data = {
            "event_type": "$ai_generation",
            "data": {
                "id": "gen123",
                "event": "$ai_generation",
                "properties": {
                    "$ai_input": very_long,
                },
            },
            "options": {"max_length": 50000, "truncated": False},
        }

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/text_repr/",
            request_data,
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.data
        # Should be truncated to approximately max_length via uniform sampling
        assert data["metadata"]["char_count"] <= 55000  # Allow some overhead
        assert data["metadata"]["truncated"]

    def test_default_max_length(self):
        """Should use 2MB default max_length when not specified."""
        # Create realistic multi-line content (like a long conversation)
        # Each line is ~150 chars, so 10000 lines = ~1.5MB
        under_limit_lines = [f"Message {i}: " + "x" * 140 for i in range(10000)]
        under_limit = "\n".join(under_limit_lines)

        request_data = {
            "event_type": "$ai_generation",
            "data": {
                "id": "gen_under_limit",
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

        assert response.status_code == status.HTTP_200_OK
        data = response.data
        assert not data["metadata"]["truncated"]
        assert data["metadata"]["char_count"] > 1500000

        # Test content over 2MB - should truncate at max_length level
        # Each line is ~150 chars, so 17000 lines = ~2.5MB
        over_limit_lines = [f"Message {i}: " + "x" * 140 for i in range(17000)]
        over_limit = "\n".join(over_limit_lines)
        request_data["data"]["id"] = "gen_over_limit"  # type: ignore[index]  # Use different ID to avoid cache
        request_data["data"]["properties"]["$ai_input"] = over_limit  # type: ignore[index]
        request_data["options"] = {"truncated": False}  # Disable internal truncation to test max_length

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/text_repr/",
            request_data,
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.data
        assert data["metadata"]["truncated"]
        assert data["metadata"]["char_count"] <= 2100000  # Allow some overhead for sampling

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

        assert response.status_code == status.HTTP_200_OK
        data = response.data
        assert "世界" in data["text"]
        assert "🌍" in data["text"]
        assert "émojis" in data["text"]

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

        assert response.status_code == status.HTTP_200_OK
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

        assert response.status_code == status.HTTP_200_OK
        data = response.data
        assert "deep" in data["text"]

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

        assert response.status_code == status.HTTP_200_OK
        data = response.data
        # Should show available tools section
        assert "AVAILABLE TOOLS: 2" in data["text"]
        assert "lov-view(file_path: string, lines?: string)" in data["text"]
        assert "Use this tool to read the contents of a file." in data["text"]
        assert "supabase--migration(migration_name: string)" in data["text"]
        assert "Create a Supabase migration file." in data["text"]

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

        assert response.status_code == status.HTTP_200_OK
        data = response.data
        # Should show available tools section
        assert "AVAILABLE TOOLS: 1" in data["text"]
        assert "get_weather(location: string)" in data["text"]
        assert "Get current weather for a location." in data["text"]

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

        assert response.status_code == status.HTTP_200_OK
        data = response.data
        # Should show collapsed marker
        assert "<<<TOOLS_EXPANDABLE|" in data["text"]
        assert "AVAILABLE TOOLS: 10" in data["text"]
        # Should not show individual tools in main output
        assert "tool0(param: string)" not in data["text"]

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

        assert response.status_code == status.HTTP_200_OK
        data = response.data
        # Should show plain text indicator
        assert "[+] AVAILABLE TOOLS: 10" in data["text"]
        # Should not have interactive marker
        assert "<<<TOOLS_EXPANDABLE|" not in data["text"]


class TestCachingBehavior(APIBaseTest):
    """Test caching behavior of text repr API."""

    def test_caching_identical_requests(self):
        """Should cache and return cached result for identical requests."""
        from django.core.cache import cache

        request_data = {
            "event_type": "$ai_generation",
            "data": {
                "id": "gen_cache_test",
                "event": "$ai_generation",
                "properties": {
                    "$ai_input": "Test input for caching",
                },
            },
            "options": {"truncated": True},
        }

        # First request - should generate and cache
        response1 = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/text_repr/",
            request_data,
            format="json",
        )

        assert response1.status_code == status.HTTP_200_OK
        first_text = response1.data["text"]
        first_metadata = response1.data["metadata"]

        # Verify result was cached by checking cache directly
        from products.llm_analytics.backend.api.text_repr import LLMAnalyticsTextReprViewSet

        viewset = LLMAnalyticsTextReprViewSet()
        viewset.team_id = self.team.id
        cache_key = viewset._get_cache_key("$ai_generation", "gen_cache_test", {"truncated": True})
        cached_result = cache.get(cache_key)
        assert cached_result is not None
        assert cached_result["text"] == first_text

        # Second identical request - should use cache and return same result
        response2 = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/text_repr/",
            request_data,
            format="json",
        )

        assert response2.status_code == status.HTTP_200_OK
        assert response2.data["text"] == first_text
        assert response2.data["metadata"]["char_count"] == first_metadata["char_count"]

    def test_cache_key_differs_by_options(self):
        """Should use different cache keys for different options."""
        from django.core.cache import cache

        base_request = {
            "event_type": "$ai_generation",
            "data": {
                "id": "gen_options_test",
                "event": "$ai_generation",
                "properties": {
                    "$ai_input": "a" * 5000,  # Long enough to trigger truncation
                },
            },
        }

        # Request with truncated=True
        request1 = {**base_request, "options": {"truncated": True}}
        response1 = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/text_repr/",
            request1,
            format="json",
        )
        assert response1.status_code == status.HTTP_200_OK
        text_with_truncation = response1.data["text"]

        # Request with truncated=False - should NOT use cache from request1
        request2 = {**base_request, "options": {"truncated": False}}
        response2 = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/text_repr/",
            request2,
            format="json",
        )
        assert response2.status_code == status.HTTP_200_OK
        text_without_truncation = response2.data["text"]

        # Results should be different (truncation affects output)
        assert text_with_truncation != text_without_truncation

        # Verify both are cached with different keys
        from products.llm_analytics.backend.api.text_repr import LLMAnalyticsTextReprViewSet

        viewset = LLMAnalyticsTextReprViewSet()
        viewset.team_id = self.team.id

        cache_key1 = viewset._get_cache_key("$ai_generation", "gen_options_test", {"truncated": True})
        cache_key2 = viewset._get_cache_key("$ai_generation", "gen_options_test", {"truncated": False})

        assert cache_key1 != cache_key2
        assert cache.get(cache_key1) is not None
        assert cache.get(cache_key2) is not None

    def test_cache_key_differs_by_event_id(self):
        """Should use different cache keys for different event IDs."""
        from django.core.cache import cache

        # First event
        request1 = {
            "event_type": "$ai_generation",
            "data": {
                "id": "gen_id_test_1",
                "event": "$ai_generation",
                "properties": {"$ai_input": "Test"},
            },
        }

        response1 = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/text_repr/",
            request1,
            format="json",
        )
        assert response1.status_code == status.HTTP_200_OK

        # Different event ID - should NOT use cache
        request2 = {
            "event_type": "$ai_generation",
            "data": {
                "id": "gen_id_test_2",  # Different ID
                "event": "$ai_generation",
                "properties": {"$ai_input": "Test"},
            },
        }

        response2 = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/text_repr/",
            request2,
            format="json",
        )
        assert response2.status_code == status.HTTP_200_OK

        # Verify different cache keys were used
        from products.llm_analytics.backend.api.text_repr import LLMAnalyticsTextReprViewSet

        viewset = LLMAnalyticsTextReprViewSet()
        viewset.team_id = self.team.id

        cache_key1 = viewset._get_cache_key("$ai_generation", "gen_id_test_1", {})
        cache_key2 = viewset._get_cache_key("$ai_generation", "gen_id_test_2", {})

        assert cache_key1 != cache_key2
        assert cache.get(cache_key1) is not None
        assert cache.get(cache_key2) is not None

    def test_cache_isolation_by_team(self):
        """Should isolate cache by team."""
        from posthog.models import Team

        # Create another team in same org
        other_team = Team.objects.create(organization=self.organization, name="Other Team")

        request_data = {
            "event_type": "$ai_generation",
            "data": {
                "id": "gen_team_test",
                "event": "$ai_generation",
                "properties": {"$ai_input": "Test"},
            },
        }

        # Request from first team
        response1 = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/text_repr/",
            request_data,
            format="json",
        )
        assert response1.status_code == status.HTTP_200_OK

        # Verify cache key includes team ID
        from products.llm_analytics.backend.api.text_repr import LLMAnalyticsTextReprViewSet

        viewset1 = LLMAnalyticsTextReprViewSet()
        viewset1.team_id = self.team.id
        cache_key1 = viewset1._get_cache_key("$ai_generation", "gen_team_test", {})

        viewset2 = LLMAnalyticsTextReprViewSet()
        viewset2.team_id = other_team.id
        cache_key2 = viewset2._get_cache_key("$ai_generation", "gen_team_test", {})

        # Cache keys should be different due to different team IDs
        assert cache_key1 != cache_key2
        assert str(self.team.id) in cache_key1
        assert str(other_team.id) in cache_key2

    def test_cache_respects_trace_id(self):
        """Should cache traces separately by trace ID."""
        from django.core.cache import cache

        # First trace
        request1 = {
            "event_type": "$ai_trace",
            "data": {
                "trace": {
                    "id": "trace_cache_1",
                    "properties": {"$ai_span_name": "test"},
                },
                "hierarchy": [],
            },
        }

        response1 = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/text_repr/",
            request1,
            format="json",
        )
        assert response1.status_code == status.HTTP_200_OK

        # Different trace ID - should NOT use cache
        request2 = {
            "event_type": "$ai_trace",
            "data": {
                "trace": {
                    "id": "trace_cache_2",  # Different trace ID
                    "properties": {"$ai_span_name": "test"},
                },
                "hierarchy": [],
            },
        }

        response2 = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/text_repr/",
            request2,
            format="json",
        )
        assert response2.status_code == status.HTTP_200_OK

        # Verify different cache keys were used
        from products.llm_analytics.backend.api.text_repr import LLMAnalyticsTextReprViewSet

        viewset = LLMAnalyticsTextReprViewSet()
        viewset.team_id = self.team.id

        cache_key1 = viewset._get_cache_key("$ai_trace", "trace_cache_1", {})
        cache_key2 = viewset._get_cache_key("$ai_trace", "trace_cache_2", {})

        assert cache_key1 != cache_key2
        assert cache.get(cache_key1) is not None
        assert cache.get(cache_key2) is not None
