import json
from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from botocore.exceptions import ClientError
from parameterized import parameterized

from products.managed_migrations.backend.api.batch_imports import BatchImportS3SourceCreateSerializer
from products.managed_migrations.backend.models.batch_imports import BatchImport, BatchImportConfigBuilder, ContentType

TEST_ROLE_ARN = "arn:aws:iam::123456789012:role/posthog-import"


class TestBatchImportModel(BaseTest):
    def test_batch_import_creation(self):
        batch_import = BatchImport.objects.create(
            team=self.team, created_by_id=self.user.id, import_config={"test": "config"}, secrets={"secret": "value"}
        )

        self.assertEqual(batch_import.team, self.team)
        self.assertEqual(batch_import.created_by_id, self.user.id)
        self.assertEqual(batch_import.status, BatchImport.Status.RUNNING)
        self.assertEqual(batch_import.import_config, {"test": "config"})
        self.assertIsInstance(batch_import.config, BatchImportConfigBuilder)

    def test_content_type_enum(self):
        self.assertEqual(ContentType.MIXPANEL.value, "mixpanel")
        self.assertEqual(ContentType.CAPTURED.value, "captured")
        self.assertEqual(ContentType.AMPLITUDE.value, "amplitude")

        self.assertEqual(ContentType.MIXPANEL.serialize(), {"type": "mixpanel"})


