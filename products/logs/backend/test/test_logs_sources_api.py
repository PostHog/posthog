from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

import yaml
from parameterized import parameterized
from rest_framework import status

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.team import Team

from products.logs.backend.cloud_sources.aws_firehose import (
    FIREHOSE_ENDPOINT_PATH,
    LOG_GROUP_PLACEHOLDER,
    TEMPLATE_PATH,
    quick_create_url,
    stack_name_for,
)
from products.logs.backend.models import LogsSource
from products.logs.backend.presentation.views.sources_api import LogsSourceSerializer
from products.logs.backend.source_health import SourceHealth

NOW = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)


class TestLogsSourceSerializerValidation(SimpleTestCase):
    @parameterized.expand(
        [
            ("bad_region", {"region": "virginia"}),
            ("missing_region", {"default_labels": {"env": "prod"}}),
        ]
    )
    def test_rejects_invalid_config(self, _name: str, config: dict) -> None:
        serializer = LogsSourceSerializer(data={"name": "prod", "provider": "aws_cloudwatch", "config": config})
        assert not serializer.is_valid()
        assert "config" in serializer.errors

    def test_mode_is_not_writable(self) -> None:
        serializer = LogsSourceSerializer(
            data={"name": "prod", "provider": "aws_cloudwatch", "mode": "pull", "config": {"region": "us-east-1"}}
        )
        assert serializer.is_valid(), serializer.errors
        assert "mode" not in serializer.validated_data

    @parameterized.expand(
        [
            ("disabled_wins", False, NOW - timedelta(minutes=1), "disabled"),
            ("never_received", True, None, "waiting"),
            ("recent_hour_bucket", True, NOW - timedelta(minutes=90), "receiving"),
            ("old", True, NOW - timedelta(hours=3), "stale"),
        ]
    )
    def test_source_status(self, _name: str, enabled: bool, last_received_at: datetime | None, expected: str) -> None:
        health = SourceHealth(last_received_at=last_received_at, records_received_24h=1, records_dropped_24h=0)
        assert health.status(enabled=enabled, now=NOW) == expected


class TestLogsSourcesAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.base_url = f"/api/projects/{self.team.pk}/logs/sources/"

    def _payload(self, **overrides) -> dict:
        payload = {
            "name": "Production account",
            "provider": "aws_cloudwatch",
            "config": {"region": "us-east-1", "default_labels": {"env": "prod"}},
        }
        payload.update(overrides)
        return payload

    def _create_source(self, team: Team | None = None, **overrides) -> LogsSource:
        team = team or self.team
        fields = {"name": "prod", "provider": "aws_cloudwatch", "config": {"region": "us-east-1"}, **overrides}
        return LogsSource.objects.for_team(team.pk).create(team=team, **fields)

    def test_create_scopes_to_team_and_setup_targets_the_source(self) -> None:
        response = self.client.post(self.base_url, self._payload(), format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        source_id = response.json()["id"]
        source = LogsSource.objects.for_team(self.team.pk).get(id=source_id)
        assert source.created_by == self.user
        assert response.json()["mode"] == "push"
        assert response.json()["config"]["default_labels"] == {"env": "prod"}
        assert "secrets" not in response.json()

        setup = self.client.get(f"{self.base_url}{source_id}/setup/")
        assert setup.status_code == status.HTTP_200_OK
        assert setup.json()["endpoint_path"] == f"{FIREHOSE_ENDPOINT_PATH}/{source_id}"
        assert setup.json()["endpoint_url"].endswith(setup.json()["endpoint_path"])
        assert setup.json()["access_key"] == self.team.api_token
        assert setup.json()["quick_create_url"] is None

        with override_settings(LOGS_CLOUD_SOURCES_TEMPLATE_URL="https://templates.example.com/firehose.yaml"):
            link = self.client.get(f"{self.base_url}{source_id}/setup/").json()["quick_create_url"]
        assert link.startswith(
            "https://us-east-1.console.aws.amazon.com/cloudformation/home?region=us-east-1#/stacks/quickcreate?"
        )
        assert "templateURL=https%3A%2F%2Ftemplates.example.com%2Ffirehose.yaml" in link
        assert f"stackName=posthog-logs-production-account-{source_id[:8]}" in link
        assert f"param_PostHogAccessKey={self.team.api_token}" in link

    def test_bad_region_is_rejected_at_the_endpoint(self) -> None:
        response = self.client.post(self.base_url, self._payload(config={"region": "virginia"}), format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "config__region"

    def test_partial_config_patch_merges_into_the_stored_config(self) -> None:
        source = self._create_source(config={"region": "us-east-1", "default_labels": {"env": "prod"}})

        response = self.client.patch(
            f"{self.base_url}{source.id}/", {"config": {"default_labels": {"env": "staging"}}}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        source.refresh_from_db()
        assert source.config == {
            "region": "us-east-1",
            "default_labels": {"env": "staging"},
            "service_name_overrides": {},
        }
        assert response.json()["config"]["region"] == "us-east-1"

    def test_a_row_without_region_still_reads(self) -> None:
        source = self._create_source(config={})
        response = self.client.get(f"{self.base_url}{source.id}/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["config"] == {"region": "", "default_labels": {}, "service_name_overrides": {}}

    def test_a_sibling_teams_source_is_not_visible(self) -> None:
        # Same organization, so the org permission layer lets the request through and the
        # queryset filter is what has to reject it.
        other_team = self.create_team_with_organization(self.organization)
        other = self._create_source(team=other_team, name="theirs")

        assert self.client.get(f"{self.base_url}{other.id}/").status_code == status.HTTP_404_NOT_FOUND
        assert self.client.get(self.base_url).json()["results"] == []

    def test_delete_is_recorded_in_the_activity_log(self) -> None:
        source = self._create_source()
        response = self.client.delete(f"{self.base_url}{source.id}/")
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert ActivityLog.objects.filter(scope="LogsSource", item_id=str(source.id), activity="deleted").exists()

    @parameterized.expand(
        [
            ("recent_bucket", timedelta(0), "receiving"),
            ("old_bucket", timedelta(hours=5), "stale"),
        ]
    )
    @patch("products.logs.backend.source_health.sync_execute")
    def test_health_reads_source_metrics_for_every_source(
        self, _name: str, age: timedelta, expected_status: str, mock_execute
    ) -> None:
        source = self._create_source()
        silent = self._create_source(name="silent")
        # app_metrics2 truncates to the hour and the driver returns naive datetimes.
        bucket = datetime.now(UTC).replace(minute=0, second=0, microsecond=0, tzinfo=None) - age
        mock_execute.return_value = [(str(source.id), bucket, 120, 3)]

        response = self.client.get(f"{self.base_url}health/")

        assert response.status_code == status.HTTP_200_OK, response.json()
        body = response.json()["sources"]
        assert body[str(source.id)]["status"] == expected_status
        assert body[str(source.id)]["records_received_24h"] == 120
        assert body[str(source.id)]["records_dropped_24h"] == 3
        assert body[str(silent.id)] == {
            "status": "waiting",
            "last_received_at": None,
            "records_received_24h": 0,
            "records_dropped_24h": 0,
        }
        query_params = mock_execute.call_args.args[1]
        assert sorted(query_params["instance_ids"]) == sorted([str(source.id), str(silent.id)])
        assert query_params["team_id"] == self.team.pk

    @patch("products.logs.backend.source_health.sync_execute")
    def test_health_skips_clickhouse_when_there_are_no_sources(self, mock_execute) -> None:
        response = self.client.get(f"{self.base_url}health/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"sources": {}}
        mock_execute.assert_not_called()


class TestAwsFirehoseTemplate(SimpleTestCase):
    def test_quick_create_link_fills_parameters_the_template_declares(self) -> None:
        # CloudFormation short-form tags (!Ref, !GetAtt) are not plain YAML, so keep them as opaque nodes.
        class CfnLoader(yaml.SafeLoader):
            pass

        CfnLoader.add_multi_constructor("!", lambda _loader, _suffix, node: node.value)
        template = yaml.load(TEMPLATE_PATH.read_text(), Loader=CfnLoader)

        link = quick_create_url(
            region="us-east-1",
            template_url="https://templates.example.com/firehose.yaml",
            endpoint_url="https://us.i.posthog.com/i/v1/logs/aws/firehose/abc",
            access_key="phc_test",
            source_name="prod",
            source_id="6f1a2b3c-0000-4000-8000-000000000001",
        )
        assert link is not None
        query = parse_qs(urlsplit(link).fragment.split("?", 1)[1])
        filled = {key.removeprefix("param_") for key in query if key.startswith("param_")}
        assert filled <= set(template["Parameters"])
        assert template["Parameters"]["PostHogAccessKey"]["NoEcho"] is True
        # The link stays deliberately incomplete, so it reads as a helper rather than a one-click
        # provisioning action. The placeholder must also survive encoding to stay readable.
        assert query["param_LogGroupName"] == [LOG_GROUP_PLACEHOLDER]
        assert LOG_GROUP_PLACEHOLDER in link

    @parameterized.expand(
        [
            ("commercial", "eu-central-1", "https://eu-central-1.console.aws.amazon.com/"),
            ("govcloud", "us-gov-west-1", "https://us-gov-west-1.console.amazonaws-us-gov.com/"),
            ("china", "cn-north-1", "https://cn-north-1.console.amazonaws.cn/"),
            ("isolated", "us-iso-east-1", None),
            ("malformed", "virginia/evil", None),
        ]
    )
    def test_quick_create_link_targets_the_region_partition(
        self, _name: str, region: str, expected_prefix: str | None
    ) -> None:
        link = quick_create_url(
            region=region,
            template_url="https://templates.example.com/firehose.yaml",
            endpoint_url="https://eu.i.posthog.com/i/v1/logs/aws/firehose/abc",
            access_key="phc_test",
            source_name="prod",
            source_id="6f1a2b3c-0000-4000-8000-000000000001",
        )
        if expected_prefix is None:
            assert link is None
        else:
            assert link is not None and link.startswith(expected_prefix)

    @parameterized.expand(
        [
            ("plain", "Production account", "posthog-logs-production-account-6f1a2b3c"),
            ("symbols", "prod / eu (2)", "posthog-logs-prod-eu-2-6f1a2b3c"),
            ("empty", "***", "posthog-logs-source-6f1a2b3c"),
            ("long", "x" * 200, f"posthog-logs-{'x' * 106}-6f1a2b3c"),
        ]
    )
    def test_stack_name_is_cloudformation_safe(self, _name: str, source_name: str, expected: str) -> None:
        name = stack_name_for(source_name, "6f1a2b3c-0000-4000-8000-000000000001")
        assert name == expected
        assert len(name) <= 128
