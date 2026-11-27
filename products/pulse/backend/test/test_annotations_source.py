from datetime import timedelta
from typing import Any

from posthog.test.base import BaseTest

from django.utils import timezone

from parameterized import parameterized

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.annotations.backend.facade import testing as annotations_testing
from products.annotations.backend.facade.enums import AnnotationScope
from products.pulse.backend.config import DEFAULT_BRIEF_SETTINGS
from products.pulse.backend.models import BriefConfig
from products.pulse.backend.sources.annotations import AnnotationsSource
from products.pulse.backend.sources.base import EvidenceRef, EvidenceType, SourceItem

_DEFAULT_MAX_ANNOTATIONS = DEFAULT_BRIEF_SETTINGS.max_annotations


class TestAnnotationsGather(BaseTest):
    def _gather(self, config: BriefConfig | None = None, lookback_days: int = 7) -> list[SourceItem]:
        return AnnotationsSource().gather(
            self.team,
            config,
            lookback_days,
            UserAccessControl(user=self.user, team=self.team),
        )

    def _annotation(self, days_ago: float = 1, **kwargs: Any) -> int:
        fields: dict[str, Any] = {
            "team_id": self.team.id,
            "organization_id": self.organization.id,
            "content": "Shipped v2.3",
            "scope": AnnotationScope.PROJECT,
            "date_marker": timezone.now() - timedelta(days=days_ago),
            **kwargs,
        }
        return annotations_testing.create_annotation(**fields)

    def test_gather_returns_context_item(self) -> None:
        annotation_id = self._annotation()

        items = self._gather()

        assert len(items) == 1
        item = items[0]
        assert item.source == "annotations"
        assert item.kind == "context"
        assert item.title == "Shipped v2.3"
        assert item.metrics == {}
        assert item.evidence == [
            EvidenceRef(type=EvidenceType.ANNOTATION, ref=str(annotation_id), label="Shipped v2.3", url="")
        ]
        assert item.fingerprint_hint == f"annotation:{annotation_id}"

    @parameterized.expand([("in_period", 1, 1), ("before_period", 8, 0)])
    def test_gather_reads_the_lookback_window(self, _name: str, days_ago: float, expected_count: int) -> None:
        self._annotation(days_ago=days_ago)

        items = self._gather(lookback_days=7)

        assert len(items) == expected_count

    def test_cap_keeps_newest(self) -> None:
        for hours_ago in range(_DEFAULT_MAX_ANNOTATIONS + 3):
            self._annotation(days_ago=hours_ago / 24, content=f"annotation {hours_ago}")

        items = self._gather()

        assert len(items) == _DEFAULT_MAX_ANNOTATIONS
        assert items[0].title == "annotation 0"
        assert all(item.title != f"annotation {_DEFAULT_MAX_ANNOTATIONS}" for item in items)

    def test_config_overrides_cap_per_request(self) -> None:
        for i in range(5):
            self._annotation(days_ago=i / 24, content=f"annotation {i}")

        config = BriefConfig(team=self.team, settings={"max_annotations": 2})
        items = self._gather(config)

        assert len(items) == 2

    def test_long_content_truncated_in_title(self) -> None:
        self._annotation(content="x" * 300)

        items = self._gather()

        assert len(items[0].title) == 100
        assert items[0].description.startswith("x" * 200)
