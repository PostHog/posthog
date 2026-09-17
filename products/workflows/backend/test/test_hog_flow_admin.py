from unittest.mock import patch

from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.admin.sites import AdminSite
from django.contrib.contenttypes.models import ContentType
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.backends.db import SessionStore
from django.http import HttpRequest
from django.test import RequestFactory, TestCase
from django.utils import timezone

from posthog.models.user import User

from products.workflows.backend.admin.hog_flow_admin import HogFlowAdmin
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow


class TestHogFlowAdminEmailAudit(TestCase):
    def setUp(self) -> None:
        super().setUp()
        _, self.team, self.user = User.objects.bootstrap("Org", "staff@posthog.com", None)
        self.admin = HogFlowAdmin(HogFlow, AdminSite())
        self.flow = HogFlow.objects.create(name="Welcome", team=self.team)

    def _request(self) -> HttpRequest:
        request = RequestFactory().post("/")
        request.user = self.user
        # Admin actions call message_user, which needs a message store on the request.
        request.session = SessionStore()
        # Set on the raw request only in tests; MessageMiddleware owns the attribute at runtime.
        request._messages = FallbackStorage(request)  # type: ignore[attr-defined]
        return request

    def _admin_history(self) -> LogEntry:
        return LogEntry.objects.get(
            content_type=ContentType.objects.get_for_model(HogFlow),
            object_id=str(self.flow.pk),
        )

    @patch("products.workflows.backend.admin.hog_flow_admin.pause_workflow_email_sending", return_value=True)
    def test_manual_pause_records_admin_history(self, _mock_pause: object) -> None:
        self.admin.pause_email_sending(self._request(), HogFlow.objects.filter(pk=self.flow.pk))

        entry = self._admin_history()
        assert entry.user_id == self.user.pk
        assert entry.action_flag == CHANGE
        assert "Paused" in entry.change_message

    @patch("products.workflows.backend.admin.hog_flow_admin.resume_workflow_email_sending", return_value=True)
    def test_manual_resume_records_admin_history(self, _mock_resume: object) -> None:
        self.flow.email_sending_paused_at = timezone.now()
        self.flow.save(update_fields=["email_sending_paused_at"])

        self.admin.resume_email_sending(self._request(), HogFlow.objects.filter(pk=self.flow.pk))

        entry = self._admin_history()
        assert entry.user_id == self.user.pk
        assert "Resumed" in entry.change_message
