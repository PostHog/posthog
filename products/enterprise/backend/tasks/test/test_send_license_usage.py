from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseDestroyTablesMixin, _create_event, flush_persons_and_events
from unittest.mock import ANY, Mock, patch

from posthog.models.team import Team

from products.enterprise.backend.api.test.base import LicensedTestMixin
from products.enterprise.backend.models.license import License
from products.enterprise.backend.tasks.send_license_usage import send_license_usage


class SendLicenseUsageTest(LicensedTestMixin, ClickhouseDestroyTablesMixin, APIBaseTest):
    @freeze_time("2021-10-10T23:01:00Z")
    @patch("posthoganalytics.capture")
    @patch("requests.post")
    def test_send_license_usage(self, mock_post, mock_capture):
        self.license.key = "legacy-key"
        self.license.save()
        team2 = Team.objects.create(organization=self.organization)
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id=1,
            timestamp="2021-10-08T14:01:01Z",
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id=1,
            timestamp="2021-10-09T12:01:01Z",
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id=1,
            timestamp="2021-10-09T13:01:01Z",
        )
        _create_event(
            event="$$internal_metrics_shouldnt_be_billed",
            team=self.team,
            distinct_id=1,
            timestamp="2021-10-09T13:01:01Z",
        )
        _create_event(
            event="$pageview",
            team=team2,
            distinct_id=1,
            timestamp="2021-10-09T14:01:01Z",
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id=1,
            timestamp="2021-10-10T14:01:01Z",
        )
        flush_persons_and_events()

        mockresponse = Mock()
        mock_post.return_value = mockresponse
        mockresponse.json = lambda: {"ok": True, "valid_until": "2021-11-10T23:01:00Z"}

        send_license_usage()
        mock_post.assert_called_once_with(
            "https://license.posthog.com/licenses/usage",
            data={"date": "2021-10-09", "key": self.license.key, "events_count": 3},
        )
        mock_capture.assert_called_once_with(
            "send license usage data",
            distinct_id=self.user.distinct_id,
            properties={
                "date": "2021-10-09",
                "events_count": 3,
                "license_keys": [self.license.key],
                "organization_name": "Test",
            },
            groups={"instance": ANY, "organization": str(self.organization.id)},
        )
        self.assertEqual(License.objects.get().valid_until.isoformat(), "2021-11-10T23:01:00+00:00")

    @freeze_time("2021-10-10T23:01:00Z")
    @patch("posthoganalytics.capture")
    @patch("ee.tasks.send_license_usage.sync_execute", side_effect=Exception())
    def test_send_license_error(self, mock_post, mock_capture):
        self.license.key = "legacy-key"
        self.license.save()

        team2 = Team.objects.create(organization=self.organization)
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id=1,
            timestamp="2021-10-08T14:01:01Z",
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id=1,
            timestamp="2021-10-09T12:01:01Z",
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id=1,
            timestamp="2021-10-09T13:01:01Z",
        )
        _create_event(
            event="$$internal_metrics_shouldnt_be_billed",
            team=self.team,
            distinct_id=1,
            timestamp="2021-10-09T13:01:01Z",
        )
        _create_event(
            event="$pageview",
            team=team2,
            distinct_id=1,
            timestamp="2021-10-09T14:01:01Z",
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id=1,
            timestamp="2021-10-10T14:01:01Z",
        )
        flush_persons_and_events()
        with self.assertRaises(Exception):
            send_license_usage()
        mock_capture.assert_called_once_with(
            "send license usage data error",
            distinct_id=self.user.distinct_id,
            properties={
                "error": "",
                "date": "2021-10-09",
                "organization_name": "Test",
            },
            groups={"instance": ANY, "organization": str(self.organization.id)},
        )

    @freeze_time("2021-10-10T23:01:00Z")
    @patch("posthoganalytics.capture")
    @patch("requests.post")
    def test_send_license_usage_already_sent(self, mock_post, mock_capture):
        self.license.key = "legacy-key"
        self.license.save()

        team2 = Team.objects.create(organization=self.organization)
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id=1,
            timestamp="2021-10-08T14:01:01Z",
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id=1,
            timestamp="2021-10-09T12:01:01Z",
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id=1,
            timestamp="2021-10-09T13:01:01Z",
        )
        _create_event(
            event="$$internal_metrics_shouldnt_be_billed",
            team=self.team,
            distinct_id=1,
            timestamp="2021-10-09T13:01:01Z",
        )
        _create_event(
            event="$pageview",
            team=team2,
            distinct_id=1,
            timestamp="2021-10-09T14:01:01Z",
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id=1,
            timestamp="2021-10-10T14:01:01Z",
        )
        mockresponse = Mock()
        mock_post.return_value = mockresponse
        mockresponse.ok = False
        mockresponse.status_code = 400
        mockresponse.json = lambda: {
            "code": "already_sent",
            "error": "Usage data for this period has already been sent.",
        }
        flush_persons_and_events()
        send_license_usage()
        mock_capture.assert_not_called()

    @freeze_time("2021-10-10T23:01:00Z")
    @patch("posthoganalytics.capture")
    @patch("requests.post")
    def test_send_license_not_found(self, mock_post, mock_capture):
        self.license.key = "legacy-key"
        self.license.save()

        team2 = Team.objects.create(organization=self.organization)
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id=1,
            timestamp="2021-10-08T14:01:01Z",
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id=1,
            timestamp="2021-10-09T12:01:01Z",
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id=1,
            timestamp="2021-10-09T13:01:01Z",
        )
        _create_event(
            event="$$internal_metrics_shouldnt_be_billed",
            team=self.team,
            distinct_id=1,
            timestamp="2021-10-09T13:01:01Z",
        )
        _create_event(
            event="$pageview",
            team=team2,
            distinct_id=1,
            timestamp="2021-10-09T14:01:01Z",
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id=1,
            timestamp="2021-10-10T14:01:01Z",
        )
        flush_persons_and_events()
        flush_persons_and_events()

        mockresponse = Mock()
        mock_post.return_value = mockresponse
        mockresponse.status_code = 404
        mockresponse.ok = False
        mockresponse.json = lambda: {"code": "not_found"}
        mockresponse.content = ""

        send_license_usage()

        mock_capture.assert_called_once_with(
            "send license usage data error",
            distinct_id=self.user.distinct_id,
            properties={
                "error": "",
                "date": "2021-10-09",
                "organization_name": "Test",
                "status_code": 404,
                "events_count": 3,
            },
            groups={"instance": ANY, "organization": str(self.organization.id)},
        )
        self.assertEqual(License.objects.get().valid_until.isoformat(), "2021-10-10T22:01:00+00:00")

    @freeze_time("2021-10-10T23:01:00Z")
    @patch("posthoganalytics.capture")
    @patch("requests.post")
    def test_send_license_not_triggered_for_v2_licenses(self, mock_post, mock_capture):
        self.license.key = "billing-service::v2-key"
        self.license.save()

        send_license_usage()

        assert mock_capture.call_count == 0


class SendLicenseUsageNoLicenseTest(APIBaseTest):
    @freeze_time("2021-10-10T23:01:00Z")
    @patch("requests.post")
    def test_no_license(self, mock_post):
        # Same test, we just don't include the LicensedTestMixin so no license
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id=1,
            timestamp="2021-10-08T14:01:01Z",
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id=1,
            timestamp="2021-10-09T12:01:01Z",
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id=1,
            timestamp="2021-10-09T13:01:01Z",
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id=1,
            timestamp="2021-10-09T14:01:01Z",
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id=1,
            timestamp="2021-10-10T14:01:01Z",
        )

        flush_persons_and_events()

        send_license_usage()

        self.assertEqual(mock_post.call_count, 0)
