import urllib.parse

import pytest
from unittest.mock import patch

import structlog

from products.warehouse_sources.sources.hubspot.hubspot import (
    PROPERTY_LENGTH_LIMIT,
    HubspotResumeConfig,
    _backfill_missing_properties,
    _flatten_result,
    _get_properties_str,
    get_rows,
)
from products.warehouse_sources.sources.hubspot.settings import HUBSPOT_API_VERSION_V3
from products.warehouse_sources.sources.sdk import ResumableSourceManager
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, always, scripted_network, source_inputs

logger = structlog.get_logger()


def _manager(endpoint: str) -> ResumableSourceManager[HubspotResumeConfig]:
    # Use it inside `scripted_network`, which gives the manager an in-memory redis.
    return ResumableSourceManager(source_inputs(endpoint), HubspotResumeConfig)


def test_hubspot_get_properties():
    with patch("products.warehouse_sources.sources.hubspot.hubspot._get_property_names") as mock_get_property_names:
        mock_get_property_names.return_value = [
            "address",
            "email",
            "date_of_birth",
        ]
        props_str = _get_properties_str(
            props=["id", "name"],
            api_key="dummy_api_key",
            refresh_token="dummy_refresh_token",
            object_type="contact",
            logger=logger,
        )
    # default props should come first, followed by custom props
    assert props_str == "id,name,address,email,date_of_birth"


def test_hubspot_get_properties_without_custom_props():
    props_str = _get_properties_str(
        props=["id", "name"],
        api_key="dummy_api_key",
        refresh_token="dummy_refresh_token",
        object_type="contact",
        include_custom_props=False,
        logger=logger,
    )
    assert props_str == "id,name"


def test_hubspot_get_properties_when_no_custom_props_exist():
    with patch("products.warehouse_sources.sources.hubspot.hubspot._get_property_names") as mock_get_property_names:
        mock_get_property_names.return_value = [
            "id",
            "name",
        ]
        props_str = _get_properties_str(
            props=["id", "name"],
            api_key="dummy_api_key",
            refresh_token="dummy_refresh_token",
            object_type="contact",
            logger=logger,
        )
    assert props_str == "id,name"


def test_hubspot_get_properties_when_no_default_props_exist():
    with patch("products.warehouse_sources.sources.hubspot.hubspot._get_property_names") as mock_get_property_names:
        mock_get_property_names.return_value = [
            "id",
            "name",
        ]
        props_str = _get_properties_str(
            props=[],
            api_key="dummy_api_key",
            refresh_token="dummy_refresh_token",
            object_type="contact",
            logger=logger,
        )
    assert props_str == "id,name"


def test_flatten_result_backfills_missing_properties():
    result = {
        "id": "123",
        "properties": {
            "email": "test@example.com",
            # firstname and lastname are missing — HubSpot omits them when they have no value
        },
    }
    row = _flatten_result(result)

    # Simulate the backfill logic from get_rows
    expected_properties = ["email", "firstname", "lastname"]
    for prop in expected_properties:
        if prop not in row:
            row[prop] = None

    assert row["id"] == "123"
    assert row["email"] == "test@example.com"
    assert row["firstname"] is None
    assert row["lastname"] is None


def test_get_rows_with_selected_properties_backfills_missing_columns():
    """When HubSpot omits properties from the response, selected_properties ensures they appear as None."""
    mock_api_response = {
        "results": [
            {
                "id": "1",
                "properties": {"email": "a@b.com"},
                # firstname is missing from response
            },
            {
                "id": "2",
                "properties": {"email": "c@d.com", "firstname": "Alice"},
            },
        ],
        "paging": {},
    }

    with (
        patch("products.warehouse_sources.sources.hubspot.hubspot._get_property_names") as mock_get_props,
        scripted_network(always(ScriptedResponse(json=mock_api_response))),
    ):
        mock_get_props.return_value = ["email", "firstname"]

        rows = list(
            get_rows(
                api_key="key",
                refresh_token="token",
                endpoint="contacts",
                logger=logger,
                resumable_source_manager=_manager("contacts"),
                selected_properties=["email", "firstname"],
                api_version=HUBSPOT_API_VERSION_V3,
            )
        )

    assert len(rows) == 1  # one PyArrow table batch
    table = rows[0]
    assert "email" in table.column_names
    assert "firstname" in table.column_names
    # Row 1 should have firstname=None (backfilled), Row 2 should have firstname="Alice"
    firstname_col = table.column("firstname").to_pylist()
    assert firstname_col[0] is None
    assert firstname_col[1] == "Alice"


