import datetime as dt

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.pinterest_ads.pinterest_ads import (
    ANALYTICS_RESUME_KIND,
    ENTITY_RESUME_KIND,
    PinterestAdsResumeConfig,
    _iter_analytics_rows,
    _iter_entity_rows,
    _iter_targeting_analytics_rows,
    _parse_targeting_analytics_rows,
    pinterest_ads_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pinterest_ads.settings import (
    ANALYTICS_ENDPOINT_PATHS,
    ANALYTICS_ENTITY_SOURCES,
    ANALYTICS_ID_PARAM_NAMES,
    ENTITY_ENDPOINT_PATHS,
    PINTEREST_ADS_CONFIG,
    TARGETING_ANALYTICS_ENDPOINT_PATHS,
    TARGETING_ANALYTICS_ID_COLUMNS,
    EndpointType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pinterest_ads.source import PinterestAdsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.pinterest_ads.utils import (
    _make_request,
    build_session,
    fetch_account_currency,
    fetch_analytics,
    fetch_entities,
    fetch_entity_ids,
    get_date_range,
    list_ad_accounts,
)


def _make_resume_manager(
    *,
    can_resume: bool = False,
    state: PinterestAdsResumeConfig | None = None,
) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = can_resume
    manager.load_state.return_value = state
    return manager


class TestGetDateRange:
    @pytest.mark.parametrize(
        "last_value,expected_start",
        [
            (dt.datetime(2024, 3, 15, 14, 30, 0), "2024-03-15"),
            (dt.date(2024, 3, 15), "2024-03-15"),
            ("2024-03-15", "2024-03-15"),
        ],
    )
    def test_incremental_values(self, last_value, expected_start):
        start_date, end_date = get_date_range(True, last_value)

        assert start_date == expected_start
        assert end_date == dt.datetime.now().strftime("%Y-%m-%d")

    def test_invalid_string_falls_back_to_default(self):
        start_date, _ = get_date_range(True, "invalid-date")

        assert start_date is not None
        assert start_date != "invalid-date"


class TestBuildSession:
    def test_sets_auth_header(self):
        session = build_session("test_token")
        assert session.headers["Authorization"] == "Bearer test_token"
        assert session.headers["Accept"] == "application/json"


class TestFetchEntities:
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.pinterest_ads.utils._make_request")
    def test_multiple_pages(self, mock_request):
        mock_request.side_effect = [
            {"items": [{"id": "1"}], "bookmark": "next_page"},
            {"items": [{"id": "2"}], "bookmark": None},
        ]
        session = mock.MagicMock()

        result = fetch_entities(session, "acc123", "campaigns")
        assert len(result) == 2
        assert mock_request.call_count == 2


class TestListAdAccounts:
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.pinterest_ads.utils._make_request")
    def test_walks_every_bookmarked_page(self, mock_request):
        # A user with many ad accounts gets them across pages: the picker must list all of them, not
        # just the first page, and must pass the previous page's bookmark back to Pinterest.
        mock_request.side_effect = [
            {"items": [{"id": "549770029420"}], "bookmark": "page_2"},
            {"items": [{"id": "111"}], "bookmark": None},
        ]
        session = mock.MagicMock()

        result = list_ad_accounts(session)

        assert [account["id"] for account in result] == ["549770029420", "111"]
        assert mock_request.call_count == 2

        first_call, second_call = mock_request.call_args_list
        assert first_call[0][1] == "https://api.pinterest.com/v5/ad_accounts"
        assert "bookmark" not in first_call[0][2]
        assert second_call[0][1] == "https://api.pinterest.com/v5/ad_accounts"
        assert second_call[0][2]["bookmark"] == "page_2"


class TestFetchEntityIds:
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.pinterest_ads.utils.fetch_entities")
    def test_empty_entities(self, mock_fetch):
        mock_fetch.return_value = []
        session = mock.MagicMock()

        ids = fetch_entity_ids(session, "acc123", "campaign_analytics")
        assert ids == []


class TestFetchAccountCurrency:
    @pytest.mark.parametrize(
        "status_code,json_data,expected",
        [
            (200, {"id": "acc123", "currency": "EUR"}, "EUR"),
            (200, {"id": "acc123"}, None),
            (403, {}, None),
            (500, {}, None),
        ],
    )
    def test_currency_fetch(self, status_code, json_data, expected):
        mock_session = mock.MagicMock()
        mock_response = mock.MagicMock()
        mock_response.status_code = status_code
        mock_response.json.return_value = json_data
        mock_session.get.return_value = mock_response

        result = fetch_account_currency(mock_session, "acc123")
        assert result == expected

    def test_returns_none_on_exception(self):
        mock_session = mock.MagicMock()
        mock_session.get.side_effect = Exception("network error")

        result = fetch_account_currency(mock_session, "acc123")
        assert result is None


class TestFetchAnalytics:
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.pinterest_ads.utils._make_request")
    def test_adds_currency_to_rows(self, mock_request):
        mock_request.return_value = [
            {"CAMPAIGN_ID": "1", "DATE": "2024-01-01", "SPEND_IN_DOLLAR": 5.0},
        ]
        session = mock.MagicMock()

        result = fetch_analytics(
            session, "acc123", "campaign_analytics", ["1"], "2024-01-01", "2024-01-31", currency="EUR"
        )
        assert len(result) == 1
        assert result[0]["currency"] == "EUR"


class TestMakeRequestErrorHandling:
    @pytest.mark.parametrize(
        "status_code",
        [400, 401, 403, 404],
    )
    def test_non_retryable_errors_match_framework(self, status_code):
        """Verify that HTTP errors from _make_request match get_non_retryable_errors patterns."""
        mock_response = mock.MagicMock()
        mock_response.status_code = status_code
        mock_response.raise_for_status.side_effect = requests.HTTPError(
            f"{status_code} Client Error: for url: https://api.pinterest.com/v5/test",
            response=mock_response,
        )

        mock_session = mock.MagicMock()
        mock_session.get.return_value = mock_response

        non_retryable_errors = PinterestAdsSource().get_non_retryable_errors()

        with pytest.raises(requests.HTTPError) as exc_info:
            _make_request(mock_session, "https://api.pinterest.com/v5/test")

        error_msg = str(exc_info.value)
        assert any(pattern in error_msg for pattern in non_retryable_errors), (
            f"HTTP {status_code} error message '{error_msg}' does not match any non-retryable pattern"
        )

    @pytest.mark.parametrize("status_code", [429, 500, 502, 503, 504])
    def test_transient_errors_are_retryable(self, status_code):
        # These are the statuses the shared tracked transport already retries in-process; once
        # that budget is exhausted the error must stay retryable (and out of the non-retryable
        # set) so a self-recovering blip isn't reported as an unclassified error.
        error_class = "Client Error" if status_code == 429 else "Server Error"
        mock_response = mock.MagicMock()
        mock_response.status_code = status_code
        mock_response.raise_for_status.side_effect = requests.HTTPError(
            f"{status_code} {error_class}: for url: https://api.pinterest.com/v5/test",
            response=mock_response,
        )

        mock_session = mock.MagicMock()
        mock_session.get.return_value = mock_response

        source = PinterestAdsSource()

        with pytest.raises(requests.HTTPError) as exc_info:
            _make_request(mock_session, "https://api.pinterest.com/v5/test")

        error_msg = str(exc_info.value)
        assert any(pattern in error_msg for pattern in source.get_retryable_errors())
        assert not any(pattern in error_msg for pattern in source.get_non_retryable_errors())

    def test_chunked_encoding_error_is_retried(self):
        # A mid-stream connection drop while reading the body raises ChunkedEncodingError, which must
        # be retried so a single dropped connection doesn't fail the whole import.
        good_response = mock.MagicMock()
        good_response.raise_for_status.return_value = None
        good_response.json.return_value = {"items": []}

        mock_session = mock.MagicMock()
        mock_session.get.side_effect = [
            requests.exceptions.ChunkedEncodingError(
                "Connection broken: InvalidChunkLength(got length b'', 0 bytes read)"
            ),
            good_response,
        ]

        with mock.patch("tenacity.nap.time.sleep"):
            result = _make_request(mock_session, "https://api.pinterest.com/v5/test")

        assert result == {"items": []}
        assert mock_session.get.call_count == 2

    def test_chunked_encoding_error_eventually_reraises(self):
        mock_session = mock.MagicMock()
        mock_session.get.side_effect = requests.exceptions.ChunkedEncodingError("Connection broken")

        with mock.patch("tenacity.nap.time.sleep"):
            with pytest.raises(requests.exceptions.ChunkedEncodingError):
                _make_request(mock_session, "https://api.pinterest.com/v5/test")

        assert mock_session.get.call_count == 5


class TestPinterestAdsSource:
    def test_unknown_endpoint(self):
        with pytest.raises(ValueError, match="Unknown Pinterest Ads endpoint"):
            pinterest_ads_source(
                ad_account_id="acc123",
                endpoint="nonexistent",
                access_token="token",
                resumable_source_manager=_make_resume_manager(),
                source_logger=mock.MagicMock(),
            )


class TestIterEntityRowsFresh:
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.pinterest_ads.pinterest_ads._make_request"
    )
    def test_saves_state_with_next_bookmark_after_first_yield(self, mock_request):
        mock_request.side_effect = [
            {"items": [{"id": "1"}], "bookmark": "next_page"},
            {"items": [{"id": "2"}], "bookmark": None},
        ]
        manager = _make_resume_manager()
        session = mock.MagicMock()

        yielded = list(_iter_entity_rows(session, "acc123", "campaigns", manager, mock.MagicMock()))

        assert yielded == [[{"id": "1"}], [{"id": "2"}]]
        # Only one page had a next bookmark — only one save
        assert manager.save_state.call_count == 1
        saved = manager.save_state.call_args.args[0]
        assert saved == PinterestAdsResumeConfig(kind=ENTITY_RESUME_KIND, bookmark="next_page")


class TestIterEntityRowsResume:
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.pinterest_ads.pinterest_ads._make_request"
    )
    def test_seeds_bookmark_from_saved_state(self, mock_request):
        mock_request.return_value = {"items": [{"id": "3"}], "bookmark": None}
        manager = _make_resume_manager(
            can_resume=True,
            state=PinterestAdsResumeConfig(kind=ENTITY_RESUME_KIND, bookmark="saved_cursor"),
        )
        session = mock.MagicMock()

        yielded = list(_iter_entity_rows(session, "acc123", "campaigns", manager, mock.MagicMock()))

        assert yielded == [[{"id": "3"}]]
        assert mock_request.call_count == 1
        # Initial request carries the saved bookmark — does NOT re-issue the unbookmarked request
        called_params = mock_request.call_args.args[2]
        assert called_params["bookmark"] == "saved_cursor"


