from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.buildbetter.buildbetter import (
    BuildBetterResumeConfig,
    _make_paginated_request,
    buildbetter_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.buildbetter.settings import (
    BUILDBETTER_API_URL,
    BUILDBETTER_ENDPOINTS,
    BUILDBETTER_REST_API_URL,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.buildbetter.source import BuildBetterSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager


def _make_response(json_data: dict, status_code: int = 200) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 300
    response.json.return_value = json_data
    return response


def _make_manager(can_resume: bool = False, state: BuildBetterResumeConfig | None = None) -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = can_resume
    manager.load_state.return_value = state
    return manager


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


REST_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.buildbetter.buildbetter.make_tracked_session"
)


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

        state = BuildBetterResumeConfig(offset=saved_offset) if saved_offset is not None else None
        manager = _make_manager(can_resume=can_resume, state=state)
        logger = MagicMock()

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.buildbetter.buildbetter.make_tracked_session"
        ) as session_cls:
            session = session_cls.return_value
            session.post.return_value = _make_response(resumed_page)

            batches = list(
                _make_paginated_request(
                    api_key="key",
                    endpoint_name="interviews",
                    logger=logger,
                    resumable_source_manager=manager,
                )
            )

        assert batches == [[{"id": "x"}]]
        assert session.post.call_count == 1
        call = session.post.call_args_list[0]
        assert call.kwargs["json"]["variables"]["offset"] == expected_first_offset

        manager.can_resume.assert_called_once()
        if can_resume:
            manager.load_state.assert_called_once()
        else:
            manager.load_state.assert_not_called()
        # Short page terminates the loop; save_state is not invoked
        manager.save_state.assert_not_called()

    def test_save_state_called_for_each_full_page(self) -> None:
        page_size = BUILDBETTER_ENDPOINTS["interviews"].page_size
        full_page_a = _interview_payload([f"a{i}" for i in range(page_size)])
        full_page_b = _interview_payload([f"b{i}" for i in range(page_size)])
        tail_page = _interview_payload(["c0"])

        manager = _make_manager(can_resume=False)
        logger = MagicMock()

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.buildbetter.buildbetter.make_tracked_session"
        ) as session_cls:
            session = session_cls.return_value
            session.post.side_effect = [
                _make_response(full_page_a),
                _make_response(full_page_b),
                _make_response(tail_page),
            ]

            list(
                _make_paginated_request(
                    api_key="key",
                    endpoint_name="interviews",
                    logger=logger,
                    resumable_source_manager=manager,
                )
            )

        saved_offsets = [call.args[0].offset for call in manager.save_state.call_args_list]
        assert saved_offsets == [page_size, page_size * 2]

    def test_drops_optional_field_when_schema_rejects_it(self) -> None:
        manager = _make_manager(can_resume=False)
        logger = MagicMock()
        schema_error = {"errors": [{"message": "field 'monologues' not found in type: 'interview'"}]}

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.buildbetter.buildbetter.make_tracked_session"
        ) as session_cls:
            session = session_cls.return_value
            session.post.side_effect = [
                _make_response(schema_error),
                _make_response(_interview_payload(["i1"])),
            ]

            batches = list(
                _make_paginated_request(
                    api_key="key",
                    endpoint_name="interviews",
                    logger=logger,
                    resumable_source_manager=manager,
                )
            )

        assert batches == [[{"id": "i1"}]]
        assert session.post.call_count == 2
        first_query = session.post.call_args_list[0].kwargs["json"]["query"]
        retried_query = session.post.call_args_list[1].kwargs["json"]["query"]
        assert "monologues" in first_query
        assert "monologues" not in retried_query
        # Same page is retried after dropping the field, not skipped
        assert session.post.call_args_list[1].kwargs["json"]["variables"]["offset"] == 0

    def test_non_droppable_schema_error_still_raises(self) -> None:
        manager = _make_manager(can_resume=False)
        logger = MagicMock()
        schema_error = {"errors": [{"message": "field 'id' not found in type: 'interview'"}]}

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.buildbetter.buildbetter.make_tracked_session"
        ) as session_cls:
            session = session_cls.return_value
            session.post.return_value = _make_response(schema_error)

            with pytest.raises(Exception, match="BuildBetter GraphQL error"):
                list(
                    _make_paginated_request(
                        api_key="key",
                        endpoint_name="interviews",
                        logger=logger,
                        resumable_source_manager=manager,
                    )
                )

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
        manager = _make_manager(can_resume=False)
        logger = MagicMock()
        query_name = BUILDBETTER_ENDPOINTS[endpoint_name].graphql_query_name

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.buildbetter.buildbetter.make_tracked_session"
        ) as session_cls:
            session = session_cls.return_value
            session.post.return_value = _make_response({"data": {query_name: []}})

            list(
                _make_paginated_request(
                    api_key="key",
                    endpoint_name=endpoint_name,
                    logger=logger,
                    resumable_source_manager=manager,
                    incremental_field=incremental_field,
                    incremental_field_last_value="2026-01-01",
                )
            )

        call = session.post.call_args_list[0]
        assert call.kwargs["json"]["variables"]["where"] == {expected_filter_field: {"_gt": "2026-01-01"}}


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
        manager = _make_manager(can_resume=False)
        logger = MagicMock()

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.buildbetter.buildbetter.make_tracked_session"
        ) as session_cls:
            session = session_cls.return_value
            session.post.return_value = _make_response({"data": payload})

            batches = list(
                _make_paginated_request(
                    api_key="key",
                    endpoint_name=endpoint_name,
                    logger=logger,
                    resumable_source_manager=manager,
                )
            )

        assert batches == [expected_rows]
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

        manager = _make_manager(can_resume=False)
        logger = MagicMock()

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.buildbetter.buildbetter.make_tracked_session"
        ) as session_cls:
            session = session_cls.return_value
            session.post.side_effect = [_make_response(empty_page), _make_response(tail_page)]

            batches = list(
                _make_paginated_request(
                    api_key="key",
                    endpoint_name="interview_sentences",
                    logger=logger,
                    resumable_source_manager=manager,
                )
            )

        assert session.post.call_count == 2
        assert session.post.call_args_list[1].kwargs["json"]["variables"]["offset"] == page_size
        assert batches == [
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
        manager = _make_manager(can_resume=False)

        with patch(REST_PATCH) as session_cls:
            session = session_cls.return_value
            session.get.side_effect = [
                _make_response(_recordings_page(["rec-1", "rec-gone"])),
                _make_response(child_payload),
                # A recording deleted after the list read is skipped rather than failing the sync
                _make_response({"message": "Not Found"}, status_code=404),
            ]

            response = buildbetter_source(
                api_key="key",
                endpoint_name=endpoint_name,
                api_version="v3",
                logger=MagicMock(),
                resumable_source_manager=manager,
            )
            batches = list(cast(Iterable[Any], response.items()))

        parent_columns = {
            "interview_id": "rec-1",
            "interview_created_at": "2026-07-28T15:05:00.000Z",
            "interview_updated_at": "2026-07-28T15:12:00.000Z",
        }
        assert batches == [[parent_columns | row for row in expected_child_rows]]
        primary_keys = response.primary_keys
        assert primary_keys
        for row in batches[0]:
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
        manager = _make_manager(can_resume=can_resume, state=state)

        with patch(REST_PATCH) as session_cls:
            session = session_cls.return_value
            session.get.side_effect = [
                _make_response(_recordings_page(["a"], has_more=True)),
                _make_response(_recordings_page(["b"], has_more=False)),
            ]

            response = buildbetter_source(
                api_key="key",
                endpoint_name="interviews",
                api_version="v3",
                logger=MagicMock(),
                resumable_source_manager=manager,
            )
            batches = list(cast(Iterable[Any], response.items()))

        assert batches == [[_recording("a")], [_recording("b")]]
        assert [call.kwargs["params"]["page"] for call in session.get.call_args_list] == [first_page, first_page + 1]
        assert [call.args[0].page for call in manager.save_state.call_args_list] == [first_page + 1]
        assert response.on_complete == manager.clear_state


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
        manager = _make_manager(can_resume=False)
        query_name = BUILDBETTER_ENDPOINTS[endpoint_name].graphql_query_name

        with patch(REST_PATCH) as session_cls:
            session = session_cls.return_value
            session.post.return_value = _make_response({"data": {query_name: []}})
            session.get.return_value = _make_response(_recordings_page([]))

            response = buildbetter_source(
                api_key="key",
                endpoint_name=endpoint_name,
                api_version=api_version,
                logger=MagicMock(),
                resumable_source_manager=manager,
            )
            list(cast(Iterable[Any], response.items()))

        requested_urls = [call.args[0] for call in session.post.call_args_list + session.get.call_args_list]
        assert requested_urls == [expected_url]
        assert response.primary_keys == expected_primary_keys
        manager.can_resume.assert_called_once()

    def test_unknown_version_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="Unsupported BuildBetter API version"):
            buildbetter_source(
                api_key="key",
                endpoint_name="interviews",
                api_version="v2",
                logger=MagicMock(),
                resumable_source_manager=_make_manager(),
            )

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
        with patch(REST_PATCH) as session_cls:
            session = session_cls.return_value
            getattr(session, method).return_value = _make_response(payload)

            assert validate_credentials("key", api_version) == (True, None)

        assert getattr(session, method).call_args.args[0] == expected_url


class TestBuildBetterSourceNonRetryableErrors:
    def setup_method(self) -> None:
        self.source = BuildBetterSource()

    @parameterized.expand(
        [
            ("401_client_error", "401 Client Error: Unauthorized for url: https://api.buildbetter.app/v1/graphql"),
            ("403_client_error", "403 Client Error: Forbidden for url: https://api.buildbetter.app/v1/graphql"),
            ("auth_hook_unauthorized", "BuildBetter GraphQL error: Authentication hook unauthorized this request"),
            ("webhook_auth_request_failed", "BuildBetter GraphQL error: webhook authentication request failed"),
        ]
    )
    def test_matches_auth_failures(self, _name: str, observed_error: str) -> None:
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @parameterized.expand(
        [
            ("read_timeout", "HTTPSConnectionPool(host='api.buildbetter.app', port=443): Read timed out."),
            ("server_error", "BuildBetter: server error 503"),
            ("connection_reset", "Connection reset by peer"),
        ]
    )
    def test_does_not_match_transient_errors(self, _name: str, other_error: str) -> None:
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)