def test_get_rows_with_selected_properties_filters_invalid():
    """Invalid properties are filtered out before the request."""
    mock_api_response = {
        "results": [
            {"id": "1", "properties": {"email": "a@b.com"}},
        ],
        "paging": {},
    }

    with (
        patch("products.warehouse_sources.sources.hubspot.hubspot._get_property_names") as mock_get_props,
        scripted_network(always(ScriptedResponse(json=mock_api_response))),
        patch.object(logger, "warning") as mock_warning,
    ):
        # Only "email" exists, "nonexistent_prop" does not
        mock_get_props.return_value = ["email", "firstname", "lastname"]

        rows = list(
            get_rows(
                api_key="key",
                refresh_token="token",
                endpoint="contacts",
                logger=logger,
                resumable_source_manager=_manager("contacts"),
                selected_properties=["email", "nonexistent_prop"],
                api_version=HUBSPOT_API_VERSION_V3,
            )
        )

    assert len(rows) == 1
    table = rows[0]
    # email should be present, nonexistent_prop should not
    assert "email" in table.column_names
    assert "nonexistent_prop" not in table.column_names
    # Warning should have been logged about the invalid property
    warning_messages = [str(call) for call in mock_warning.call_args_list]
    assert any("nonexistent_prop" in msg for msg in warning_messages)


def test_get_rows_all_invalid_properties_falls_back_to_defaults():
    """If all selected properties are invalid, falls back to default behavior."""
    mock_api_response = {
        "results": [
            {"id": "1", "properties": {"email": "a@b.com", "firstname": "Test"}},
        ],
        "paging": {},
    }

    with (
        patch("products.warehouse_sources.sources.hubspot.hubspot._get_property_names") as mock_get_props,
        scripted_network(always(ScriptedResponse(json=mock_api_response))),
    ):
        # None of the selected properties exist
        mock_get_props.return_value = ["email", "firstname", "lastname"]

        rows = list(
            get_rows(
                api_key="key",
                refresh_token="token",
                endpoint="contacts",
                logger=logger,
                resumable_source_manager=_manager("contacts"),
                selected_properties=["totally_fake_1", "totally_fake_2"],
                api_version=HUBSPOT_API_VERSION_V3,
            )
        )

    assert len(rows) == 1
    table = rows[0]
    # Should have fallen back to defaults, so no backfill of fake properties
    assert "totally_fake_1" not in table.column_names
    assert "totally_fake_2" not in table.column_names


def test_get_rows_without_selected_properties_uses_defaults():
    """When selected_properties is None, default behavior is unchanged."""
    mock_api_response = {
        "results": [
            {"id": "1", "properties": {"email": "a@b.com"}},
        ],
        "paging": {},
    }

    with (
        patch("products.warehouse_sources.sources.hubspot.hubspot._get_property_names") as mock_get_props,
        scripted_network(always(ScriptedResponse(json=mock_api_response))),
    ):
        mock_get_props.return_value = ["email", "custom_field"]

        rows = list(
            get_rows(
                api_key="key",
                refresh_token="token",
                endpoint="contacts",
                logger=logger,
                resumable_source_manager=_manager("contacts"),
                selected_properties=None,
                api_version=HUBSPOT_API_VERSION_V3,
            )
        )

    assert len(rows) == 1
    # _get_property_names should have been called for custom prop discovery (default behavior)
    mock_get_props.assert_called_once()