class TestIterAnalyticsRowsFresh:
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.pinterest_ads.pinterest_ads.fetch_account_currency"
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.pinterest_ads.pinterest_ads.fetch_entity_ids"
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.pinterest_ads.pinterest_ads._make_request"
    )
    def test_saves_state_between_batches(self, mock_request, mock_entity_ids, mock_currency):
        mock_entity_ids.return_value = ["1", "2"]
        mock_currency.return_value = None
        mock_request.return_value = [{"CAMPAIGN_ID": "1", "DATE": "2024-01-01"}]
        manager = _make_resume_manager()

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.pinterest_ads.pinterest_ads._chunk_list",
            return_value=[["1"], ["2"]],
        ):
            list(
                _iter_analytics_rows(
                    mock.MagicMock(),
                    "acc123",
                    "campaign_analytics",
                    manager,
                    mock.MagicMock(),
                    False,
                    None,
                )
            )

        # After first batch yield, state points at next batch
        assert manager.save_state.call_count >= 1
        first_saved = manager.save_state.call_args_list[0].args[0]
        assert first_saved.kind == ANALYTICS_RESUME_KIND
        assert first_saved.batch_index == 1
        assert first_saved.date_chunk_index == 0

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.pinterest_ads.pinterest_ads.fetch_entity_ids"
    )
    def test_no_entities_short_circuits(self, mock_entity_ids):
        mock_entity_ids.return_value = []
        manager = _make_resume_manager()

        yielded = list(
            _iter_analytics_rows(
                mock.MagicMock(),
                "acc123",
                "campaign_analytics",
                manager,
                mock.MagicMock(),
                False,
                None,
            )
        )

        assert yielded == []
        manager.save_state.assert_not_called()

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.pinterest_ads.pinterest_ads.fetch_account_currency"
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.pinterest_ads.pinterest_ads.fetch_entity_ids"
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.pinterest_ads.pinterest_ads._make_request"
    )
    def test_malformed_response_does_not_advance_cursor(self, mock_request, mock_entity_ids, mock_currency):
        # First request returns a malformed response (dict instead of list); second returns a valid list.
        # The cursor must not advance past the malformed chunk, so on resume the failed chunk is retried.
        mock_entity_ids.return_value = ["1", "2"]
        mock_currency.return_value = None
        mock_request.side_effect = [
            {"error": "oops"},
            [{"CAMPAIGN_ID": "2", "DATE": "2024-01-01"}],
        ]
        manager = _make_resume_manager()

        with (
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.pinterest_ads.pinterest_ads._chunk_date_range",
                return_value=[("2024-01-01", "2024-01-31")],
            ),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.pinterest_ads.pinterest_ads._chunk_list",
                return_value=[["1"], ["2"]],
            ),
        ):
            yielded = list(
                _iter_analytics_rows(
                    mock.MagicMock(),
                    "acc123",
                    "campaign_analytics",
                    manager,
                    mock.MagicMock(),
                    False,
                    None,
                )
            )

        # Only the second (successful) chunk produced rows.
        assert len(yielded) == 1
        assert yielded[0][0]["campaign_id"] == "2"
        # No save_state happens at all: the first chunk failed (skipped), and the second is the final chunk.
        manager.save_state.assert_not_called()


