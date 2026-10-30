from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.buildbetter.buildbetter import (
    BuildBetterResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.buildbetter.settings import (
    BUILDBETTER_API_URL,
    BUILDBETTER_ENDPOINTS,
    BUILDBETTER_REST_API_URL,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.buildbetter.source import BuildBetterSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.buildbetter import (
    BuildBetterSourceConfig,
)


def _interview_payload(ids: list[str]) -> dict:
    return {"data": {"interview": [{"id": i} for i in ids]}}


def _recording(recording_id: str) -> dict:
    return {
        "id": recording_id,
        "display_name": "Renewal discussion",
        "source": "upload",
        "recorded_at": "2026-07-28T15:00:00.000Z",
        "created_at": "2026-07-28T15:05:00.000Z",
        "updated_at": "2026-07-28T15:12:00.000Z",
        "metadata": [],
    }


def _recordings_page(ids: list[str], has_more: bool = False) -> dict:
    return {"recordings": [_recording(i) for i in ids], "page": 1, "limit": 100, "has_more": has_more}


def _driver() -> SourceDriver:
    return SourceDriver(BuildBetterSource(), BuildBetterSourceConfig(api_key="key"))


class TestMakePaginatedRequest:
    @parameterized.expand(
        [
            ("fresh_run", False, None, 0),
            ("resume", True, 3, 3),
        ]
    )
    def test_starting_offset_from_resume_state(
        self,
        _name: str,
        can_resume: bool,
        saved_offset_multiplier: int | None,
        expected_first_offset_multiplier: int,
    ) -> None:
        page_size = BUILDBETTER_ENDPOINTS["interviews"].page_size
        saved_offset = saved_offset_multiplier * page_size if saved_offset_multiplier is not None else None
        expected_first_offset = expected_first_offset_multiplier * page_size
        # Single short page terminates the loop without saving further state
        resumed_page = _interview_payload(["x"])

        state = BuildBetterResumeConfig(offset=saved_offset) if can_resume and saved_offset is not None else None
        result = _driver().run(
            "interviews", [ScriptedResponse(json=resumed_page)], resume_state=state, api_version="v1"
        )

        assert result.raised is None
        assert result.items == [[{"id": "x"}]]
        assert len(result.requests) == 1
        assert result.requests[0].json()["variables"]["offset"] == expected_first_offset
        # Short page terminates the loop; save_state is not invoked
        assert result.saved_states == []

    def test_save_state_called_for_each_full_page(self) -> None:
        page_size = BUILDBETTER_ENDPOINTS["interviews"].page_size
        full_page_a = _interview_payload([f"a{i}" for i in range(page_size)])
        full_page_b = _interview_payload([f"b{i}" for i in range(page_size)])
        tail_page = _interview_payload(["c0"])

        result = _driver().run(
            "interviews",
            [ScriptedResponse(json=page) for page in (full_page_a, full_page_b, tail_page)],
            api_version="v1",
        )

        assert result.raised is None
        assert result.saved_states == [
            BuildBetterResumeConfig(offset=page_size),
            BuildBetterResumeConfig(offset=page_size * 2),
        ]

    def test_drops_optional_field_when_schema_rejects_it(self) -> None:
        schema_error = {"errors": [{"message": "field 'monologues' not found in type: 'interview'"}]}
        result = _driver().run(
            "interviews",
            [ScriptedResponse(json=schema_error), ScriptedResponse(json=_interview_payload(["i1"]))],
            api_version="v1",
        )

        assert result.raised is None
        assert result.items == [[{"id": "i1"}]]
        assert len(result.requests) == 2
        first_query = result.requests[0].json()["query"]
        retried_query = result.requests[1].json()["query"]
        assert "monologues" in first_query
        assert "monologues" not in retried_query
        # Same page is retried after dropping the field, not skipped
        assert result.requests[1].json()["variables"]["offset"] == 0

    def test_non_droppable_schema_error_still_raises(self) -> None:
        schema_error = {"errors": [{"message": "field 'id' not found in type: 'interview'"}]}
        result = _driver().run("interviews", [ScriptedResponse(json=schema_error)], api_version="v1")

        assert isinstance(result.raised, Exception)
        assert "BuildBetter GraphQL error" in str(result.raised)

    @parameterized.expand(
        [
            ("top_level", "interviews", "updated_at", "updated_at"),
            # A nested table's rows carry the parent timestamp under a prefixed column, but the
            # filter has to name the field the parent query knows
            ("nested_interview", "interview_attendees", "interview_updated_at", "updated_at"),
            ("nested_extraction", "extraction_topics", "extraction_created_at", "created_at"),
        ]
    )
    def test_incremental_filter_passes_where_clause(
        self, _name: str, endpoint_name: str, incremental_field: str, expected_filter_field: str
    ) -> None:
        query_name = BUILDBETTER_ENDPOINTS[endpoint_name].graphql_query_name
        result = _driver().run(
            endpoint_name,
            [ScriptedResponse(json={"data": {query_name: []}})],
            api_version="v1",
            incremental_field=incremental_field,
            db_incremental_field_last_value="2026-01-01",
        )

        assert result.raised is None
        assert result.requests[0].json()["variables"]["where"] == {expected_filter_field: {"_gt": "2026-01-01"}}


class TestNestedEndpoints:
    @parameterized.expand(
        [
            (
                "interview_attendees",
                "interview_attendees",
                {
                    "interview": [
                        {
                            "id": 1,
                            "created_at": "2026-01-01",
                            "updated_at": "2026-01-02",
                            "attendees": [
                                {"id": 10, "speaker": "Speaker 1", "person": {"id": 100, "email": "a@example.com"}},
                                {"id": 11, "speaker": "Speaker 2", "person": None},
                            ],
                        }
                    ]
                },
                [
                    {
                        "interview_id": 1,
                        "interview_created_at": "2026-01-01",
                        "interview_updated_at": "2026-01-02",
                        "id": 10,
                        "speaker": "Speaker 1",
                        "person": {"id": 100, "email": "a@example.com"},
                    },
                    {
                        "interview_id": 1,
                        "interview_created_at": "2026-01-01",
                        "interview_updated_at": "2026-01-02",
                        "id": 11,
                        "speaker": "Speaker 2",
                        "person": None,
                    },
                ],
            ),
            (
                "interview_sentences",
                "interview_sentences",
                {
                    "interview": [
                        {
                            "id": 2,
                            "created_at": "2026-01-01",
                            "updated_at": "2026-01-02",
                            "sentences": [
                                {"text": "First", "speaker": "Speaker 1", "start_sec": 0, "end_sec": 2},
                                {"text": "Second", "speaker": "Speaker 2", "start_sec": 2, "end_sec": 4},
                            ],
                        }
                    ]
                },
                [
                    {
                        "interview_id": 2,
                        "interview_created_at": "2026-01-01",
                        "interview_updated_at": "2026-01-02",
                        "text": "First",
                        "speaker": "Speaker 1",
                        "start_sec": 0,
                        "end_sec": 2,
                        "sentence_index": 0,
                    },
                    {
                        "interview_id": 2,
                        "interview_created_at": "2026-01-01",
                        "interview_updated_at": "2026-01-02",
                        "text": "Second",
                        "speaker": "Speaker 2",
                        "start_sec": 2,
                        "end_sec": 4,
                        "sentence_index": 1,
                    },
                ],
            ),
            (
                "interview_tags",
                "interview_tags",
                {
                    "interview": [
                        {
                            "id": 6,
                            "created_at": "2026-01-01",
                            "updated_at": "2026-01-02",
                            "tags": [
                                {"tag": {"id": 20, "name": "Churn risk", "color": "#ff0000"}},
                                # A tag reference the API resolves to nothing has no key columns
                                {"tag": None},
                            ],
                        }
                    ]
                },
                [
                    {
                        "interview_id": 6,
                        "interview_created_at": "2026-01-01",
                        "interview_updated_at": "2026-01-02",
                        "tag_id": 20,
                        "tag_name": "Churn risk",
                        "tag_color": "#ff0000",
                    },
                ],
            ),
            (
                # An object relationship yields at most one row, built from the type's own fields
                "interview_types",
                "interview_types",
                {
                    "interview": [
                        {
                            "id": 7,
                            "created_at": "2026-01-01",
                            "updated_at": "2026-01-02",
                            "type": {"id": 30, "name": "User interview"},
                        },
                        {"id": 8, "created_at": "2026-01-03", "updated_at": "2026-01-04", "type": None},
                    ]
                },
                [
                    {
                        "interview_id": 7,
                        "interview_created_at": "2026-01-01",
                        "interview_updated_at": "2026-01-02",
                        "type_id": 30,
                        "type_name": "User interview",
                    },
                ],
            ),
            (
                "extraction_types",
                "extraction_types",
                {
                    "extraction": [
                        {
                            "id": 9,
                            "created_at": "2026-01-05",
                            "types": [
                                {"type": {"id": 40, "name": "Pain point"}},
                                {"type": {"id": 41, "name": "Feature request"}},
                            ],
                        }
                    ]
                },
                [
                    {
                        "extraction_id": 9,
                        "extraction_created_at": "2026-01-05",
                        "type_id": 40,
                        "type_name": "Pain point",
                    },
                    {
                        "extraction_id": 9,
                        "extraction_created_at": "2026-01-05",
                        "type_id": 41,
                        "type_name": "Feature request",
                    },
                ],
            ),
            (
                "extraction_topics",
                "extraction_topics",
                {
                    "extraction": [
                        {
                            "id": 3,
                            "created_at": "2026-01-03",
                            "topics": [{"topic": {"id": 7, "text": "Pricing"}}],
                        },
                        {"id": 4, "created_at": "2026-01-04", "topics": []},
                        # A topic reference the API resolves to nothing has no key columns
                        {"id": 5, "created_at": "2026-01-05", "topics": [{"topic": None}]},
                    ]
                },
                [
                    {
                        "extraction_id": 3,
                        "extraction_created_at": "2026-01-03",
                        "topic_id": 7,
                        "topic_text": "Pricing",
                    },
                ],
            ),
        ]
    )
    def test_flattens_nested_rows_with_parent_columns(
        self, _name: str, endpoint_name: str, payload: dict, expected_rows: list[dict]
    ) -> None:
        result = _driver().run(endpoint_name, [ScriptedResponse(json={"data": payload})], api_version="v1")

        assert result.raised is None
        assert result.items == [expected_rows]
        # Every row has to carry its whole primary key, otherwise merges collapse or duplicate rows
        for row in expected_rows:
            assert all(key in row for key in BUILDBETTER_ENDPOINTS[endpoint_name].primary_keys)

    def test_page_without_nested_rows_keeps_paginating(self) -> None:
        page_size = BUILDBETTER_ENDPOINTS["interview_sentences"].page_size
        empty_page = {
            "data": {
                "interview": [
                    {"id": i, "created_at": "c", "updated_at": "u", "sentences": []} for i in range(page_size)
                ]
            }
        }
        tail_page = {
            "data": {
                "interview": [
                    {
                        "id": 99,
                        "created_at": "c",
                        "updated_at": "u",
                        "sentences": [{"text": "Hello", "speaker": "Speaker 1", "start_sec": 0, "end_sec": 1}],
                    }
                ]
            }
        }

        result = _driver().run(
            "interview_sentences",
            [ScriptedResponse(json=empty_page), ScriptedResponse(json=tail_page)],
            api_version="v1",
        )

        assert result.raised is None
        assert len(result.requests) == 2
        assert result.requests[1].json()["variables"]["offset"] == page_size
        assert result.items == [
            [
                {
                    "interview_id": 99,
                    "interview_created_at": "c",
                    "interview_updated_at": "u",
                    "text": "Hello",
                    "speaker": "Speaker 1",
                    "start_sec": 0,
                    "end_sec": 1,
                    "sentence_index": 0,
                }
            ]
        ]


class TestRestEndpoints:
    @parameterized.expand(
        [
            (
                "interview_attendees",
                "interview_attendees",
                {
                    "id": "rec-1",
                    "participants": [
                        {"speaker": 0, "person": {"id": "per-1", "firstName": "Pat", "email": "pat@example.com"}},
                        {"speaker": 1, "person": {"id": "per-2", "firstName": "Alex", "email": "alex@example.com"}},
                    ],
                },
                [
                    {"speaker": 0, "person": {"id": "per-1", "firstName": "Pat", "email": "pat@example.com"}},
                    {"speaker": 1, "person": {"id": "per-2", "firstName": "Alex", "email": "alex@example.com"}},
                ],
            ),
            (
                "interview_sentences",
                "interview_sentences",
                {
                    "type": "utterance",
                    "recordingId": "rec-1",
                    "utterances": [
                        {"recordingId": "rec-1", "startSec": 0, "endSec": 2.5, "speaker": 0, "text": "First"},
                        {"recordingId": "rec-1", "startSec": 2.5, "endSec": 4, "speaker": 1, "text": "Second"},
                    ],
                },
                [
                    {"text": "First", "speaker": 0, "start_sec": 0, "end_sec": 2.5, "sentence_index": 0},
                    {"text": "Second", "speaker": 1, "start_sec": 2.5, "end_sec": 4, "sentence_index": 1},
                ],
            ),
        ]
    )
    def test_flattens_recording_children_with_parent_columns(
        self, _name: str, endpoint_name: str, child_payload: dict, expected_child_rows: list[dict]
    ) -> None:
        result = _driver().run(
            endpoint_name,
            [
                ScriptedResponse(json=_recordings_page(["rec-1", "rec-gone"])),
                ScriptedResponse(json=child_payload),
                # A recording deleted after the list read is skipped rather than failing the sync
                ScriptedResponse(status=404, json={"message": "Not Found"}),
            ],
            api_version="v3",
        )

        parent_columns = {
            "interview_id": "rec-1",
            "interview_created_at": "2026-07-28T15:05:00.000Z",
            "interview_updated_at": "2026-07-28T15:12:00.000Z",
        }
        assert result.raised is None
        assert result.items == [[parent_columns | row for row in expected_child_rows]]
        assert result.response is not None
        primary_keys = result.response.primary_keys
        assert primary_keys
        for row in result.rows:
            assert all(row.get(key) is not None for key in primary_keys)

    @parameterized.expand(
        [
            ("fresh_run", False, None, 1),
            ("resume", True, BuildBetterResumeConfig(page=3), 3),
            # A checkpoint written by the GraphQL path carries no page, so REST starts over
            ("graphql_checkpoint", True, BuildBetterResumeConfig(offset=200), 1),
        ]
    )
    def test_pages_recordings_and_checkpoints_the_next_page(
        self, _name: str, can_resume: bool, state: BuildBetterResumeConfig | None, first_page: int
    ) -> None:
        result = _driver().run(
            "interviews",
            [
                ScriptedResponse(json=_recordings_page(["a"], has_more=True)),
                ScriptedResponse(json=_recordings_page(["b"], has_more=False)),
            ],
            resume_state=state if can_resume else None,
            api_version="v3",
        )

        assert result.raised is None
        assert result.items == [[_recording("a")], [_recording("b")]]
        assert result.params("page") == [str(first_page), str(first_page + 1)]
        assert [saved.page for saved in result.saved_states] == [first_page + 1]
        assert result.completed_state is None


class TestBuildbetterSource:
    @parameterized.expand(
        [
            ("v1_interviews", "v1", "interviews", BUILDBETTER_API_URL, ["id"]),
            ("v1_attendees", "v1", "interview_attendees", BUILDBETTER_API_URL, ["interview_id", "id"]),
            ("v3_interviews", "v3", "interviews", f"{BUILDBETTER_REST_API_URL}/recordings", ["id"]),
            (
                "v3_attendees",
                "v3",
                "interview_attendees",
                f"{BUILDBETTER_REST_API_URL}/recordings",
                ["interview_id", "speaker"],
            ),
            # REST serves no signals, so v3 keeps them on GraphQL
            ("v3_extractions", "v3", "extractions", BUILDBETTER_API_URL, ["id"]),
        ]
    )
    def test_routes_each_version_to_its_api(
        self, _name: str, api_version: str, endpoint_name: str, expected_url: str, expected_primary_keys: list[str]
    ) -> None:
        query_name = BUILDBETTER_ENDPOINTS[endpoint_name].graphql_query_name
        response = (
            ScriptedResponse(json=_recordings_page([]))
            if api_version == "v3" and endpoint_name != "extractions"
            else ScriptedResponse(json={"data": {query_name: []}})
        )
        result = _driver().run(endpoint_name, [response], api_version=api_version)

        assert result.raised is None
        assert [request.origin + request.path for request in result.requests] == [expected_url]
        assert result.response is not None
        assert result.response.primary_keys == expected_primary_keys

    def test_unknown_version_is_rejected(self) -> None:
        result = _driver().run("interviews", [], api_version="v2")

        assert isinstance(result.raised, ValueError)
        assert "Unsupported BuildBetter API version" in str(result.raised)

    @parameterized.expand(
        [
            ("v1", "v1", {"interviews", "interview_attendees", "interview_sentences", "extractions"}),
            ("v3", "v3", {"extractions"}),
        ]
    )
    def test_incremental_tables_per_version(self, _name: str, api_version: str, expected_incremental: set[str]) -> None:
        schemas = BuildBetterSource().get_schemas(MagicMock(), team_id=1, api_version=api_version)
        checked = {"interviews", "interview_attendees", "interview_sentences", "extractions"}

        assert {schema.name for schema in schemas if schema.supports_incremental} & checked == expected_incremental

    @parameterized.expand(
        [
            ("v1", "v1", "post", BUILDBETTER_API_URL, {"data": {"interview": [{"id": 1}]}}),
            ("v3", "v3", "get", f"{BUILDBETTER_REST_API_URL}/recordings", _recordings_page(["rec-1"])),
        ]
    )
    def test_validate_credentials_probes_the_pinned_api(
        self, _name: str, api_version: str, method: str, expected_url: str, payload: dict
    ) -> None:
        with scripted_network([ScriptedResponse(json=payload)]) as network:
            assert validate_credentials("key", api_version) == (True, None)

        assert [(request.method, request.origin + request.path) for request in network.requests_log] == [
            (method.upper(), expected_url)
        ]


class TestBuildBetterSourceNonRetryableErrors:
    def setup_method(self) -> None:
        self.source = BuildBetterSource()

    @parameterized.expand(
        [
            ("auth_hook_unauthorized", "BuildBetter GraphQL error: Authentication hook unauthorized this request"),
            ("webhook_auth_request_failed", "BuildBetter GraphQL error: webhook authentication request failed"),
        ]
    )
    def test_matches_auth_failures(self, _name: str, observed_error: str) -> None:
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @parameterized.expand(
        [
            ("server_error", "BuildBetter: server error 503"),
        ]
    )
    def test_does_not_match_transient_errors(self, _name: str, other_error: str) -> None:
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)
