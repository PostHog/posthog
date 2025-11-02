"""
Tests for text_repr.py - Django REST API endpoint.

Tests cover request validation, response format, error handling, and integration
with formatters for different event types.
"""

from posthog.test.base import APIBaseTest

from rest_framework.test import APIClient


class TestTextReprAPI(APIBaseTest):
    """Test text repr API endpoints."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_login(self.user)

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
            f"/api/projects/{self.team.id}/llm_analytics/text_repr/",
            request_data,
            format="json",
        )

        assert response.status_code == 200
        data = response.json()

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
            f"/api/projects/{self.team.id}/llm_analytics/text_repr/",
            request_data,
            format="json",
        )

        assert response.status_code == 200
        data = response.json()

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
            f"/api/projects/{self.team.id}/llm_analytics/text_repr/",
            request_data,
            format="json",
        )

        assert response.status_code == 200
        data = response.json()

        assert "text" in data
        assert "MY-TRACE" in data["text"]
        assert "TRACE HIERARCHY:" in data["text"]
        assert "[GEN]" in data["text"]
        assert data["metadata"]["trace_id"] == "trace123"

    def test_missing_event_type(self):
        """Should return 400 for missing event_type."""
        request_data = {"data": {}}

        response = self.client.post(
            f"/api/projects/{self.team.id}/llm_analytics/text_repr/",
            request_data,
            format="json",
        )

        assert response.status_code == 400
        data = response.json()
        assert "event_type" in str(data).lower()

    def test_missing_data(self):
        """Should return 400 for missing data."""
        request_data = {"event_type": "$ai_generation"}

        response = self.client.post(
            f"/api/projects/{self.team.id}/llm_analytics/text_repr/",
            request_data,
            format="json",
        )

        assert response.status_code == 400
        data = response.json()
        assert "data" in str(data).lower()

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
            f"/api/projects/{self.team.id}/llm_analytics/text_repr/",
            request_data,
            format="json",
        )

        assert response.status_code == 200
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
            f"/api/projects/{self.team.id}/llm_analytics/text_repr/",
            request_data,
            format="json",
        )

        assert response.status_code == 200
        data = response.json()
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
            f"/api/projects/{self.team.id}/llm_analytics/text_repr/",
            request_data,
            format="json",
        )

        assert response.status_code == 200
        data = response.json()
        # Should not have interactive markers
        assert "<<<TRUNCATED|" not in data["text"]
        assert "chars truncated" in data["text"]

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
            f"/api/projects/{self.team.id}/llm_analytics/text_repr/",
            request_data,
            format="json",
        )

        assert response.status_code == 200
        data = response.json()
        # Should show tree but not expandable markers
        assert "[GEN]" in data["text"]
        assert "GEN_EXPANDABLE" not in data["text"]

    def test_batch_stringify(self):
        """Should stringify multiple events in batch."""
        request_data = {
            "items": [
                {
                    "event_id": "gen1",
                    "event_type": "$ai_generation",
                    "data": {
                        "id": "gen1",
                        "event": "$ai_generation",
                        "properties": {"$ai_input": "First"},
                    },
                },
                {
                    "event_id": "gen2",
                    "event_type": "$ai_generation",
                    "data": {
                        "id": "gen2",
                        "event": "$ai_generation",
                        "properties": {"$ai_input": "Second"},
                    },
                },
            ],
            "options": {"truncated": True},
        }

        response = self.client.post(
            f"/api/projects/{self.team.id}/llm_analytics/text_repr/batch/",
            request_data,
            format="json",
        )

        assert response.status_code == 200
        data = response.json()

        assert "results" in data
        assert len(data["results"]) == 2
        assert "First" in data["results"][0]["text"]
        assert "Second" in data["results"][1]["text"]

    def test_batch_empty_items(self):
        """Should return 400 for empty items list."""
        request_data = {"items": []}

        response = self.client.post(
            f"/api/projects/{self.team.id}/llm_analytics/text_repr/batch/",
            request_data,
            format="json",
        )

        assert response.status_code == 400

    def test_batch_too_many_items(self):
        """Should return 400 for too many items."""
        request_data = {
            "items": [
                {
                    "event_type": "$ai_generation",
                    "data": {"id": f"gen{i}", "event": "$ai_generation", "properties": {}},
                }
                for i in range(51)
            ]
        }

        response = self.client.post(
            f"/api/projects/{self.team.id}/llm_analytics/text_repr/batch/",
            request_data,
            format="json",
        )

        assert response.status_code == 400
        data = response.json()
        assert "50" in str(data)

    def test_batch_with_error_in_item(self):
        """Should include error in results for failed items."""
        request_data = {
            "items": [
                {
                    "event_type": "$ai_generation",
                    "data": {
                        "id": "gen1",
                        "event": "$ai_generation",
                        "properties": {"$ai_input": "Valid"},
                    },
                },
                {
                    "event_type": "$ai_generation",
                    "data": None,  # This will cause an error
                },
            ]
        }

        response = self.client.post(
            f"/api/projects/{self.team.id}/llm_analytics/text_repr/batch/",
            request_data,
            format="json",
        )

        assert response.status_code == 200
        data = response.json()

        assert len(data["results"]) == 2
        # First should succeed
        assert "Valid" in data["results"][0]["text"]
        # Second should have error
        assert data["results"][1]["metadata"]["rendering"] == "error"
        assert "error" in data["results"][1]["metadata"]

    def test_authentication_required(self):
        """Should require authentication."""
        self.client.logout()

        request_data = {
            "event_type": "$ai_generation",
            "data": {"id": "gen123", "event": "$ai_generation", "properties": {}},
        }

        response = self.client.post(
            f"/api/projects/{self.team.id}/llm_analytics/text_repr/",
            request_data,
            format="json",
        )

        assert response.status_code in [401, 403]

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
            f"/api/projects/{other_team.id}/llm_analytics/text_repr/",
            request_data,
            format="json",
        )

        # Should be forbidden
        assert response.status_code in [403, 404]


class TestProviderFormats(APIBaseTest):
    """Test different LLM provider formats."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_login(self.user)

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
            f"/api/projects/{self.team.id}/llm_analytics/text_repr/",
            request_data,
            format="json",
        )

        assert response.status_code == 200
        data = response.json()
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
            f"/api/projects/{self.team.id}/llm_analytics/text_repr/",
            request_data,
            format="json",
        )

        assert response.status_code == 200
        data = response.json()
        assert "I'll help" in data["text"]
        assert "get_weather" in data["text"]
        assert "Dublin" in data["text"]

    def test_mixed_formats(self):
        """Should handle mixed provider formats in batch."""
        request_data = {
            "items": [
                {
                    "event_type": "$ai_generation",
                    "data": {
                        "id": "gen1",
                        "event": "$ai_generation",
                        "properties": {"$ai_output_choices": [{"message": {"role": "assistant", "content": "OpenAI"}}]},
                    },
                },
                {
                    "event_type": "$ai_generation",
                    "data": {
                        "id": "gen2",
                        "event": "$ai_generation",
                        "properties": {"$ai_output_choices": [{"role": "assistant", "content": "Anthropic"}]},
                    },
                },
            ]
        }

        response = self.client.post(
            f"/api/projects/{self.team.id}/llm_analytics/text_repr/batch/",
            request_data,
            format="json",
        )

        assert response.status_code == 200
        data = response.json()
        assert "OpenAI" in data["results"][0]["text"]
        assert "Anthropic" in data["results"][1]["text"]