class TestIterAnalyticsRowsResume:
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.pinterest_ads.pinterest_ads.fetch_account_currency"
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.pinterest_ads.pinterest_ads.fetch_entity_ids"
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.pinterest_ads.pinterest_ads._make_request"
    )
    def test_resumes_at_saved_cursor(self, mock_request, mock_entity_ids, mock_currency):
        mock_entity_ids.return_value = ["1", "2"]
        mock_currency.return_value = "EUR"
        mock_request.return_value = [{"CAMPAIGN_ID": "2", "DATE": "2024-01-05"}]
        manager = _make_resume_manager(
            can_resume=True,
            state=PinterestAdsResumeConfig(
                kind=ANALYTICS_RESUME_KIND,
                batch_index=1,
                date_chunk_index=0,
            ),
        )

        with (
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.pinterest_ads.pinterest_ads._chunk_date_range",
                return_value=[("2024-01-01", "2024-01-31")],
            ),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.pinterest_ads.pinterest_ads._chunk_list",
                return_value=[["1"], ["2"]],
            ),
        ):
            yielded = list(
                _iter_analytics_rows(
                    mock.MagicMock(),
                    "acc123",
                    "campaign_analytics",
                    manager,
                    mock.MagicMock(),
                    False,
                    None,
                )
            )

        # Setup is re-derived on resume — entity list + currency fetched once.
        assert mock_entity_ids.call_count == 1
        assert mock_currency.call_count == 1
        # Resumed at batch 1 → only that batch's chunk is requested (batch 0 is skipped).
        assert mock_request.call_count == 1
        assert yielded[0][0]["currency"] == "EUR"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.pinterest_ads.pinterest_ads.fetch_account_currency"
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.pinterest_ads.pinterest_ads.fetch_entity_ids"
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.pinterest_ads.pinterest_ads._make_request"
    )
    def test_ignores_state_with_wrong_kind(self, mock_request, mock_entity_ids, mock_currency):
        mock_entity_ids.return_value = ["1"]
        mock_currency.return_value = None
        mock_request.return_value = []
        manager = _make_resume_manager(
            can_resume=True,
            state=PinterestAdsResumeConfig(kind=ENTITY_RESUME_KIND, bookmark="stale"),
        )

        list(
            _iter_analytics_rows(
                mock.MagicMock(),
                "acc123",
                "campaign_analytics",
                manager,
                mock.MagicMock(),
                False,
                None,
            )
        )

        # Falls through to fresh path → re-fetches parent entities
        mock_entity_ids.assert_called_once()


