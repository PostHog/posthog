import pytest
from unittest.mock import MagicMock, patch

import dagster
from dagster import build_op_context

from posthog.models import Organization, Team, User
from posthog.models.file_system.user_product_list import UserProductList

from products.growth.dags.user_product_list import populate_user_product_list, populate_user_product_list_job


def create_mock_s3_resource():
    """Create a mock S3 resource for testing."""
    mock_s3_resource = MagicMock()
    mock_s3_client = MagicMock()
    mock_s3_resource.get_client.return_value = mock_s3_client
    return mock_s3_resource


def build_default_context(op_config: dict, resources: dict | None = None):
    """Build a Dagster op context with default mock S3 resource.

    Args:
        op_config: The op configuration dictionary
        resources: Optional resources dictionary. If not provided or doesn't include 's3',
                   the default mock S3 resource will be added.

    Returns:
        A Dagster OpExecutionContext with the provided config and resources.
    """
    if resources is None:
        resources = {}

    if "s3" not in resources:
        resources = {**resources, "s3": create_mock_s3_resource()}

    return build_op_context(op_config=op_config, resources=resources)


class TestPopulateUserProductListOp:
    @pytest.mark.django_db
    def test_basic_populate_creates_entries(self):
        org = Organization.objects.create(name="Test Org")
        team = Team.objects.create(organization=org, name="Test Team")
        user = User.objects.create(email="test@example.com", first_name="Test", allow_sidebar_suggestions=True)
        user.join(organization=org)

        with patch(
            "products.growth.dags.user_product_list.get_valid_product_paths",
            return_value={"product_analytics", "session_replay"},
        ):
            context = build_default_context(
                op_config={
                    "product_paths": ["product_analytics"],
                }
            )

            populate_user_product_list(context)

            entries = UserProductList.objects.filter(user=user, team=team)
            assert entries.count() == 1
            assert entries.first().product_path == "product_analytics"
            assert entries.first().enabled is True
            assert entries.first().reason is None

            metadata = context.get_output_metadata("result")
            assert metadata["created"].value == 1
            assert metadata["skipped"].value == 0

    @pytest.mark.django_db
    def test_populate_with_reason(self):
        org = Organization.objects.create(name="Test Org")
        team = Team.objects.create(organization=org, name="Test Team")
        user = User.objects.create(email="test@example.com", first_name="Test", allow_sidebar_suggestions=True)
        user.join(organization=org)

        with patch(
            "products.growth.dags.user_product_list.get_valid_product_paths",
            return_value={"product_analytics"},
        ):
            context = build_default_context(
                op_config={
                    "product_paths": ["product_analytics"],
                    "reason": "product_intent",
                }
            )

            populate_user_product_list(context)

            entry = UserProductList.objects.get(user=user, team=team, product_path="product_analytics")
            assert entry.reason == "product_intent"

    @pytest.mark.django_db
    def test_populate_with_reason_text(self):
        org = Organization.objects.create(name="Test Org")
        team = Team.objects.create(organization=org, name="Test Team")
        user = User.objects.create(email="test@example.com", first_name="Test", allow_sidebar_suggestions=True)
        user.join(organization=org)

        with patch(
            "products.growth.dags.user_product_list.get_valid_product_paths",
            return_value={"product_analytics"},
        ):
            context = build_default_context(
                op_config={
                    "product_paths": ["product_analytics"],
                    "reason": "product_intent",
                    "reason_text": "You've been using this product frequently",
                }
            )

            populate_user_product_list(context)

            entry = UserProductList.objects.get(user=user, team=team, product_path="product_analytics")
            assert entry.reason == "product_intent"
            assert entry.reason_text == "You've been using this product frequently"

    @pytest.mark.django_db
    def test_populate_with_reason_text_only(self):
        org = Organization.objects.create(name="Test Org")
        team = Team.objects.create(organization=org, name="Test Team")
        user = User.objects.create(email="test@example.com", first_name="Test", allow_sidebar_suggestions=True)
        user.join(organization=org)

        with patch(
            "products.growth.dags.user_product_list.get_valid_product_paths",
            return_value={"product_analytics"},
        ):
            context = build_default_context(
                op_config={
                    "product_paths": ["product_analytics"],
                    "reason_text": "Custom message for user",
                }
            )

            populate_user_product_list(context)

            entry = UserProductList.objects.get(user=user, team=team, product_path="product_analytics")
            assert entry.reason is None
            assert entry.reason_text == "Custom message for user"

    @pytest.mark.django_db
    def test_populate_respects_allow_sidebar_suggestions_false(self):
        org = Organization.objects.create(name="Test Org")
        team = Team.objects.create(organization=org, name="Test Team")
        user_allowed = User.objects.create(
            email="allowed@example.com",
            first_name="Allowed",
            allow_sidebar_suggestions=True,
        )
        user_disallowed = User.objects.create(
            email="disallowed@example.com",
            first_name="Disallowed",
            allow_sidebar_suggestions=False,
        )
        user_allowed.join(organization=org)
        user_disallowed.join(organization=org)

        with patch(
            "products.growth.dags.user_product_list.get_valid_product_paths",
            return_value={"product_analytics"},
        ):
            context = build_default_context(
                op_config={
                    "product_paths": ["product_analytics"],
                }
            )

            populate_user_product_list(context)

            allowed_entry = UserProductList.objects.filter(user=user_allowed, team=team)
            disallowed_entry = UserProductList.objects.filter(user=user_disallowed, team=team)

            assert allowed_entry.count() == 1
            assert disallowed_entry.count() == 0

            metadata = context.get_output_metadata("result")
            assert metadata["created"].value == 1

    @pytest.mark.django_db
    def test_populate_respects_allow_sidebar_suggestions_null_defaults_to_allowed(self):
        org = Organization.objects.create(name="Test Org")
        team = Team.objects.create(organization=org, name="Test Team")
        user_null = User.objects.create(email="null@example.com", first_name="Null", allow_sidebar_suggestions=None)
        user_null.join(organization=org)

        with patch(
            "products.growth.dags.user_product_list.get_valid_product_paths",
            return_value={"product_analytics"},
        ):
            context = build_default_context(
                op_config={
                    "product_paths": ["product_analytics"],
                }
            )

            populate_user_product_list(context)

            entry = UserProductList.objects.filter(user=user_null, team=team)
            assert entry.count() == 1

    @pytest.mark.django_db
    def test_populate_multiple_products(self):
        org = Organization.objects.create(name="Test Org")
        team = Team.objects.create(organization=org, name="Test Team")
        user = User.objects.create(email="test@example.com", first_name="Test", allow_sidebar_suggestions=True)
        user.join(organization=org)

        with patch(
            "products.growth.dags.user_product_list.get_valid_product_paths",
            return_value={"product_analytics", "session_replay", "feature_flags"},
        ):
            context = build_default_context(
                op_config={
                    "product_paths": ["product_analytics", "session_replay"],
                }
            )

            populate_user_product_list(context)

            entries = UserProductList.objects.filter(user=user, team=team)
            assert entries.count() == 2
            assert set(entries.values_list("product_path", flat=True)) == {
                "product_analytics",
                "session_replay",
            }

            metadata = context.get_output_metadata("result")
            assert metadata["created"].value == 2

    @pytest.mark.django_db
    def test_populate_skips_existing_entries(self):
        org = Organization.objects.create(name="Test Org")
        team = Team.objects.create(organization=org, name="Test Team")
        user = User.objects.create(email="test@example.com", first_name="Test", allow_sidebar_suggestions=True)
        user.join(organization=org)

        UserProductList.objects.create(
            user=user,
            team=team,
            product_path="product_analytics",
            enabled=True,
            reason="product_intent",
        )

        with patch(
            "products.growth.dags.user_product_list.get_valid_product_paths",
            return_value={"product_analytics"},
        ):
            context = build_default_context(
                op_config={
                    "product_paths": ["product_analytics"],
                    "reason": "new_product",
                }
            )

            populate_user_product_list(context)

            entries = UserProductList.objects.filter(user=user, team=team, product_path="product_analytics")
            assert entries.count() == 1
            entry = entries.first()
            assert entry.reason == "product_intent"

            metadata = context.get_output_metadata("result")
            assert metadata["created"].value == 0
            assert metadata["skipped"].value == 1

    @pytest.mark.django_db
    def test_populate_multiple_teams(self):
        org = Organization.objects.create(name="Test Org")
        team1 = Team.objects.create(organization=org, name="Test Team 1")
        team2 = Team.objects.create(organization=org, name="Test Team 2")
        user = User.objects.create(email="test@example.com", first_name="Test", allow_sidebar_suggestions=True)
        user.join(organization=org)

        with patch(
            "products.growth.dags.user_product_list.get_valid_product_paths",
            return_value={"product_analytics"},
        ):
            context = build_default_context(
                op_config={
                    "product_paths": ["product_analytics"],
                }
            )

            populate_user_product_list(context)

            entries_team1 = UserProductList.objects.filter(user=user, team=team1)
            entries_team2 = UserProductList.objects.filter(user=user, team=team2)

            assert entries_team1.count() == 1
            assert entries_team2.count() == 1

            metadata = context.get_output_metadata("result")
            assert metadata["created"].value == 2

    @pytest.mark.django_db
    def test_populate_filters_by_require_existing_product(self):
        org = Organization.objects.create(name="Test Org")
        team = Team.objects.create(organization=org, name="Test Team")
        user_with_product = User.objects.create(
            email="with@example.com", first_name="With", allow_sidebar_suggestions=True
        )
        user_without_product = User.objects.create(
            email="without@example.com",
            first_name="Without",
            allow_sidebar_suggestions=True,
        )
        user_with_product.join(organization=org)
        user_without_product.join(organization=org)

        UserProductList.objects.create(
            user=user_with_product,
            team=team,
            product_path="product_analytics",
            enabled=True,
        )

        with patch(
            "products.growth.dags.user_product_list.get_valid_product_paths",
            return_value={"product_analytics", "session_replay"},
        ):
            context = build_default_context(
                op_config={
                    "product_paths": ["session_replay"],
                    "require_existing_product": "product_analytics",
                }
            )

            populate_user_product_list(context)

            with_entry = UserProductList.objects.filter(
                user=user_with_product, team=team, product_path="session_replay"
            )
            without_entry = UserProductList.objects.filter(
                user=user_without_product, team=team, product_path="session_replay"
            )

            assert with_entry.count() == 1
            assert without_entry.count() == 0

    @pytest.mark.django_db
    def test_populate_fails_with_empty_product_paths(self):
        with patch(
            "products.growth.dags.user_product_list.get_valid_product_paths",
            return_value={"product_analytics"},
        ):
            context = build_default_context(
                op_config={
                    "product_paths": [],
                }
            )

            with pytest.raises(dagster.Failure, match="product_paths cannot be empty"):
                populate_user_product_list(context)

    @pytest.mark.django_db
    def test_populate_fails_with_invalid_product_paths(self):
        with patch(
            "products.growth.dags.user_product_list.get_valid_product_paths",
            return_value={"product_analytics"},
        ):
            context = build_default_context(
                op_config={
                    "product_paths": ["invalid_product"],
                }
            )

            with pytest.raises(dagster.Failure, match="Invalid product paths"):
                populate_user_product_list(context)

    @pytest.mark.django_db
    def test_populate_fails_with_invalid_require_existing_product(self):
        with patch(
            "products.growth.dags.user_product_list.get_valid_product_paths",
            return_value={"product_analytics"},
        ):
            context = build_default_context(
                op_config={
                    "product_paths": ["product_analytics"],
                    "require_existing_product": "invalid_product",
                }
            )

            with pytest.raises(dagster.Failure, match="Invalid require_existing_product"):
                populate_user_product_list(context)

    @pytest.mark.django_db
    def test_populate_fails_with_invalid_reason(self):
        with patch(
            "products.growth.dags.user_product_list.get_valid_product_paths",
            return_value={"product_analytics"},
        ):
            context = build_default_context(
                op_config={
                    "product_paths": ["product_analytics"],
                    "reason": "invalid_reason",
                }
            )

            with pytest.raises(Exception):  # Dagster will fail at config validation time
                populate_user_product_list(context)

    @pytest.mark.django_db
    def test_populate_filters_by_role_at_organization(self):
        org = Organization.objects.create(name="Test Org")
        team = Team.objects.create(organization=org, name="Test Team")
        user_engineering = User.objects.create(
            email="eng@example.com",
            first_name="Engineer",
            allow_sidebar_suggestions=True,
            role_at_organization="engineering",
        )
        user_data = User.objects.create(
            email="data@example.com",
            first_name="Data",
            allow_sidebar_suggestions=True,
            role_at_organization="data",
        )
        user_no_role = User.objects.create(
            email="norole@example.com",
            first_name="NoRole",
            allow_sidebar_suggestions=True,
            role_at_organization=None,
        )
        user_engineering.join(organization=org)
        user_data.join(organization=org)
        user_no_role.join(organization=org)

        with patch(
            "products.growth.dags.user_product_list.get_valid_product_paths",
            return_value={"product_analytics"},
        ):
            context = build_default_context(
                op_config={
                    "product_paths": ["product_analytics"],
                    "role_at_organization": "engineering",
                }
            )

            populate_user_product_list(context)

            eng_entry = UserProductList.objects.filter(user=user_engineering, team=team)
            data_entry = UserProductList.objects.filter(user=user_data, team=team)
            no_role_entry = UserProductList.objects.filter(user=user_no_role, team=team)

            assert eng_entry.count() == 1
            assert data_entry.count() == 0
            assert no_role_entry.count() == 0

            metadata = context.get_output_metadata("result")
            assert metadata["created"].value == 1

    @pytest.mark.django_db
    def test_populate_fails_with_invalid_role_at_organization(self):
        with patch(
            "products.growth.dags.user_product_list.get_valid_product_paths",
            return_value={"product_analytics"},
        ):
            context = build_default_context(
                op_config={
                    "product_paths": ["product_analytics"],
                    "role_at_organization": "invalid_role",
                }
            )

            with pytest.raises(dagster.Failure, match="Invalid role_at_organization"):
                populate_user_product_list(context)

    @pytest.mark.django_db
    def test_populate_filters_by_emails_from_s3(self):
        org = Organization.objects.create(name="Test Org")
        team = Team.objects.create(organization=org, name="Test Team")
        user1 = User.objects.create(
            email="user1@example.com",
            first_name="User1",
            allow_sidebar_suggestions=True,
        )
        user2 = User.objects.create(
            email="user2@example.com",
            first_name="User2",
            allow_sidebar_suggestions=True,
        )
        user3 = User.objects.create(
            email="user3@example.com",
            first_name="User3",
            allow_sidebar_suggestions=True,
        )
        user1.join(organization=org)
        user2.join(organization=org)
        user3.join(organization=org)

        email_list_content = "user1@example.com\nuser2@example.com\n"
        mock_s3_client = MagicMock()
        mock_response = MagicMock()
        mock_response["Body"].read.return_value = email_list_content.encode("utf-8")
        mock_s3_client.get_object.return_value = mock_response

        mock_s3_resource = MagicMock()
        mock_s3_resource.get_client.return_value = mock_s3_client

        with patch(
            "products.growth.dags.user_product_list.get_valid_product_paths",
            return_value={"product_analytics"},
        ):
            context = build_default_context(
                op_config={
                    "product_paths": ["product_analytics"],
                    "email_filter_s3_url": "s3://my-bucket/emails.txt",
                },
                resources={"s3": mock_s3_resource},
            )

            populate_user_product_list(context)

            user1_entry = UserProductList.objects.filter(user=user1, team=team)
            user2_entry = UserProductList.objects.filter(user=user2, team=team)
            user3_entry = UserProductList.objects.filter(user=user3, team=team)

            assert user1_entry.count() == 1
            assert user2_entry.count() == 1
            assert user3_entry.count() == 0

            mock_s3_resource.get_client.assert_called_once()
            mock_s3_client.get_object.assert_called_once_with(Bucket="my-bucket", Key="emails.txt")

            metadata = context.get_output_metadata("result")
            assert metadata["created"].value == 2

    @pytest.mark.django_db
    def test_populate_filters_by_emails_from_s3_case_insensitive(self):
        org = Organization.objects.create(name="Test Org")
        team = Team.objects.create(organization=org, name="Test Team")
        user_upper = User.objects.create(email="USER@EXAMPLE.COM", first_name="Upper", allow_sidebar_suggestions=True)
        user_lower = User.objects.create(email="user@example.com", first_name="Lower", allow_sidebar_suggestions=True)
        user_upper.join(organization=org)
        user_lower.join(organization=org)

        email_list_content = "user@example.com\n"
        mock_s3_client = MagicMock()
        mock_response = MagicMock()
        mock_response["Body"].read.return_value = email_list_content.encode("utf-8")
        mock_s3_client.get_object.return_value = mock_response

        mock_s3_resource = MagicMock()
        mock_s3_resource.get_client.return_value = mock_s3_client

        with patch(
            "products.growth.dags.user_product_list.get_valid_product_paths",
            return_value={"product_analytics"},
        ):
            context = build_default_context(
                op_config={
                    "product_paths": ["product_analytics"],
                    "email_filter_s3_url": "s3://my-bucket/emails.txt",
                },
                resources={"s3": mock_s3_resource},
            )

            populate_user_product_list(context)

            upper_entry = UserProductList.objects.filter(user=user_upper, team=team)
            lower_entry = UserProductList.objects.filter(user=user_lower, team=team)

            assert upper_entry.count() == 1
            assert lower_entry.count() == 1

    @pytest.mark.django_db
    def test_populate_filters_by_emails_from_s3_with_whitespace(self):
        org = Organization.objects.create(name="Test Org")
        team = Team.objects.create(organization=org, name="Test Team")
        user = User.objects.create(email="user@example.com", first_name="User", allow_sidebar_suggestions=True)
        user.join(organization=org)

        email_list_content = "  user@example.com  \n\n  another@example.com  \n"
        mock_s3_client = MagicMock()
        mock_response = MagicMock()
        mock_response["Body"].read.return_value = email_list_content.encode("utf-8")
        mock_s3_client.get_object.return_value = mock_response

        mock_s3_resource = MagicMock()
        mock_s3_resource.get_client.return_value = mock_s3_client

        with patch(
            "products.growth.dags.user_product_list.get_valid_product_paths",
            return_value={"product_analytics"},
        ):
            context = build_default_context(
                op_config={
                    "product_paths": ["product_analytics"],
                    "email_filter_s3_url": "s3://my-bucket/emails.txt",
                },
                resources={"s3": mock_s3_resource},
            )

            populate_user_product_list(context)

            entry = UserProductList.objects.filter(user=user, team=team)
            assert entry.count() == 1

    @pytest.mark.django_db
    def test_populate_filters_by_emails_from_s3_empty_list(self):
        org = Organization.objects.create(name="Test Org")
        team = Team.objects.create(organization=org, name="Test Team")
        user = User.objects.create(email="user@example.com", first_name="User", allow_sidebar_suggestions=True)
        user.join(organization=org)

        email_list_content = ""
        mock_s3_client = MagicMock()
        mock_response = MagicMock()
        mock_response["Body"].read.return_value = email_list_content.encode("utf-8")
        mock_s3_client.get_object.return_value = mock_response

        mock_s3_resource = MagicMock()
        mock_s3_resource.get_client.return_value = mock_s3_client

        with patch(
            "products.growth.dags.user_product_list.get_valid_product_paths",
            return_value={"product_analytics"},
        ):
            context = build_default_context(
                op_config={
                    "product_paths": ["product_analytics"],
                    "email_filter_s3_url": "s3://my-bucket/emails.txt",
                },
                resources={"s3": mock_s3_resource},
            )

            populate_user_product_list(context)

            entry = UserProductList.objects.filter(user=user, team=team)
            assert entry.count() == 0

    @pytest.mark.django_db
    def test_populate_fails_with_invalid_s3_url_scheme(self):
        mock_s3_resource = MagicMock()

        with patch(
            "products.growth.dags.user_product_list.get_valid_product_paths",
            return_value={"product_analytics"},
        ):
            context = build_default_context(
                op_config={
                    "product_paths": ["product_analytics"],
                    "email_filter_s3_url": "https://my-bucket/emails.txt",
                },
                resources={"s3": mock_s3_resource},
            )

            with pytest.raises(
                dagster.Failure,
                match="Failed to download or process email filter from S3",
            ):
                populate_user_product_list(context)

    @pytest.mark.django_db
    def test_populate_fails_with_invalid_s3_url_format(self):
        mock_s3_resource = MagicMock()

        with patch(
            "products.growth.dags.user_product_list.get_valid_product_paths",
            return_value={"product_analytics"},
        ):
            context = build_default_context(
                op_config={
                    "product_paths": ["product_analytics"],
                    "email_filter_s3_url": "s3://",
                },
                resources={"s3": mock_s3_resource},
            )

            with pytest.raises(
                dagster.Failure,
                match="Failed to download or process email filter from S3",
            ):
                populate_user_product_list(context)

    @pytest.mark.django_db
    def test_populate_fails_when_s3_download_fails(self):
        mock_s3_client = MagicMock()
        mock_s3_client.get_object.side_effect = Exception("S3 access denied")

        mock_s3_resource = MagicMock()
        mock_s3_resource.get_client.return_value = mock_s3_client

        with patch(
            "products.growth.dags.user_product_list.get_valid_product_paths",
            return_value={"product_analytics"},
        ):
            context = build_default_context(
                op_config={
                    "product_paths": ["product_analytics"],
                    "email_filter_s3_url": "s3://my-bucket/emails.txt",
                },
                resources={"s3": mock_s3_resource},
            )

            with pytest.raises(
                dagster.Failure,
                match="Failed to download or process email filter from S3",
            ):
                populate_user_product_list(context)

    @pytest.mark.django_db
    def test_populate_combines_email_filter_with_other_filters(self):
        org = Organization.objects.create(name="Test Org")
        team = Team.objects.create(organization=org, name="Test Team")
        user1 = User.objects.create(
            email="user1@example.com",
            first_name="User1",
            allow_sidebar_suggestions=True,
            role_at_organization="engineering",
        )
        user2 = User.objects.create(
            email="user2@example.com",
            first_name="User2",
            allow_sidebar_suggestions=True,
            role_at_organization="data",
        )
        user3 = User.objects.create(
            email="user3@example.com",
            first_name="User3",
            allow_sidebar_suggestions=True,
            role_at_organization="engineering",
        )
        user1.join(organization=org)
        user2.join(organization=org)
        user3.join(organization=org)

        email_list_content = "user1@example.com\nuser2@example.com\nuser3@example.com\n"
        mock_s3_client = MagicMock()
        mock_response = MagicMock()
        mock_response["Body"].read.return_value = email_list_content.encode("utf-8")
        mock_s3_client.get_object.return_value = mock_response

        mock_s3_resource = MagicMock()
        mock_s3_resource.get_client.return_value = mock_s3_client

        with patch(
            "products.growth.dags.user_product_list.get_valid_product_paths",
            return_value={"product_analytics"},
        ):
            context = build_default_context(
                op_config={
                    "product_paths": ["product_analytics"],
                    "email_filter_s3_url": "s3://my-bucket/emails.txt",
                    "role_at_organization": "engineering",
                },
                resources={"s3": mock_s3_resource},
            )

            populate_user_product_list(context)

            user1_entry = UserProductList.objects.filter(user=user1, team=team)
            user2_entry = UserProductList.objects.filter(user=user2, team=team)
            user3_entry = UserProductList.objects.filter(user=user3, team=team)

            assert user1_entry.count() == 1
            assert user2_entry.count() == 0
            assert user3_entry.count() == 1


