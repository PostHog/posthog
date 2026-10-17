from datetime import UTC, date, datetime, timedelta
from typing import Any

import time_machine

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gong import GongSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.gong.gong import (
    GONG_BASE_URL,
    GongResumeConfig,
    _format_datetime,
    _to_datetime,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gong.source import GongSource


def _driver() -> SourceDriver:
    return SourceDriver(GongSource(), GongSourceConfig(access_key="key", access_key_secret="secret"))


class TestFormatDatetime:
    @parameterized.expand(
        [
            ("utc_aware", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_treated_as_utc", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
        ]
    )
    def test_format_datetime(self, _name: str, value: datetime, expected: str) -> None:
        assert _format_datetime(value) == expected


class TestToDatetime:
    @parameterized.expand(
        [
            ("none", None, None),
            ("aware_datetime", datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 1, tzinfo=UTC)),
            ("naive_datetime", datetime(2026, 1, 1), datetime(2026, 1, 1, tzinfo=UTC)),
            ("date", date(2026, 1, 1), datetime(2026, 1, 1, tzinfo=UTC)),
            ("iso_string", "2026-01-01T00:00:00Z", datetime(2026, 1, 1, tzinfo=UTC)),
            ("garbage_string", "not-a-date", None),
        ]
    )
    def test_to_datetime(self, _name: str, value: Any, expected: datetime | None) -> None:
        assert _to_datetime(value) == expected


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, None, True, None),
            ("unauthorized", 401, None, False, "Invalid Gong access key or access key secret"),
            ("forbidden_source_create", 403, None, True, None),
            (
                "forbidden_for_schema",
                403,
                "calls",
                False,
                "Your Gong credentials do not have permission to access this endpoint",
            ),
        ]
    )
    def test_validate_credentials(
        self, _name: str, status_code: int, schema_name: str | None, expected_valid: bool, expected_message: str | None
    ) -> None:
        with scripted_network([ScriptedResponse(status=status_code)]) as network:
            is_valid, message = validate_credentials("key", "secret", schema_name)

        assert is_valid is expected_valid
        assert message == expected_message
        assert [request.url for request in network.requests_log] == [f"{GONG_BASE_URL}/v2/workspaces"]