class TestEndpointCatalog:
    @pytest.mark.parametrize("endpoint", sorted(PINTEREST_ADS_CONFIG))
    def test_every_endpoint_has_a_path_for_its_type(self, endpoint):
        # A config entry with no matching path only fails once a customer selects the table and the
        # sync KeyErrors, so keep the catalog and the path maps in lockstep here instead.
        config = PINTEREST_ADS_CONFIG[endpoint]

        if config.endpoint_type == EndpointType.ENTITY:
            assert endpoint in ENTITY_ENDPOINT_PATHS
            return

        if config.endpoint_type == EndpointType.ANALYTICS:
            assert endpoint in ANALYTICS_ENDPOINT_PATHS
        else:
            assert endpoint in TARGETING_ANALYTICS_ENDPOINT_PATHS
            assert endpoint in TARGETING_ANALYTICS_ID_COLUMNS

        assert endpoint in ANALYTICS_ID_PARAM_NAMES
        assert ANALYTICS_ENTITY_SOURCES[endpoint] in ENTITY_ENDPOINT_PATHS

    @pytest.mark.parametrize("endpoint", sorted(PINTEREST_ADS_CONFIG))
    def test_primary_keys_identify_a_row(self, endpoint):
        # Fanned-out tables aggregate rows from every parent, so a key that is only unique per
        # parent seeds duplicates that every later merge multi-matches.
        config = PINTEREST_ADS_CONFIG[endpoint]

        if config.endpoint_type == EndpointType.ENTITY:
            assert config.primary_keys == ["id"]
        elif config.endpoint_type == EndpointType.ANALYTICS:
            assert config.primary_keys[-1] == "date"
            assert len(config.primary_keys) == 2
        else:
            assert config.primary_keys[1:] == ["date", "targeting_type", "targeting_value"]


