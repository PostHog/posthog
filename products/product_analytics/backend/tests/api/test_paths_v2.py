from typing import Any

from posthog.test.base import APIBaseTest

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from posthog.schema import (
    DateRange,
    PathsV2Anchor,
    PathsV2AnchorType,
    PathsV2Filter,
    PathsV2Item,
    PathsV2Query,
    PathsV2StepSource,
)

from products.product_analytics.backend.facade.queries import (
    PATHS_V2_OTHER,
    anchored_segment_to_funnels_query,
    edge_to_funnels_query,
)
from products.product_analytics.backend.presentation.paths_v2 import PathsV2SegmentToFunnelRequestSerializer

DATE_RANGE = DateRange(date_from="2023-03-01", date_to="2023-03-31")


def _query(**filter_overrides: Any) -> dict:
    filter_kwargs: dict[str, Any] = {
        "stepSources": [PathsV2StepSource(event=event) for event in ("a", "b", "c")],
        **filter_overrides,
    }
    return PathsV2Query(dateRange=DATE_RANGE, pathsV2Filter=PathsV2Filter(**filter_kwargs)).model_dump(
        exclude_none=True
    )


def _items(*events: str) -> list[dict]:
    return [{"event": event} for event in events]


class TestSegmentToFunnelRequestValidation(SimpleTestCase):
    @parameterized.expand(
        [
            ("single_item", _items("a")),
            ("too_many_items", _items(*(["a"] * 21))),
            ("item_without_event", [{"event": "a"}, {"label": "no event"}]),
            ("missing_query", None),
        ]
    )
    def test_rejects_invalid_bodies(self, _name: str, items: list[dict] | None) -> None:
        data: dict[str, Any] = {"query": {"kind": "PathsV2Query"}}
        if items is not None:
            data["items"] = items
        else:
            data = {"items": _items("a", "b")}
        serializer = PathsV2SegmentToFunnelRequestSerializer(data=data)
        self.assertFalse(serializer.is_valid())

    def test_accepts_null_and_blank_labels(self) -> None:
        serializer = PathsV2SegmentToFunnelRequestSerializer(
            data={
                "query": {"kind": "PathsV2Query"},
                "items": [{"event": "a", "label": None}, {"event": "b", "label": ""}],
            }
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)


class TestSegmentToFunnelAPI(APIBaseTest):
    def _post(self, query: dict, items: list[dict]):
        return self.client.post(
            f"/api/projects/{self.team.pk}/paths_v2/segment_to_funnel/",
            {"query": query, "items": items},
            format="json",
        )

    def test_open_mode_edge_matches_the_converter(self) -> None:
        response = self._post(_query(), _items("a", "b"))

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        expected = edge_to_funnels_query(
            PathsV2Query.model_validate(_query()), self.team, PathsV2Item(event="a"), PathsV2Item(event="b")
        )
        self.assertEqual(response.json()["funnels_query"], expected.model_dump(exclude_none=True, mode="json"))

    def test_open_mode_rejects_multi_hop_segments(self) -> None:
        response = self._post(_query(), _items("a", "b", "c"))

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("single edge", response.json()["detail"])

    def test_anchored_chain_matches_the_converter(self) -> None:
        query = _query(anchor=PathsV2Anchor(item=PathsV2Item(event="a"), type=PathsV2AnchorType.START))

        response = self._post(query, _items("a", "b", "c"))

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        expected = anchored_segment_to_funnels_query(
            PathsV2Query.model_validate(query),
            self.team,
            [PathsV2Item(event=event) for event in ("a", "b", "c")],
        )
        self.assertEqual(response.json()["funnels_query"], expected.model_dump(exclude_none=True, mode="json"))

    def test_end_anchored_chain_converts_in_forward_time_order(self) -> None:
        # An end-anchored chain arrives anchor-first, i.e. backward in time; the emitted
        # funnel must run forward, ending at the anchor.
        query = _query(anchor=PathsV2Anchor(item=PathsV2Item(event="c"), type=PathsV2AnchorType.END))

        response = self._post(query, _items("c", "b", "a"))

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        series_events = [node["event"] for node in response.json()["funnels_query"]["series"]]
        self.assertEqual(series_events, ["a", "b", "c"])

    def test_anchored_segment_must_start_at_the_anchor(self) -> None:
        query = _query(anchor=PathsV2Anchor(item=PathsV2Item(event="a"), type=PathsV2AnchorType.START))

        response = self._post(query, _items("b", "c"))

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("anchor", response.json()["detail"])

    def test_anchor_guard_normalizes_null_and_empty_labels(self) -> None:
        # For a source without a naming property the converter ignores labels entirely, so a
        # ""-labelled first item must still match a null-labelled anchor.
        query = _query(anchor=PathsV2Anchor(item=PathsV2Item(event="a"), type=PathsV2AnchorType.START))

        response = self._post(query, [{"event": "a", "label": ""}, {"event": "b"}])

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())

    @parameterized.expand(
        [
            ("other_row_item", _items("a", PATHS_V2_OTHER)),
            ("event_without_step_source", _items("a", "unknown-event")),
        ]
    )
    def test_inconvertible_items_return_400(self, _name: str, items: list[dict]) -> None:
        response = self._post(_query(), items)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_paths_query_returns_400(self) -> None:
        response = self._post({"kind": "TrendsQuery", "series": []}, _items("a", "b"))

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