class TestBatchImportConfigBuilder(BaseTest):
    def setUp(self):
        super().setUp()
        self.batch_import = BatchImport(team=self.team)

    def test_json_lines_configuration(self):
        config = self.batch_import.config.json_lines(ContentType.MIXPANEL, skip_blanks=False)

        expected = {"data_format": {"type": "json_lines", "skip_blanks": False, "content": {"type": "mixpanel"}}}
        self.assertEqual(self.batch_import.import_config, expected)
        self.assertIsInstance(config, BatchImportConfigBuilder)

    def test_from_s3_configuration(self):
        self.batch_import.config.from_s3(
            bucket="my-bucket",
            prefix="data/",
            region="us-east-1",
            access_key_id="AKIATEST",
            secret_access_key="secret123",
        )

        expected_config = {
            "source": {
                "type": "s3",
                "bucket": "my-bucket",
                "prefix": "data/",
                "region": "us-east-1",
                "access_key_id_key": "aws_access_key_id",
                "secret_access_key_key": "aws_secret_access_key",
            }
        }
        self.assertEqual(self.batch_import.import_config, expected_config)
        self.assertEqual(self.batch_import.secrets["aws_access_key_id"], "AKIATEST")
        self.assertEqual(self.batch_import.secrets["aws_secret_access_key"], "secret123")

    @parameterized.expand(
        [
            ("s3", "from_s3", "https://acct123.r2.cloudflarestorage.com"),
            ("s3_gzip", "from_s3_gzip", "http://localhost:9000"),
        ]
    )
    def test_from_s3_with_endpoint_url(self, _name, method, endpoint_url):
        getattr(self.batch_import.config, method)(
            bucket="my-bucket",
            prefix="data/",
            region="auto",
            access_key_id="AKIATEST",
            secret_access_key="secret123",
            endpoint_url=endpoint_url,
        )

        source = self.batch_import.import_config["source"]
        self.assertEqual(source["type"], _name)
        self.assertEqual(source["endpoint_url"], endpoint_url)
        self.assertEqual(source["region"], "auto")

    @parameterized.expand([("s3", "from_s3"), ("s3_gzip", "from_s3_gzip")])
    def test_from_s3_without_endpoint_url_omits_key(self, _name, method):
        getattr(self.batch_import.config, method)(
            bucket="my-bucket",
            prefix="data/",
            region="us-east-1",
            access_key_id="AKIATEST",
            secret_access_key="secret123",
        )

        self.assertNotIn("endpoint_url", self.batch_import.import_config["source"])

    @parameterized.expand([("s3", "from_s3"), ("s3_gzip", "from_s3_gzip")])
    def test_from_s3_with_iam_role(self, _name, method):
        getattr(self.batch_import.config, method)(
            bucket="my-bucket",
            prefix="data/",
            region="us-east-1",
            role_arn=TEST_ROLE_ARN,
            external_id="posthog-us-some-team-uuid",
        )

        source = self.batch_import.import_config["source"]
        self.assertEqual(source["type"], _name)
        self.assertEqual(source["role_arn"], TEST_ROLE_ARN)
        self.assertEqual(source["external_id"], "posthog-us-some-team-uuid")
        self.assertNotIn("access_key_id_key", source)
        self.assertNotIn("secret_access_key_key", source)
        self.assertIsNone(self.batch_import.secrets)

    @parameterized.expand(
        [
            (
                "role_with_endpoint_url",
                {"role_arn": TEST_ROLE_ARN, "external_id": "eid", "endpoint_url": "http://localhost:9000"},
            ),
            ("role_without_external_id", {"role_arn": TEST_ROLE_ARN}),
            (
                "both_auth_methods",
                {"role_arn": TEST_ROLE_ARN, "external_id": "eid", "access_key_id": "ak", "secret_access_key": "sk"},
            ),
            ("no_auth", {}),
        ]
    )
    def test_from_s3_invalid_auth_combinations_raise(self, _name, kwargs):
        with self.assertRaises(ValueError):
            self.batch_import.config.from_s3(bucket="my-bucket", prefix="data/", region="us-east-1", **kwargs)

    def test_chained_configuration(self):
        urls = ["http://example.com/data.json"]

        self.batch_import.config.json_lines(ContentType.AMPLITUDE).from_urls(urls).to_kafka("events_topic", 1000, 60)

        expected_config = {
            "data_format": {"type": "json_lines", "skip_blanks": True, "content": {"type": "amplitude"}},
            "source": {"type": "url_list", "urls_key": "urls", "allow_internal_ips": False, "timeout_seconds": 30},
            "sink": {"type": "kafka", "topic": "events_topic", "send_rate": 1000, "transaction_timeout_seconds": 60},
        }
        self.assertEqual(self.batch_import.import_config, expected_config)
        self.assertEqual(self.batch_import.secrets["urls"], urls)

    def test_to_capture_configuration(self):
        urls = ["http://example.com/data.json"]

        self.batch_import.config.json_lines(ContentType.AMPLITUDE).from_urls(urls).to_capture(send_rate=1000)

        expected_config = {
            "data_format": {"type": "json_lines", "skip_blanks": True, "content": {"type": "amplitude"}},
            "source": {"type": "url_list", "urls_key": "urls", "allow_internal_ips": False, "timeout_seconds": 30},
            "sink": {"type": "capture", "send_rate": 1000},
        }
        self.assertEqual(self.batch_import.import_config, expected_config)
        self.assertEqual(self.batch_import.secrets["urls"], urls)

    def test_with_generate_identify_events_configuration(self):
        """Test that generate_identify_events is added as a top-level config field"""
        self.batch_import.config.json_lines(ContentType.AMPLITUDE).with_generate_identify_events(True)

        expected_config = {
            "data_format": {"type": "json_lines", "skip_blanks": True, "content": {"type": "amplitude"}},
            "generate_identify_events": True,
        }
        self.assertEqual(self.batch_import.import_config, expected_config)

    def test_config_builder_does_not_include_amplitude_fields_by_default(self):
        """Test that config builder doesn't include Amplitude-specific fields unless explicitly set"""
        self.batch_import.config.json_lines(ContentType.MIXPANEL).from_urls(["http://example.com"])

        expected_config = {
            "data_format": {"type": "json_lines", "skip_blanks": True, "content": {"type": "mixpanel"}},
            "source": {"type": "url_list", "urls_key": "urls", "allow_internal_ips": False, "timeout_seconds": 30},
        }
        self.assertEqual(self.batch_import.import_config, expected_config)
        self.assertNotIn("import_events", self.batch_import.import_config)
        self.assertNotIn("generate_identify_events", self.batch_import.import_config)
        self.assertNotIn("generate_group_identify_events", self.batch_import.import_config)

    def test_with_import_events_configuration(self):
        """Test that import_events is added as a top-level config field"""
        self.batch_import.config.json_lines(ContentType.AMPLITUDE).with_import_events(False)

        expected_config = {
            "data_format": {"type": "json_lines", "skip_blanks": True, "content": {"type": "amplitude"}},
            "import_events": False,
        }
        self.assertEqual(self.batch_import.import_config, expected_config)

    def test_with_both_amplitude_options(self):
        """Test that both import_events and generate_identify_events can be set together"""
        self.batch_import.config.json_lines(ContentType.AMPLITUDE).with_import_events(
            True
        ).with_generate_identify_events(True)

        expected_config = {
            "data_format": {"type": "json_lines", "skip_blanks": True, "content": {"type": "amplitude"}},
            "import_events": True,
            "generate_identify_events": True,
        }
        self.assertEqual(self.batch_import.import_config, expected_config)

    def test_with_generate_group_identify_events_configuration(self):
        """Test that generate_group_identify_events is added as a top-level config field"""
        self.batch_import.config.json_lines(ContentType.AMPLITUDE).with_generate_group_identify_events(True)

        expected_config = {
            "data_format": {"type": "json_lines", "skip_blanks": True, "content": {"type": "amplitude"}},
            "generate_group_identify_events": True,
        }
        self.assertEqual(self.batch_import.import_config, expected_config)

    def test_with_all_amplitude_options(self):
        """Test that all Amplitude-specific options can be set together"""
        self.batch_import.config.json_lines(ContentType.AMPLITUDE).with_import_events(
            True
        ).with_generate_identify_events(False).with_generate_group_identify_events(True)

        expected_config = {
            "data_format": {"type": "json_lines", "skip_blanks": True, "content": {"type": "amplitude"}},
            "import_events": True,
            "generate_identify_events": False,
            "generate_group_identify_events": True,
        }
        self.assertEqual(self.batch_import.import_config, expected_config)


