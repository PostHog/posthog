from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

import requests
from parameterized import parameterized

from products.growth.backend.audit_skills import get_audit_skill
from products.skills.backend.facade.api import SkillPrompt


@override_settings(CLOUD_DEPLOYMENT="EU", GROWTH_ACCOUNT_AUDIT_US_API_KEY="test-us-skill-key")
class TestAuditSkills(SimpleTestCase):
    @override_settings(CLOUD_DEPLOYMENT="US", GROWTH_ENRICHMENT_INTERNAL_TEAM_ID=1)
    def test_us_reads_team_two_locally(self) -> None:
        with patch(
            "products.growth.backend.audit_skills.get_skill_prompt", return_value=SkillPrompt(body="Audit", version=2)
        ) as read:
            self.assertEqual(get_audit_skill("onboarding-audit"), SkillPrompt(body="Audit", version=2))
        read.assert_called_once_with(team_id=2, skill_name="onboarding-audit")

    def test_eu_reads_the_complete_us_skill(self) -> None:
        body = "Audit instructions. " * 1000
        with (
            patch("products.growth.backend.audit_skills.get_skill_prompt") as local_read,
            patch("products.growth.backend.audit_skills.requests.get") as get,
        ):
            get.return_value.status_code = 200
            get.return_value.json.return_value = {"body": body, "version": 3, "files": [], "body_next_offset": None}
            self.assertEqual(get_audit_skill("onboarding-audit"), SkillPrompt(body=body, version=3))
        local_read.assert_not_called()
        get.assert_called_once_with(
            "https://us.posthog.com/api/projects/2/llm_skills/name/onboarding-audit/",
            headers={"Authorization": "Bearer test-us-skill-key"},
            params={"body_length": 65536},
            timeout=(3, 10),
            allow_redirects=False,
        )

    @parameterized.expand(
        [
            (404, {}),
            (200, {"body": " "}),
            (200, {"body": "é" * 32769}),
            (200, {"body_next_offset": 8000}),
            (200, {"files": [{"path": "references/checklist.md"}]}),
        ]
    )
    def test_rejects_missing_or_incomplete_skills(self, status: int, changes: dict[str, object]) -> None:
        with patch("products.growth.backend.audit_skills.requests.get") as get:
            get.return_value.status_code = status
            get.return_value.json.return_value = {
                "body": "Audit",
                "version": 1,
                "files": [],
                "body_next_offset": None,
                **changes,
            }
            self.assertIsNone(get_audit_skill("onboarding-audit"))

    @parameterized.expand(
        [(requests.Timeout("timeout"),), (requests.HTTPError("unauthorized", response=requests.Response()),)]
    )
    def test_us_failure_does_not_fall_back_to_eu(self, error: requests.RequestException) -> None:
        with (
            patch("products.growth.backend.audit_skills.get_skill_prompt") as local_read,
            patch("products.growth.backend.audit_skills.requests.get", side_effect=error),
            self.assertRaises(type(error)),
        ):
            get_audit_skill("onboarding-audit")
        local_read.assert_not_called()

    @override_settings(GROWTH_ACCOUNT_AUDIT_US_API_KEY="")
    def test_missing_us_key_fails_closed(self) -> None:
        with patch("products.growth.backend.audit_skills.requests.get") as get, self.assertRaises(RuntimeError):
            get_audit_skill("onboarding-audit")
        get.assert_not_called()