class TestPopulateUserProductListJob:
    @pytest.mark.django_db
    def test_job_execution_success(self):
        org = Organization.objects.create(name="Test Org")
        team = Team.objects.create(organization=org, name="Test Team")
        user = User.objects.create(email="test@example.com", first_name="Test", allow_sidebar_suggestions=True)
        user.join(organization=org)

        with patch(
            "products.growth.dags.user_product_list.get_valid_product_paths",
            return_value={"product_analytics"},
        ):
            result = populate_user_product_list_job.execute_in_process(
                run_config={
                    "ops": {
                        "populate_user_product_list": {
                            "config": {
                                "product_paths": ["product_analytics"],
                                "reason": "product_intent",
                            }
                        }
                    }
                },
                resources={"s3": create_mock_s3_resource()},
            )

            assert result.success

            entry = UserProductList.objects.get(user=user, team=team, product_path="product_analytics")
            assert entry.reason == "product_intent"

    @pytest.mark.django_db
    def test_job_respects_allow_sidebar_suggestions(self):
        org = Organization.objects.create(name="Test Org")
        team = Team.objects.create(organization=org, name="Test Team")
        user_allowed = User.objects.create(
            email="allowed@example.com",
            first_name="Allowed",
            allow_sidebar_suggestions=True,
        )
        user_disallowed = User.objects.create(
            email="disallowed@example.com",
            first_name="Disallowed",
            allow_sidebar_suggestions=False,
        )
        user_allowed.join(organization=org)
        user_disallowed.join(organization=org)

        with patch(
            "products.growth.dags.user_product_list.get_valid_product_paths",
            return_value={"product_analytics"},
        ):
            result = populate_user_product_list_job.execute_in_process(
                run_config={
                    "ops": {
                        "populate_user_product_list": {
                            "config": {
                                "product_paths": ["product_analytics"],
                            }
                        }
                    }
                },
                resources={"s3": create_mock_s3_resource()},
            )

            assert result.success

            allowed_entry = UserProductList.objects.filter(user=user_allowed, team=team)
            disallowed_entry = UserProductList.objects.filter(user=user_disallowed, team=team)

            assert allowed_entry.count() == 1
            assert disallowed_entry.count() == 0