class TestParseTargetingAnalyticsRows:
    @pytest.mark.parametrize(
        "payload,expected",
        [
            (
                {
                    "data": [
                        {
                            "targeting_type": "GENDER",
                            "targeting_value": "female",
                            "metrics": {"CAMPAIGN_ID": "1", "DATE": "2024-01-01", "SPEND_IN_DOLLAR": 5.0},
                        }
                    ]
                },
                [
                    {
                        "campaign_id": "1",
                        "date": "2024-01-01",
                        "spend_in_dollar": 5.0,
                        "targeting_type": "GENDER",
                        "targeting_value": "female",
                    }
                ],
            ),
            # Metrics are nested; an item without them cannot be keyed, so it is dropped rather than
            # yielding a row with no date or entity id.
            ({"data": [{"targeting_type": "GENDER", "targeting_value": "female"}]}, []),
            ({"data": []}, []),
        ],
    )
    def test_flattens_metrics_into_the_row(self, payload, expected):
        assert _parse_targeting_analytics_rows(payload) == expected

    @pytest.mark.parametrize("payload", [[], {"error": "oops"}, {"data": {"not": "a list"}}, None])
    def test_unexpected_payloads_report_failure(self, payload):
        # None tells the caller the chunk failed, so the resume cursor stays put and it is retried.
        assert _parse_targeting_analytics_rows(payload) is None


class TestIterTargetingAnalyticsRows:
    def _run(self, endpoint, mock_request, manager=None):
        with (
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.pinterest_ads.pinterest_ads.fetch_entity_ids",
                return_value=["1"],
            ),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.pinterest_ads.pinterest_ads.fetch_account_currency",
                return_value="USD",
            ),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.pinterest_ads.pinterest_ads._chunk_date_range",
                return_value=[("2024-01-01", "2024-01-31")],
            ),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.pinterest_ads.pinterest_ads._chunk_list",
                return_value=[["1"]],
            ),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.pinterest_ads.pinterest_ads._make_request",
                mock_request,
            ),
        ):
            return list(
                _iter_targeting_analytics_rows(
                    mock.MagicMock(),
                    "acc123",
                    endpoint,
                    manager or _make_resume_manager(),
                    mock.MagicMock(),
                    False,
                    None,
                )
            )

    def test_yields_flattened_rows_with_account_currency(self):
        mock_request = mock.MagicMock(
            return_value={
                "data": [
                    {
                        "targeting_type": "AGE_BUCKET",
                        "targeting_value": "45-49",
                        "metrics": {"CAMPAIGN_ID": "1", "DATE": "2024-01-01", "SPEND_IN_DOLLAR": 5.0},
                    }
                ]
            }
        )

        yielded = self._run("campaign_targeting_analytics", mock_request)

        assert yielded == [
            [
                {
                    "campaign_id": "1",
                    "date": "2024-01-01",
                    "spend_in_dollar": 5.0,
                    "targeting_type": "AGE_BUCKET",
                    "targeting_value": "45-49",
                    "currency": "USD",
                }
            ]
        ]


class TestIterEntityRowsWithoutPagination:
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.pinterest_ads.pinterest_ads._make_request"
    )
    def test_account_endpoint_is_scoped_to_the_configured_account(self, mock_request):
        # The ad accounts table must fetch only the configured account, not list every account the
        # OAuth token can reach. The scoped endpoint returns the object directly, not an `items` list.
        mock_request.return_value = {"id": "acc123", "currency": "EUR"}

        yielded = list(
            _iter_entity_rows(mock.MagicMock(), "acc123", "ad_accounts", _make_resume_manager(), mock.MagicMock())
        )

        assert yielded == [[{"id": "acc123", "currency": "EUR"}]]
        assert mock_request.call_count == 1
        assert mock_request.call_args.args[1] == "https://api.pinterest.com/v5/ad_accounts/acc123"
        assert mock_request.call_args.args[2] == {}
