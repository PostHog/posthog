from django.test import SimpleTestCase

from products.web_analytics.backend.heatmap_analysis import PageState, RecordingAnalysis, ReplayClick, group_page_states


def recording(
    image: str = "IMG:0:0:100:50:promotion-a", *, width: int = 1440, visit: str = "window-1:visit-1"
) -> RecordingAnalysis:
    return RecordingAnalysis(
        states=[
            PageState(
                window_id=1,
                timestamp=1000,
                visit_id=visit,
                width=width,
                height=1200,
                signature=["BUTTON:1:2:3:4:", image],
                image="123",
                clicks=[ReplayClick(x=16, y=24, target="BUTTON:1:2:3:4:", timestamp=1001)],
            )
        ]
    )


class TestPageVariants(SimpleTestCase):
    def test_promotions_with_the_same_geometry_are_separate(self) -> None:
        variants = group_page_states({"a": recording(), "b": recording("IMG:0:0:100:50:promotion-b"), "c": recording()})
        assert len(variants) == 2
        assert variants[0].summary()["recordings"] == 2
        assert variants[0].summary()["clicks"] == [{"x": 16, "y": 24, "count": 2}]
        assert variants[1].summary()["clicks"] == [{"x": 16, "y": 24, "count": 1}]

    def test_signatures_that_join_to_the_same_text_get_distinct_ids(self) -> None:
        first, second = recording(), recording()
        first.states[0].signature = ["A", "B:C"]
        second.states[0].signature = ["A:B", "C"]
        variants = group_page_states({"a": first, "b": second})
        assert len({variant.id for variant in variants}) == 2

    def test_viewports_and_repeated_states_do_not_inflate_visits(self) -> None:
        first = recording()
        first.states.append(first.states[0].model_copy(update={"timestamp": 2000, "clicks": []}))
        variants = group_page_states({"a": first, "b": recording(width=375)})
        assert len(variants) == 2
        assert all(variant.summary()["visits"] == 1 for variant in variants)

    def test_removed_sources_remove_their_clicks_and_background(self) -> None:
        first, second = recording(), recording()
        second.states[0].image = "456"
        variants = group_page_states({"a": first, "b": second})
        selected = variants[0].member_id(variants[0].members[0])
        remaining = group_page_states({"b": second})
        assert remaining[0].representative(selected).state.image == "456"
        assert remaining[0].summary(selected)["clicks"] == [{"x": 16, "y": 24, "count": 1}]
        assert remaining[0].summary(selected)["representative_replaced"] is True

    def test_persisted_membership_survives_loss_of_the_cluster_origin(self) -> None:
        first, second = recording(), recording()
        second.states[0].signature.extend([f"A:{i}" for i in range(50)])
        first.states[0].signature = [*second.states[0].signature, "A:extra"]
        variant = group_page_states({"a": first, "b": second})[0]
        assert len(variant.members) == 2
        second.states[0].variant_id = variant.id
        remaining = group_page_states({"b": second})
        assert remaining[0].id == variant.id
        newcomer = recording()
        newcomer.states[0].signature = [*second.states[0].signature, "A:other"]
        joined = group_page_states({"0": newcomer, "b": second})
        assert [(item.id, len(item.members)) for item in joined] == [(variant.id, 2)]

    def test_clicks_without_matching_target_geometry_are_excluded(self) -> None:
        source = recording()
        source.states[0].clicks.append(ReplayClick(x=48, y=56, target="removed-target", timestamp=1002))
        assert group_page_states({"a": source})[0].summary()["clicks"] == [{"x": 16, "y": 24, "count": 1}]
