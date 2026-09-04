import uuid

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from posthog.models.instance_setting import override_instance_config

from products.growth.backend.models import OrganizationEnrichment

_URL = "/api/growth_enrichment/rescore/"
_SECRET = "wh_secret_test_value"
_MODULE = "products.growth.backend.api.rescore"


class TestGrowthEnrichmentRescoreAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.enterContext(override_instance_config("GROWTH_RESCORE_WEBHOOK_SECRET", _SECRET))
        self.enterContext(override_instance_config("GROWTH_SIGNUP_ENRICHMENT_ENABLED", True))
        self.enterContext(patch(f"{_MODULE}.get_instance_region", return_value="US"))

    def _post(self, organization_id: str | None, secret: str | None = _SECRET):
        body = {} if organization_id is None else {"organization_id": organization_id}
        if secret is None:
            return self.client.post(_URL, body, format="json")
        return self.client.post(_URL, body, format="json", HTTP_X_POSTHOG_WEBHOOK_SECRET=secret)

    def test_missing_secret_returns_401_and_dispatches_nothing(self):
        with patch(f"{_MODULE}.dispatch_wizard_stamp_rescore") as dispatch_mock:
            response = self._post(str(self.organization.id), secret=None)

        assert response.status_code == 401
        dispatch_mock.assert_not_called()

    def test_wrong_secret_returns_401_and_dispatches_nothing(self):
        with patch(f"{_MODULE}.dispatch_wizard_stamp_rescore") as dispatch_mock:
            response = self._post(str(self.organization.id), secret="not-the-secret")

        assert response.status_code == 401
        dispatch_mock.assert_not_called()

    def test_unconfigured_secret_returns_503(self):
        with override_instance_config("GROWTH_RESCORE_WEBHOOK_SECRET", ""):
            with patch(f"{_MODULE}.dispatch_wizard_stamp_rescore") as dispatch_mock:
                response = self._post(str(self.organization.id))

        assert response.status_code == 503
        dispatch_mock.assert_not_called()

    def test_missing_organization_id_returns_400(self):
        response = self._post(None)

        assert response.status_code == 400

    def test_non_uuid_organization_id_returns_400(self):
        response = self._post("not-a-uuid")

        assert response.status_code == 400

    def test_kill_switch_off_returns_queued_false_disabled(self):
        OrganizationEnrichment.objects.create(organization=self.organization)
        with override_instance_config("GROWTH_SIGNUP_ENRICHMENT_ENABLED", False):
            with patch(f"{_MODULE}.dispatch_wizard_stamp_rescore") as dispatch_mock:
                response = self._post(str(self.organization.id))

        assert response.status_code == 202
        assert response.json() == {"queued": False, "reason": "disabled"}
        dispatch_mock.assert_not_called()

    def test_self_hosted_region_returns_queued_false_disabled(self):
        OrganizationEnrichment.objects.create(organization=self.organization)
        with patch(f"{_MODULE}.get_instance_region", return_value="DEV"):
            with patch(f"{_MODULE}.dispatch_wizard_stamp_rescore") as dispatch_mock:
                response = self._post(str(self.organization.id))

        assert response.status_code == 202
        assert response.json() == {"queued": False, "reason": "disabled"}
        dispatch_mock.assert_not_called()

    def test_no_enrichment_record_returns_queued_false(self):
        assert not OrganizationEnrichment.objects.filter(organization=self.organization).exists()
        with patch(f"{_MODULE}.dispatch_wizard_stamp_rescore") as dispatch_mock:
            response = self._post(str(self.organization.id))

        assert response.status_code == 202
        assert response.json() == {"queued": False, "reason": "no_enrichment_record"}
        dispatch_mock.assert_not_called()

    def test_valid_request_dispatches_and_returns_queued_true(self):
        OrganizationEnrichment.objects.create(organization=self.organization)
        with patch(f"{_MODULE}.dispatch_wizard_stamp_rescore") as dispatch_mock:
            response = self._post(str(self.organization.id))

        assert response.status_code == 202
        assert response.json() == {"queued": True}
        dispatch_mock.assert_called_once_with(str(self.organization.id))

    def test_unknown_organization_id_returns_no_enrichment_record(self):
        with patch(f"{_MODULE}.dispatch_wizard_stamp_rescore") as dispatch_mock:
            response = self._post(str(uuid.uuid4()))

        assert response.status_code == 202
        assert response.json() == {"queued": False, "reason": "no_enrichment_record"}
        dispatch_mock.assert_not_called()
