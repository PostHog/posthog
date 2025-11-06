import hmac
import json
import time
import hashlib
from typing import Any

import pytest

from posthog.models.instance_setting import set_instance_setting

from products.enterprise.backend.api.test.base import APILicensedTest


@pytest.mark.skip_on_multitenancy
class TestIntegration(APILicensedTest):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        set_instance_setting("SLACK_APP_SIGNING_SECRET", "not-so-secret")

    def _headers_for_payload(self, payload: Any):
        slack_time = time.time()
        sig_basestring = f"v0:{slack_time}:{json.dumps(payload, separators=(',', ':'))}"

        signature = (
            "v0="
            + hmac.new(
                b"not-so-secret",
                sig_basestring.encode("utf-8"),
                digestmod=hashlib.sha256,
            ).hexdigest()
        )

        return {
            "HTTP_X_SLACK_SIGNATURE": signature,
            "HTTP_X_SLACK_REQUEST_TIMESTAMP": str(slack_time),
        }

    def test_validates_payload(self):
        body = {"type": "url_verification", "challenge": "to-a-duel!"}
        headers = self._headers_for_payload(body)
        res = self.client.post(f"/api/integrations/slack/events", body, **headers)

        assert res.json() == {"challenge": "to-a-duel!"}

    def test_ignores_invalid_payload(self):
        body = {"type": "url_verification", "challenge": "to-a-duel!"}
        headers = self._headers_for_payload(body)

        body["challenge"] = "intercepted!"
        res = self.client.post(f"/api/integrations/slack/events", body, **headers)

        assert res.status_code == 403

    def test_ignores_bad_timing_headers(self):
        body = {"type": "url_verification", "challenge": "to-a-duel!"}
        headers = self._headers_for_payload(body)
        headers["HTTP_X_SLACK_REQUEST_TIMESTAMP"] = "not-a-time"

        res = self.client.post(f"/api/integrations/slack/events", body, **headers)

        assert res.status_code == 403