def test_hubspot_get_properties_url_length_limit():
    # Create a list of property names that will exceed the URL length limit
    long_props = [f"custom_property_{i}" for i in range(1000)]

    with patch("products.warehouse_sources.sources.hubspot.hubspot._get_property_names") as mock_get_property_names:
        mock_get_property_names.return_value = long_props

        # Capture the warning log
        with patch.object(logger, "warning") as mock_warning:
            props_str = _get_properties_str(
                props=["id", "name"],
                api_key="dummy_api_key",
                refresh_token="dummy_refresh_token",
                object_type="contact",
                logger=logger,
            )
            # check that the default props are included
            assert props_str.split(",")[0] == "id"
            assert props_str.split(",")[1] == "name"

            # Verify the returned string is truncated
            assert len(props_str.split(",")) < len(long_props)
            assert len(urllib.parse.quote(props_str)) <= PROPERTY_LENGTH_LIMIT

            # check that the warning was logged
            mock_warning.assert_called_once()
            assert "Your request to Hubspot is too long to process" in mock_warning.call_args[0][0]


@pytest.mark.parametrize(
    "row, expected_properties, expected_none_keys",
    [
        pytest.param(
            {"name": "Acme", "domain": "acme.com"},
            ["name", "domain", "status"],
            ["status"],
            id="single_missing_prop",
        ),
        pytest.param(
            {"name": "Beta"},
            ["name", "domain", "status", "owner_id"],
            ["domain", "status", "owner_id"],
            id="multiple_missing_props",
        ),
        pytest.param(
            {"name": "Gamma", "domain": "gamma.com", "status": "active"},
            ["name", "domain", "status"],
            [],
            id="no_missing_props",
        ),
        pytest.param(
            {},
            ["name", "domain"],
            ["name", "domain"],
            id="all_props_missing",
        ),
        pytest.param(
            {"name": "Delta"},
            [],
            [],
            id="empty_expected_properties",
        ),
    ],
)
def test_backfill_missing_properties(row, expected_properties, expected_none_keys):
    _backfill_missing_properties(row, expected_properties)

    for prop in expected_properties:
        assert prop in row, f"Property '{prop}' missing after backfill"

    for key in expected_none_keys:
        assert row[key] is None, f"Expected None for '{key}', got {row[key]}"


def test_get_rows_backfills_missing_properties():
    # HubSpot omits the properties that are null on a record
    mock_api_response = {
        "results": [
            {
                "id": "1",
                "properties": {
                    "createdate": "2024-01-01",
                    "domain": "acme.com",
                    "name": "Acme",
                    "custom_field": "value1",
                },
            },
            {
                "id": "2",
                "properties": {
                    "createdate": "2024-02-01",
                    "name": "Beta",
                    # domain and custom_field omitted by HubSpot (null values)
                },
            },
        ],
        "paging": {},
    }

    with (
        patch("products.warehouse_sources.sources.hubspot.hubspot._get_property_names") as mock_props,
        scripted_network(always(ScriptedResponse(json=mock_api_response))),
    ):
        mock_props.return_value = ["createdate", "domain", "name", "custom_field"]

        tables = list(
            get_rows(
                api_key="dummy",
                refresh_token="dummy",
                endpoint="companies",
                logger=logger,
                resumable_source_manager=_manager("companies"),
                include_custom_props=True,
                api_version=HUBSPOT_API_VERSION_V3,
            )
        )

        assert len(tables) == 1
        table = tables[0]

        # Both rows should have all columns, including ones HubSpot omitted
        assert "id" in table.column_names
        assert "domain" in table.column_names
        assert "custom_field" in table.column_names
        assert table.num_rows == 2

        # Second row should have None for omitted properties
        rows = table.to_pylist()
        assert rows[1]["domain"] is None
        assert rows[1]["custom_field"] is None
        # First row should still have its values
        assert rows[0]["domain"] == "acme.com"
        assert rows[0]["custom_field"] == "value1"
