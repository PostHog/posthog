"""Tests for render_hogql_example."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

import products.posthog_ai.scripts.hogql_example as hogql_example_module
from products.posthog_ai.scripts.hogql_example import render_hogql_example

SAMPLE_QUERY = {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageview"}]}


@pytest.fixture(autouse=True)
def _reset_cached_team() -> None:
    hogql_example_module._cached_team = None


@patch("django.conf.settings.DEBUG", False)
def test_raises_when_debug_is_false() -> None:
    with pytest.raises(RuntimeError, match="only available when DEBUG=True"):
        render_hogql_example(SAMPLE_QUERY)


@patch("django.conf.settings.DEBUG", True)
@patch("posthog.models.team.Team.objects.first", return_value=None)
def test_raises_when_no_team(_mock_first: MagicMock) -> None:
    with pytest.raises(RuntimeError, match="requires at least one Team"):
        render_hogql_example(SAMPLE_QUERY)


@patch("posthog.hogql.printer.utils.to_printed_hogql")
@patch("posthog.hogql.filters.replace_filters")
@patch("posthog.hogql_queries.query_runner.get_query_runner")
@patch("posthog.models.team.Team.objects.first")
@patch("django.conf.settings.DEBUG", True)
def test_returns_hogql_string(
    mock_first: MagicMock,
    mock_get_runner: MagicMock,
    mock_replace_filters: MagicMock,
    mock_to_hogql: MagicMock,
) -> None:
    fake_team = MagicMock()
    mock_first.return_value = fake_team

    fake_ast = MagicMock()
    filtered_ast = MagicMock()
    fake_runner = MagicMock()
    fake_runner.to_query.return_value = fake_ast
    mock_get_runner.return_value = fake_runner
    mock_replace_filters.return_value = filtered_ast

    mock_to_hogql.return_value = "SELECT count() FROM events"

    result = render_hogql_example(SAMPLE_QUERY)

    assert result == "SELECT count() FROM events"
    mock_get_runner.assert_called_once_with(SAMPLE_QUERY, fake_team)
    fake_runner.to_query.assert_called_once()
    mock_replace_filters.assert_called_once()
    mock_to_hogql.assert_called_once_with(filtered_ast, fake_team)


@patch("posthog.hogql.printer.utils.to_printed_hogql", return_value="SELECT 1")
@patch("posthog.hogql.filters.replace_filters")
@patch("posthog.hogql_queries.query_runner.get_query_runner")
@patch("posthog.models.team.Team.objects.first")
@patch("django.conf.settings.DEBUG", True)
def test_caches_team_across_calls(
    mock_first: MagicMock,
    mock_get_runner: MagicMock,
    _mock_replace_filters: MagicMock,
    _mock_to_hogql: MagicMock,
) -> None:
    fake_team = MagicMock()
    mock_first.return_value = fake_team
    mock_get_runner.return_value = MagicMock()

    render_hogql_example(SAMPLE_QUERY)
    render_hogql_example(SAMPLE_QUERY)

    mock_first.assert_called_once()