class TestWindowedCalls:
    def test_cursor_within_window(self) -> None:
        last_value = datetime.now(UTC) - timedelta(days=5)
        result = _driver().run(
            "calls",
            [
                ScriptedResponse(json={"calls": [{"id": "c1"}], "records": {"cursor": "page2"}}),
                ScriptedResponse(json={"calls": [{"id": "c2"}]}),
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value=last_value,
        )

        assert result.raised is None
        assert result.items == [[{"id": "c1"}], [{"id": "c2"}]]
        assert result.params("cursor") == [None, "page2"]

    @parameterized.expand(
        [
            # Gong signals an empty date window with a 404; the sync skips it and continues.
            (
                "no_calls_body_skips_window",
                '{"errors":["No calls found corresponding to the provided filters"]}',
                False,
            ),
            (
                "no_records_of_another_kind_skips_window",
                '{"errors":["No answered scorecards found corresponding to the provided filters"]}',
                False,
            ),
            # A 404 for any other reason must still surface rather than be swallowed.
            ("unrelated_404_raises", '{"errors":["Not Found"]}', True),
        ]
    )
    def test_404_handling(self, _name: str, body: str, should_raise: bool) -> None:
        last_value = datetime.now(UTC) - timedelta(days=100)
        result = _driver().run(
            "calls",
            [
                ScriptedResponse(status=404, body=body.encode()),
                ScriptedResponse(json={"calls": [{"id": "c1"}]}),
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value=last_value,
        )

        if should_raise:
            assert isinstance(result.raised, Exception)
            assert result.paths == ["/v2/calls"]
            return
        # The empty window yields nothing but does not abort the sync; both windows run.
        assert result.raised is None
        assert result.items == [[{"id": "c1"}]]
        assert len(result.requests) == 2
        assert len(result.saved_states) == 2

    def test_resume_uses_saved_window_start(self) -> None:
        last_value = datetime.now(UTC) - timedelta(days=80)
        resume_start = datetime.now(UTC) - timedelta(days=10)
        result = _driver().run(
            "calls",
            [ScriptedResponse(json={"calls": [{"id": "c1"}]})],
            resume_state=GongResumeConfig(window_start=_format_datetime(resume_start)),
            should_use_incremental_field=True,
            db_incremental_field_last_value=last_value,
        )

        assert result.raised is None
        # The first request starts from the resumed window, not the DB cursor value.
        assert result.requests[0].param("fromDateTime") == _format_datetime(resume_start)


class TestGongSource:
    @parameterized.expand(
        [
            ("calls", ["id"], "started", "asc"),
            ("transcripts", ["callId"], "started", "asc"),
            ("users", ["id"], "created", "asc"),
            ("scorecards", ["scorecardId"], "created", "asc"),
            ("trackers", ["trackerId"], "created", "asc"),
            ("answered_scorecards", ["answeredScorecardId"], "callStartTime", "asc"),
            # A user's stats are one row per day, so the user id alone would merge every day into one.
            ("interaction_stats", ["userId", "day"], "day", "asc"),
            ("daily_activity", ["userId", "fromDate"], "fromDate", "asc"),
            # A folder can hold the same call more than once, as different snippets.
            ("library_folder_calls", ["folderId", "id", "created"], "created", "asc"),
            ("flows", ["id"], None, "asc"),
            ("workspaces", ["id"], None, "asc"),
        ]
    )
    def test_source_response_shape(
        self, endpoint: str, primary_keys: list[str], partition_key: str | None, sort_mode: str
    ) -> None:
        result = _driver().run(endpoint, [])
        response = result.response

        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.sort_mode == sort_mode
        if partition_key:
            assert response.partition_keys == [partition_key]
            assert response.partition_mode == "datetime"
        else:
            assert response.partition_keys is None
            assert response.partition_mode is None


class TestExtensiveCalls:
    # Gong returns only the enrichment blocks the selector names, so a table whose selector and
    # kept row keys disagree syncs null columns and no data at all.
    @parameterized.expand(
        [
            (
                "calls_extensive_requests_parties_and_crm_context",
                "calls_extensive",
                {
                    "parties": [{"emailAddress": "buyer@acme.com", "affiliation": "External"}],
                    "context": [{"system": "Salesforce", "objects": [{"objectType": "Account"}]}],
                    "content": {"brief": "should be dropped — not a column on this table"},
                },
                {"context": "Extended", "exposedFields": {"parties": True}},
                {
                    "parties": [{"emailAddress": "buyer@acme.com", "affiliation": "External"}],
                    "context": [{"system": "Salesforce", "objects": [{"objectType": "Account"}]}],
                },
            ),
            (
                "calls_content_requests_spotlight_summary_only",
                "calls_content",
                {
                    "content": {"brief": "Buyer wants SSO.", "keyPoints": [{"text": "Asked about SSO"}]},
                    "parties": [{"emailAddress": "buyer@acme.com"}],
                },
                {
                    "context": "None",
                    "exposedFields": {
                        "content": {
                            "brief": True,
                            "keyPoints": True,
                            "highlights": True,
                            "callOutcome": True,
                            "outline": True,
                        }
                    },
                },
                {"content": {"brief": "Buyer wants SSO.", "keyPoints": [{"text": "Asked about SSO"}]}},
            ),
        ]
    )
    def test_posts_selector_and_flattens_metadata(
        self,
        _name: str,
        endpoint: str,
        siblings: dict[str, Any],
        expected_selector: dict[str, Any],
        expected_columns: dict[str, Any],
    ) -> None:
        last_value = datetime.now(UTC) - timedelta(days=5)
        result = _driver().run(
            endpoint,
            [
                ScriptedResponse(
                    json={
                        "calls": [
                            {
                                "metaData": {"id": "c1", "title": "Discovery", "started": "2026-03-01T00:00:00Z"},
                                **siblings,
                            }
                        ]
                    }
                )
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value=last_value,
        )

        assert result.raised is None
        # metaData is lifted to the top level; only the blocks this table asked for ride along.
        assert result.items == [
            [{"id": "c1", "title": "Discovery", "started": "2026-03-01T00:00:00Z", **expected_columns}]
        ]
        # A single POST to the extensive endpoint with no query string.
        assert result.paths == ["/v2/calls/extensive"]
        assert result.requests[0].method == "POST"
        body = result.requests[0].json()
        assert body["contentSelector"] == expected_selector
        assert body["filter"]["fromDateTime"] == _format_datetime(last_value)
        assert "cursor" not in body

    def test_cursor_travels_in_body(self) -> None:
        last_value = datetime.now(UTC) - timedelta(days=5)
        result = _driver().run(
            "calls_extensive",
            [
                ScriptedResponse(json={"calls": [{"metaData": {"id": "c1"}}], "records": {"cursor": "page2"}}),
                ScriptedResponse(json={"calls": [{"metaData": {"id": "c2"}}]}),
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value=last_value,
        )

        assert result.raised is None
        assert result.items == [
            [{"id": "c1", "parties": None, "context": None}],
            [{"id": "c2", "parties": None, "context": None}],
        ]
        # The cursor is sent in the second request's body, never as a query param.
        assert result.requests[1].json()["cursor"] == "page2"
        assert result.params("cursor") == [None, None]

    @parameterized.expand(
        [
            # Extensive responses carry participant names and free-form CRM fields, and transcript
            # responses carry verbatim conversation text, so neither may reach HTTP sample capture.
            # Basic list endpoints stay captured for troubleshooting.
            ("calls_extensive", [{"calls": [{"metaData": {"id": "c1"}}]}], False),
            (
                "transcripts",
                [{"calls": [{"id": "c1", "started": "2026-03-01T00:00:00Z"}]}, {"callTranscripts": [{"callId": "c1"}]}],
                False,
            ),
            ("answered_scorecards", [{"answeredScorecards": [{"answeredScorecardId": 1}]}], False),
            ("users", [{"users": [{"id": "u1"}]}], True),
        ]
    )
    def test_response_body_capture_per_endpoint(
        self, endpoint: str, payloads: list[dict], expected_capture: bool
    ) -> None:
        result = _driver().run(
            endpoint,
            [ScriptedResponse(json=payload) for payload in payloads],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime.now(UTC) - timedelta(days=5),
        )

        assert result.raised is None
        assert result.session_options
        assert all(options["capture"] is expected_capture for options in result.session_options)


class TestTranscripts:
    def test_drives_from_calls_and_stamps_each_transcript_with_its_call_start(self) -> None:
        last_value = datetime.now(UTC) - timedelta(days=5)
        result = _driver().run(
            "transcripts",
            [
                ScriptedResponse(
                    json={
                        "calls": [{"id": "c1", "started": "2026-03-01T00:00:00Z"}],
                        "records": {"cursor": "calls-page2"},
                    }
                ),
                ScriptedResponse(json={"callTranscripts": [{"callId": "c1", "transcript": [{"speakerId": "u1"}]}]}),
                ScriptedResponse(json={"calls": [{"id": "c2", "started": "2026-03-02T00:00:00Z"}]}),
                ScriptedResponse(json={"callTranscripts": [{"callId": "c2", "transcript": []}]}),
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value=last_value,
        )

        assert result.raised is None
        # `started` comes from the call the transcript belongs to — the transcript response has no
        # date of its own, so without it the table can't sync incrementally or partition.
        assert result.items == [
            [{"callId": "c1", "transcript": [{"speakerId": "u1"}], "started": "2026-03-01T00:00:00Z"}],
            [{"callId": "c2", "transcript": [], "started": "2026-03-02T00:00:00Z"}],
        ]
        # Every page of the calls walk drives its own transcript request, so a second page of calls
        # isn't dropped.
        assert result.paths == ["/v2/calls", "/v2/calls/transcript", "/v2/calls", "/v2/calls/transcript"]
        assert result.requests[0].param("fromDateTime") == _format_datetime(last_value)
        assert result.requests[2].param("cursor") == "calls-page2"
        # Each request asks only for the ids on the page that drove it.
        assert [request.json()["filter"]["callIds"] for request in result.requests if request.method == "POST"] == [
            ["c1"],
            ["c2"],
        ]

    @parameterized.expand(
        [
            # A call with no start time leaves its transcript with nothing to partition or sync on.
            ("call_without_start_time", [{"id": "c1"}], [{"callId": "c1"}]),
            # A transcript for a call we never asked for has no start time to borrow either.
            (
                "transcript_for_unrequested_call",
                [{"id": "c1", "started": "2026-03-01T00:00:00Z"}],
                [{"callId": "other"}],
            ),
        ]
    )
    def test_unstampable_transcript_stops_the_sync(
        self, _name: str, calls: list[dict], transcripts: list[dict]
    ) -> None:
        result = _driver().run(
            "transcripts",
            [ScriptedResponse(json={"calls": calls}), ScriptedResponse(json={"callTranscripts": transcripts})],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime.now(UTC) - timedelta(days=5),
        )
        # Writing the row with `started=None` would bury it in the fallback partition and keep
        # it out of the watermark, so no later run would ever correct it.
        assert isinstance(result.raised, ValueError)


class TestDateFilteredStats:
    @time_machine.travel("2026-03-10T15:00:00Z", tick=False)
    def test_interaction_stats_request_one_day_at_a_time_and_stamp_the_day(self) -> None:
        result = _driver().run(
            "interaction_stats",
            [
                ScriptedResponse(json={"peopleInteractionStats": [{"userId": "u1"}]}),
                ScriptedResponse(
                    status=404, body=b'{"errors":["No users found corresponding to the provided filters"]}'
                ),
                ScriptedResponse(json={"peopleInteractionStats": [{"userId": "u1"}, {"userId": "u2"}]}),
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2026, 3, 7),
        )

        assert result.raised is None
        # Gong aggregates over the whole range it is asked for, so one-day windows are what make
        # each row one user's stats for one day.
        assert [request.json()["filter"] for request in result.requests] == [
            {"fromDate": "2026-03-06", "toDate": "2026-03-07"},
            {"fromDate": "2026-03-07", "toDate": "2026-03-08"},
            {"fromDate": "2026-03-08", "toDate": "2026-03-09"},
        ]
        assert result.items == [
            [{"userId": "u1", "day": "2026-03-06"}],
            [{"userId": "u1", "day": "2026-03-08"}, {"userId": "u2", "day": "2026-03-08"}],
        ]

    @time_machine.travel("2026-03-10T15:00:00Z", tick=False)
    def test_unchanged_cursor_stops_the_sync(self) -> None:
        page = {"answeredScorecards": [{"answeredScorecardId": 1}], "records": {"cursor": "same"}}
        result = _driver().run(
            "answered_scorecards",
            [ScriptedResponse(json=page), ScriptedResponse(json=page)],
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-03-05T18:30:00Z",
        )

        assert isinstance(result.raised, ValueError)
        assert len(result.requests) == 2

    @time_machine.travel("2026-03-10T15:00:00Z", tick=False)
    def test_daily_activity_turns_each_users_days_into_rows(self) -> None:
        result = _driver().run(
            "daily_activity",
            [
                ScriptedResponse(
                    json={
                        "usersDetailedActivities": [
                            {
                                "userId": "u1",
                                "userEmailAddress": "one@example.com",
                                "userDailyActivityStats": [
                                    {"fromDate": "2026-03-07T00:00:00-08:00", "callsAsHost": ["c1"]},
                                    {"fromDate": "2026-03-08T00:00:00-08:00", "callsAsHost": []},
                                ],
                            },
                            {"userId": "u2", "userEmailAddress": "two@example.com", "userDailyActivityStats": None},
                        ]
                    }
                ),
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-03-07T08:00:00Z",
        )

        assert result.raised is None
        assert [request.json() for request in result.requests] == [
            {"filter": {"fromDate": "2026-03-06", "toDate": "2026-03-09"}}
        ]
        assert result.items == [
            [
                {
                    "userId": "u1",
                    "userEmailAddress": "one@example.com",
                    "fromDate": "2026-03-07T00:00:00-08:00",
                    "callsAsHost": ["c1"],
                },
                {
                    "userId": "u1",
                    "userEmailAddress": "one@example.com",
                    "fromDate": "2026-03-08T00:00:00-08:00",
                    "callsAsHost": [],
                },
            ]
        ]


class TestFanOut:
    def test_library_folder_calls_are_stamped_with_their_folder_and_an_emptied_folder_is_skipped(self) -> None:
        result = _driver().run(
            "library_folder_calls",
            [
                ScriptedResponse(json={"folders": [{"id": "f1"}, {"id": "f2"}]}),
                ScriptedResponse(status=404, body=b'{"errors":["No folders found for the specified period"]}'),
                ScriptedResponse(json={"id": "f2", "calls": [{"id": "c1", "created": "2026-01-01T00:00:00Z"}]}),
            ],
        )

        assert result.raised is None
        assert result.paths == ["/v2/library/folders", "/v2/library/folder-content", "/v2/library/folder-content"]
        assert result.params("folderId") == [None, "f1", "f2"]
        assert result.items == [[{"id": "c1", "created": "2026-01-01T00:00:00Z", "folderId": "f2"}]]

    def test_flows_are_listed_per_active_user_and_kept_once(self) -> None:
        company_flow = {"id": "company", "visibility": "Company"}
        result = _driver().run(
            "flows",
            [
                ScriptedResponse(
                    json={
                        "users": [
                            {"id": "u1", "emailAddress": "one@example.com", "active": True},
                            {"id": "u2", "emailAddress": "gone@example.com", "active": False},
                        ],
                        "records": {"cursor": "users2"},
                    }
                ),
                ScriptedResponse(json={"flows": [company_flow, {"id": "mine", "visibility": "Personal"}]}),
                ScriptedResponse(json={"users": [{"id": "u3", "emailAddress": "three@example.com", "active": True}]}),
                ScriptedResponse(json={"flows": [company_flow], "records": {"cursor": "flows2"}}),
                ScriptedResponse(json={"flows": [{"id": "shared", "visibility": "Shared"}]}),
            ],
        )

        assert result.raised is None
        assert result.paths == ["/v2/users", "/v2/flows", "/v2/users", "/v2/flows", "/v2/flows"]
        assert result.params("flowOwnerEmail") == [
            None,
            "one@example.com",
            None,
            "three@example.com",
            "three@example.com",
        ]
        assert result.params("cursor") == [None, None, "users2", None, "flows2"]
        assert [row["id"] for row in result.rows] == ["company", "mine", "shared"]
