import uuid

import pytest
from unittest.mock import patch

from django.test import SimpleTestCase

from posthog.models import Team

from products.notifications.backend.logic import publish_resource_edited
from products.notifications.backend.resolvers import RecipientsResolver


class TestRecipientsResolverUnit(SimpleTestCase):
    def test_resolve_unknown_target_type_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown target type"):
            RecipientsResolver().resolve("nonexistent_type", "123", 1)  # type: ignore[arg-type]


class TestPublishResourceEditedUnit(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.team = Team(id=1, organization_id=uuid.uuid4())

    @patch("products.notifications.backend.logic.posthoganalytics.feature_enabled", return_value=False)
    @patch("products.notifications.backend.logic.get_producer")
    def test_noops_when_flag_disabled(self, mock_get_producer, mock_ff) -> None:
        publish_resource_edited(
            team=self.team,
            resource_type="HogFlow",
            resource_id="flow-123",
            updated_at="2026-06-16T00:00:00+00:00",
        )

        mock_get_producer.assert_not_called()

    @patch("products.notifications.backend.logic.posthoganalytics.feature_enabled", return_value=True)
    @patch("products.notifications.backend.logic.get_producer")
    @patch.object(RecipientsResolver, "resolve", return_value=[])
    def test_noops_when_no_recipients(self, mock_resolve, mock_get_producer, mock_ff) -> None:
        publish_resource_edited(
            team=self.team,
            resource_type="HogFlow",
            resource_id="flow-123",
            updated_at="2026-06-16T00:00:00+00:00",
        )

        mock_get_producer.assert_not_called()