class TestEdgeCases(APIBaseTest):
    """Test edge cases and error handling."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_login(self.user)

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
            f"/api/projects/{self.team.id}/llm_analytics/text_repr/",
            request_data,
            format="json",
        )

        assert response.status_code == 200
        # Should not crash

    def test_malformed_json(self):
        """Should handle malformed JSON gracefully."""
        response = self.client.post(
            f"/api/projects/{self.team.id}/llm_analytics/text_repr/",
            "not json",
            content_type="application/json",
        )

        assert response.status_code == 400

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
            f"/api/projects/{self.team.id}/llm_analytics/text_repr/",
            request_data,
            format="json",
        )

        assert response.status_code == 200
        data = response.json()
        # Should be truncated to max_length
        assert data["metadata"]["char_count"] <= 50000 + 100  # Allow for truncation message
        assert data["metadata"]["truncated"] is True

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
            f"/api/projects/{self.team.id}/llm_analytics/text_repr/",
            request_data,
            format="json",
        )

        assert response.status_code == 200
        data = response.json()
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
            f"/api/projects/{self.team.id}/llm_analytics/text_repr/",
            request_data,
            format="json",
        )

        assert response.status_code == 200
        # Should not crash

    def test_circular_references_in_state(self):
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
            f"/api/projects/{self.team.id}/llm_analytics/text_repr/",
            request_data,
            format="json",
        )

        assert response.status_code == 200
        data = response.json()
        assert "deep" in data["text"]