class TestBatchImportS3AuthValidation(SimpleTestCase):
    BASE_PAYLOAD = {
        "source_type": "s3",
        "content_type": "captured",
        "s3_bucket": "test-bucket",
        "s3_region": "us-east-1",
    }

    @parameterized.expand(
        [
            ("missing_secret_key", {"access_key": "ak"}, "Both access_key and secret_key"),
            (
                "role_and_keys",
                {"role_arn": TEST_ROLE_ARN, "access_key": "ak", "secret_key": "sk"},
                "not both",
            ),
            ("no_auth", {}, "Authentication is required"),
            (
                "role_with_endpoint_url",
                {"role_arn": TEST_ROLE_ARN, "endpoint_url": "http://localhost:9000"},
                "only works with AWS S3",
            ),
        ]
    )
    def test_invalid_auth_combinations(self, _name, extra, expected_error):
        serializer = BatchImportS3SourceCreateSerializer(data={**self.BASE_PAYLOAD, **extra})
        self.assertFalse(serializer.is_valid())
        self.assertIn(expected_error, str(serializer.errors["non_field_errors"]))

    @parameterized.expand(
        [
            ("not_an_arn", "not-an-arn"),
            ("wrong_service", "arn:aws:s3:::bucket"),
            ("short_account_id", "arn:aws:iam::123:role/foo"),
        ]
    )
    def test_invalid_role_arn_rejected(self, _name, role_arn):
        serializer = BatchImportS3SourceCreateSerializer(data={**self.BASE_PAYLOAD, "role_arn": role_arn})
        self.assertFalse(serializer.is_valid())
        self.assertIn("role_arn", serializer.errors)


class TestBatchImportAPI(APIBaseTest):
    def test_model_creation_only(self):
        batch_import = BatchImport.objects.create(
            team=self.team,
            created_by_id=self.user.id,
            import_config={"source": {"type": "s3"}},
            secrets={"access_key": "test", "secret_key": "secret_test"},
            status=BatchImport.Status.COMPLETED,
        )

        self.assertEqual(batch_import.team, self.team)
        self.assertEqual(batch_import.status, BatchImport.Status.COMPLETED)

        found = BatchImport.objects.filter(team=self.team).first()
        self.assertIsNotNone(found)
        assert found is not None
        self.assertEqual(found.id, batch_import.id)

    def test_cannot_create_multiple_running_imports(self):
        """Test that creating a new batch import fails when there's already a running one for the same team"""
        existing_import = BatchImport.objects.create(
            team=self.team,
            created_by_id=self.user.id,
            import_config={"source": {"type": "s3"}},
            secrets={"access_key": "test", "secret_key": "secret_test"},
            status=BatchImport.Status.RUNNING,
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/managed_migrations",
            {
                "source_type": "s3",
                "content_type": "captured",
                "s3_bucket": "test-bucket",
                "s3_region": "us-east-1",
                "s3_prefix": "data/",
                "access_key": "test-key",
                "secret_key": "test-secret",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Cannot create a new batch import", response.json()["error"])
        self.assertIn(str(existing_import.id), response.json()["detail"])

    def test_amplitude_validation_requires_at_least_one_option(self):
        """Test that Amplitude migrations require at least one of import_events or generate_identify_events"""
        response = self.client.post(
            f"/api/projects/{self.team.id}/managed_migrations",
            {
                "source_type": "amplitude",
                "content_type": "amplitude",
                "start_date": "2023-01-01T00:00:00Z",
                "end_date": "2023-01-02T00:00:00Z",
                "access_key": "test-key",
                "secret_key": "test-secret",
                "import_events": False,
                "generate_identify_events": False,
            },
        )

        self.assertEqual(response.status_code, 400)
        response_data = response.json()
        self.assertIn(
            "At least one of 'Import events' or 'Generate identify events' must be enabled for Amplitude migrations",
            str(response_data),
            f"Expected validation error message not found in response: {response_data}",
        )

    def test_mixpanel_migration_does_not_include_amplitude_specific_fields(self):
        """Test that Mixpanel migrations don't include Amplitude-specific fields in config"""
        response = self.client.post(
            f"/api/projects/{self.team.id}/managed_migrations",
            {
                "source_type": "mixpanel",
                "content_type": "mixpanel",
                "start_date": "2023-01-01T00:00:00Z",
                "end_date": "2023-01-02T00:00:00Z",
                "access_key": "test-key",
                "secret_key": "test-secret",
            },
        )

        self.assertEqual(response.status_code, 201)

        # Get the created batch import and check its config
        batch_import = BatchImport.objects.get(id=response.json()["id"])
        self.assertNotIn("import_events", batch_import.import_config)
        self.assertNotIn("generate_identify_events", batch_import.import_config)
        self.assertNotIn("generate_group_identify_events", batch_import.import_config)

        # Verify sink defaults to capture
        self.assertEqual(batch_import.import_config["sink"]["type"], "capture")
        self.assertEqual(batch_import.import_config["sink"]["send_rate"], 1000)

    def test_amplitude_migration_includes_amplitude_specific_fields(self):
        """Test that Amplitude migrations include import_events and generate_identify_events in config"""
        response = self.client.post(
            f"/api/projects/{self.team.id}/managed_migrations",
            {
                "source_type": "amplitude",
                "content_type": "amplitude",
                "start_date": "2023-01-01T00:00:00Z",
                "end_date": "2023-01-02T00:00:00Z",
                "access_key": "test-key",
                "secret_key": "test-secret",
                "import_events": True,
                "generate_identify_events": False,
            },
        )

        self.assertEqual(response.status_code, 201)

        # Get the created batch import and check its config
        batch_import = BatchImport.objects.get(id=response.json()["id"])
        self.assertIn("import_events", batch_import.import_config)
        self.assertIn("generate_identify_events", batch_import.import_config)
        self.assertEqual(batch_import.import_config["import_events"], True)
        self.assertEqual(batch_import.import_config["generate_identify_events"], False)

    def test_amplitude_migration_with_group_identify_events(self):
        """Test that Amplitude migrations can include generate_group_identify_events in config"""
        response = self.client.post(
            f"/api/projects/{self.team.id}/managed_migrations",
            {
                "source_type": "amplitude",
                "content_type": "amplitude",
                "start_date": "2023-01-01T00:00:00Z",
                "end_date": "2023-01-02T00:00:00Z",
                "access_key": "test-key",
                "secret_key": "test-secret",
                "import_events": True,
                "generate_identify_events": True,
                "generate_group_identify_events": True,
            },
        )

        self.assertEqual(response.status_code, 201)

        # Get the created batch import and check its config
        batch_import = BatchImport.objects.get(id=response.json()["id"])
        self.assertIn("import_events", batch_import.import_config)
        self.assertIn("generate_identify_events", batch_import.import_config)
        self.assertIn("generate_group_identify_events", batch_import.import_config)
        self.assertEqual(batch_import.import_config["import_events"], True)
        self.assertEqual(batch_import.import_config["generate_identify_events"], True)
        self.assertEqual(batch_import.import_config["generate_group_identify_events"], True)

    def test_amplitude_migration_group_identify_events_defaults_to_false(self):
        """Test that generate_group_identify_events defaults to False when not specified"""
        response = self.client.post(
            f"/api/projects/{self.team.id}/managed_migrations",
            {
                "source_type": "amplitude",
                "content_type": "amplitude",
                "start_date": "2023-01-01T00:00:00Z",
                "end_date": "2023-01-02T00:00:00Z",
                "access_key": "test-key",
                "secret_key": "test-secret",
                "import_events": True,
                "generate_identify_events": True,
                # generate_group_identify_events not specified
            },
        )

        self.assertEqual(response.status_code, 201)

        # Get the created batch import and check its config
        batch_import = BatchImport.objects.get(id=response.json()["id"])
        self.assertIn("generate_group_identify_events", batch_import.import_config)
        self.assertEqual(batch_import.import_config["generate_group_identify_events"], False)

    def test_can_create_import_when_no_running_imports(self):
        """Test that creating a new batch import succeeds when there are no running imports"""
        BatchImport.objects.create(
            team=self.team,
            created_by_id=self.user.id,
            import_config={"source": {"type": "s3"}},
            secrets={"access_key": "test", "secret_key": "secret_test"},
            status=BatchImport.Status.COMPLETED,
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/managed_migrations",
            {
                "source_type": "s3",
                "content_type": "captured",
                "s3_bucket": "test-bucket",
                "s3_region": "us-east-1",
                "s3_prefix": "data/",
                "access_key": "test-key",
                "secret_key": "test-secret",
            },
        )

        self.assertEqual(response.status_code, 201)

    def test_can_create_import_when_other_team_has_running_import(self):
        """Test that creating a new batch import succeeds when another team has a running import"""
        from posthog.models import Organization, Team

        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")

        BatchImport.objects.create(
            team=other_team,
            created_by_id=self.user.id,
            import_config={"source": {"type": "s3"}},
            secrets={"access_key": "test", "secret_key": "secret_test"},
            status=BatchImport.Status.RUNNING,
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/managed_migrations",
            {
                "source_type": "s3",
                "content_type": "captured",
                "s3_bucket": "test-bucket",
                "s3_region": "us-east-1",
                "s3_prefix": "data/",
                "access_key": "test-key",
                "secret_key": "test-secret",
            },
        )

        self.assertEqual(response.status_code, 201)

    def test_date_range_validation_exceeds_one_year(self):
        """Test that creating a date range import with more than 1 year fails"""

        start_date = datetime(2023, 1, 1, 0, 0, 0)
        end_date = start_date + timedelta(days=366)

        response = self.client.post(
            f"/api/projects/{self.team.id}/managed_migrations",
            {
                "source_type": "mixpanel",
                "content_type": "mixpanel",
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "access_key": "test-key",
                "secret_key": "test-secret",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Date range cannot exceed 1 year", str(response.json()))

    def test_date_range_validation_within_one_year_succeeds(self):
        """Test that creating a date range import within 1 year succeeds"""

        start_date = datetime(2023, 1, 1, 0, 0, 0)
        end_date = start_date + timedelta(days=300)

        response = self.client.post(
            f"/api/projects/{self.team.id}/managed_migrations",
            {
                "source_type": "amplitude",
                "content_type": "amplitude",
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "access_key": "test-key",
                "secret_key": "test-secret",
            },
        )

        self.assertEqual(response.status_code, 201)

    def test_date_range_validation_end_before_start_fails(self):
        """Test that end date before start date fails validation"""

        start_date = datetime(2023, 6, 1, 0, 0, 0)
        end_date = datetime(2023, 1, 1, 0, 0, 0)

        response = self.client.post(
            f"/api/projects/{self.team.id}/managed_migrations",
            {
                "source_type": "amplitude",
                "content_type": "amplitude",
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "access_key": "test-key",
                "secret_key": "test-secret",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("End date must be after start date", str(response.json()))

    def test_s3_prefix_can_be_empty_string(self):
        """Test that s3_prefix field accepts empty strings"""
        response = self.client.post(
            f"/api/projects/{self.team.id}/managed_migrations",
            {
                "source_type": "s3",
                "content_type": "captured",
                "s3_bucket": "test-bucket",
                "s3_region": "us-east-1",
                "s3_prefix": "",  # Empty string should be allowed
                "access_key": "test-key",
                "secret_key": "test-secret",
            },
        )

        self.assertEqual(response.status_code, 201)

        # Verify the batch import was created with empty prefix
        batch_import = BatchImport.objects.get(id=response.json()["id"])
        self.assertEqual(batch_import.import_config["source"]["prefix"], "")

    def test_s3_prefix_can_be_omitted(self):
        """Test that s3_prefix field can be omitted from the request"""
        response = self.client.post(
            f"/api/projects/{self.team.id}/managed_migrations",
            {
                "source_type": "s3",
                "content_type": "captured",
                "s3_bucket": "test-bucket",
                "s3_region": "us-east-1",
                # s3_prefix omitted entirely
                "access_key": "test-key",
                "secret_key": "test-secret",
            },
        )

        self.assertEqual(response.status_code, 201)

        # Verify the batch import was created
        batch_import = BatchImport.objects.get(id=response.json()["id"])
        self.assertIsNotNone(batch_import)

    def test_s3_gzip_migration_creates_correct_import_config(self):
        """Test that s3_gzip source type creates import_config with type s3_gzip"""
        response = self.client.post(
            f"/api/projects/{self.team.id}/managed_migrations",
            {
                "source_type": "s3_gzip",
                "content_type": "captured",
                "s3_bucket": "test-bucket",
                "s3_region": "us-east-1",
                "s3_prefix": "exports/",
                "access_key": "test-key",
                "secret_key": "test-secret",
            },
        )

        self.assertEqual(response.status_code, 201)
        batch_import = BatchImport.objects.get(id=response.json()["id"])
        self.assertEqual(batch_import.import_config["source"]["type"], "s3_gzip")
        self.assertEqual(batch_import.import_config["source"]["bucket"], "test-bucket")
        self.assertEqual(batch_import.import_config["source"]["prefix"], "exports/")
        self.assertEqual(batch_import.import_config["source"]["region"], "us-east-1")
        self.assertIn("aws_access_key_id", batch_import.secrets)
        self.assertIn("aws_secret_access_key", batch_import.secrets)

    @parameterized.expand(
        [
            ("running_unclaimed", BatchImport.Status.RUNNING, None, "waiting_to_start"),
            ("running_claimed", BatchImport.Status.RUNNING, "worker-uuid-123", "running"),
            ("paused", BatchImport.Status.PAUSED, None, "paused"),
            ("completed", BatchImport.Status.COMPLETED, None, "completed"),
            ("failed", BatchImport.Status.FAILED, None, "failed"),
        ]
    )
    def test_display_status(self, _name, status, lease_id, expected_display_status):
        batch_import = BatchImport.objects.create(
            team=self.team,
            created_by_id=self.user.id,
            import_config={"source": {"type": "s3"}},
            secrets={"access_key": "test"},
            status=status,
            lease_id=lease_id,
        )

        response = self.client.get(f"/api/projects/{self.team.id}/managed_migrations")

        self.assertEqual(response.status_code, 200)
        results = response.json()["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], str(batch_import.id))
        self.assertEqual(results[0]["display_status"], expected_display_status)

    def test_resume_clears_lease_and_backoff(self):
        batch_import = BatchImport.objects.create(
            team=self.team,
            created_by_id=self.user.id,
            import_config={"source": {"type": "s3"}},
            secrets={"access_key": "test"},
            status=BatchImport.Status.PAUSED,
            lease_id="old-lease-uuid",
            leased_until=datetime.now(tz=UTC) + timedelta(hours=1),
            backoff_attempt=5,
            backoff_until=datetime.now(tz=UTC) + timedelta(hours=1),
        )

        response = self.client.post(f"/api/projects/{self.team.id}/managed_migrations/{batch_import.id}/resume")

        self.assertEqual(response.status_code, 200)
        batch_import.refresh_from_db()
        self.assertEqual(batch_import.status, BatchImport.Status.RUNNING)
        self.assertIsNone(batch_import.lease_id)
        self.assertIsNone(batch_import.leased_until)
        self.assertEqual(batch_import.backoff_attempt, 0)
        self.assertIsNone(batch_import.backoff_until)
        self.assertEqual(batch_import.status_message, "Resumed by user")

    @parameterized.expand(
        [
            (
                "patch_import_config",
                "patch",
                {"import_config": {"source": {"type": "date_range_export", "base_url": "https://attacker.example/"}}},
                "import_config",
            ),
            (
                "put_import_config",
                "put",
                {"import_config": {"source": {"type": "date_range_export", "base_url": "https://attacker.example/"}}},
                "import_config",
            ),
            ("patch_status", "patch", {"status": BatchImport.Status.PAUSED}, "status"),
            ("put_status", "put", {"status": BatchImport.Status.PAUSED}, "status"),
        ]
    )
    def test_update_cannot_modify_read_only_fields(self, _name, method, payload, attr):
        original_config = {"source": {"type": "date_range_export", "base_url": "https://mixpanel.com/api"}}
        batch_import = BatchImport.objects.create(
            team=self.team,
            created_by_id=self.user.id,
            import_config=original_config,
            secrets={"api_key": "legit", "secret_key": "legit"},
            status=BatchImport.Status.RUNNING,
        )
        expected = {"import_config": original_config, "status": BatchImport.Status.RUNNING}[attr]

        response = getattr(self.client, method)(
            f"/api/projects/{self.team.id}/managed_migrations/{batch_import.id}",
            payload,
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        batch_import.refresh_from_db()
        self.assertEqual(getattr(batch_import, attr), expected)

    def test_s3_import_with_iam_role_creates_config_without_secrets(self):
        setup_response = self.client.get(f"/api/projects/{self.team.id}/managed_migrations/aws_iam_setup")
        self.assertEqual(setup_response.status_code, 200)
        external_id = setup_response.json()["external_id"]

        response = self.client.post(
            f"/api/projects/{self.team.id}/managed_migrations",
            {
                "source_type": "s3",
                "content_type": "captured",
                "s3_bucket": "test-bucket",
                "s3_region": "us-east-1",
                "s3_prefix": "data/",
                "role_arn": TEST_ROLE_ARN,
            },
        )

        self.assertEqual(response.status_code, 201)
        batch_import = BatchImport.objects.get(id=response.json()["id"])
        source = batch_import.import_config["source"]
        self.assertEqual(source["role_arn"], TEST_ROLE_ARN)
        # The external id shown during setup must be exactly what the import runs with
        self.assertEqual(source["external_id"], external_id)
        self.assertNotIn("access_key_id_key", source)
        self.assertIsNone(batch_import.secrets)

    def test_s3_import_role_and_keys_rejected(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/managed_migrations",
            {
                "source_type": "s3",
                "content_type": "captured",
                "s3_bucket": "test-bucket",
                "s3_region": "us-east-1",
                "role_arn": TEST_ROLE_ARN,
                "access_key": "ak",
                "secret_key": "sk",
            },
        )

        self.assertEqual(response.status_code, 400)

    def test_aws_iam_setup_returns_stable_policy_material(self):
        posthog_role_arn = "arn:aws:iam::999999999999:role/posthog-managed-migrations-import"
        with self.settings(MANAGED_MIGRATIONS_IMPORT_ROLE_ARN=posthog_role_arn):
            first = self.client.get(f"/api/projects/{self.team.id}/managed_migrations/aws_iam_setup").json()
            second = self.client.get(f"/api/projects/{self.team.id}/managed_migrations/aws_iam_setup").json()

        self.assertTrue(first["available"])
        self.assertEqual(first["external_id"], second["external_id"])
        self.assertIn(str(self.team.uuid), first["external_id"])
        trust_policy = json.loads(first["trust_policy"])
        statement = trust_policy["Statement"][0]
        self.assertEqual(statement["Principal"]["AWS"], posthog_role_arn)
        self.assertEqual(statement["Condition"]["StringEquals"]["sts:ExternalId"], first["external_id"])

    def test_aws_iam_setup_unavailable_without_role_arn_setting(self):
        with self.settings(MANAGED_MIGRATIONS_IMPORT_ROLE_ARN=""):
            response = self.client.get(f"/api/projects/{self.team.id}/managed_migrations/aws_iam_setup")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["available"])

    def _post_role_import_with_mocked_sts(self, assume_role_side_effect):
        with (
            self.settings(
                MANAGED_MIGRATIONS_VALIDATE_ROLE_ON_CREATE=True,
                MANAGED_MIGRATIONS_IMPORT_ROLE_ARN="arn:aws:iam::999999999999:role/k8s-batch-import-worker",
            ),
            patch("products.managed_migrations.backend.api.batch_imports.boto3.client") as mock_client,
        ):
            mock_client.return_value.assume_role.side_effect = assume_role_side_effect
            mock_client.return_value.list_objects_v2.return_value = {"KeyCount": 0}
            return self.client.post(
                f"/api/projects/{self.team.id}/managed_migrations",
                {
                    "source_type": "s3",
                    "content_type": "captured",
                    "s3_bucket": "test-bucket",
                    "s3_region": "us-east-1",
                    "role_arn": TEST_ROLE_ARN,
                },
            )

    def test_create_time_role_validation_blocks_unassumable_customer_role(self):
        fake_credentials = {"Credentials": {"AccessKeyId": "a", "SecretAccessKey": "s", "SessionToken": "t"}}
        response = self._post_role_import_with_mocked_sts(
            [
                fake_credentials,  # import role hop succeeds
                ClientError({"Error": {"Code": "AccessDenied", "Message": "Not authorized"}}, "AssumeRole"),
            ]
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("could not assume", response.json()["detail"])
        self.assertEqual(BatchImport.objects.filter(team_id=self.team.id).count(), 0)

    def test_create_time_role_validation_fails_open_when_import_role_unavailable(self):
        response = self._post_role_import_with_mocked_sts(
            ClientError({"Error": {"Code": "AccessDenied", "Message": "Not authorized"}}, "AssumeRole")
        )

        self.assertEqual(response.status_code, 201)

    @parameterized.expand([("s3",), ("s3_gzip",)])
    def test_s3_import_with_endpoint_url(self, source_type):
        response = self.client.post(
            f"/api/projects/{self.team.id}/managed_migrations",
            {
                "source_type": source_type,
                "content_type": "captured",
                "s3_bucket": "test-bucket",
                "s3_region": "auto",
                "s3_prefix": "data/",
                "access_key": "test-key",
                "secret_key": "test-secret",
                "endpoint_url": "http://localhost:9000",
            },
        )

        self.assertEqual(response.status_code, 201)
        batch_import = BatchImport.objects.get(id=response.json()["id"])
        self.assertEqual(batch_import.import_config["source"]["type"], source_type)
        self.assertEqual(batch_import.import_config["source"]["endpoint_url"], "http://localhost:9000")
        self.assertEqual(batch_import.import_config["source"]["region"], "auto")

    def test_s3_import_without_endpoint_url_omits_key(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/managed_migrations",
            {
                "source_type": "s3",
                "content_type": "captured",
                "s3_bucket": "test-bucket",
                "s3_region": "us-east-1",
                "s3_prefix": "data/",
                "access_key": "test-key",
                "secret_key": "test-secret",
            },
        )

        self.assertEqual(response.status_code, 201)
        batch_import = BatchImport.objects.get(id=response.json()["id"])
        self.assertNotIn("endpoint_url", batch_import.import_config["source"])

    def test_s3_import_with_empty_endpoint_url_omits_key(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/managed_migrations",
            {
                "source_type": "s3",
                "content_type": "captured",
                "s3_bucket": "test-bucket",
                "s3_region": "us-east-1",
                "s3_prefix": "data/",
                "access_key": "test-key",
                "secret_key": "test-secret",
                "endpoint_url": "",
            },
        )

        self.assertEqual(response.status_code, 201)
        batch_import = BatchImport.objects.get(id=response.json()["id"])
        self.assertNotIn("endpoint_url", batch_import.import_config["source"])

    def test_s3_import_with_invalid_endpoint_url_returns_400(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/managed_migrations",
            {
                "source_type": "s3",
                "content_type": "captured",
                "s3_bucket": "test-bucket",
                "s3_region": "us-east-1",
                "s3_prefix": "data/",
                "access_key": "test-key",
                "secret_key": "test-secret",
                "endpoint_url": "not-a-url",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["attr"], "endpoint_url")
