import pytest
from unittest.mock import patch

import dagster
from dagster import build_op_context

from posthog.models import Organization, Team, User
from posthog.models.file_system.user_product_list import UserProductList

from products.growth.dags.user_product_list import populate_user_product_list, populate_user_product_list_job


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
            context = build_op_context(
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
            assert metadata["created"].value == 1  # type: ignore
            assert metadata["skipped"].value == 0  # type: ignore

    @pytest.mark.django_db
    def test_populate_with_reason(self):
        org = Organization.objects.create(name="Test Org")
        team = Team.objects.create(organization=org, name="Test Team")
        user = User.objects.create(email="test@example.com", first_name="Test", allow_sidebar_suggestions=True)
        user.join(organization=org)

        with patch(
            "products.growth.dags.user_product_list.get_valid_product_paths", return_value={"product_analytics"}
        ):
            context = build_op_context(
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
            "products.growth.dags.user_product_list.get_valid_product_paths", return_value={"product_analytics"}
        ):
            context = build_op_context(
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
            "products.growth.dags.user_product_list.get_valid_product_paths", return_value={"product_analytics"}
        ):
            context = build_op_context(
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
            email="allowed@example.com", first_name="Allowed", allow_sidebar_suggestions=True
        )
        user_disallowed = User.objects.create(
            email="disallowed@example.com", first_name="Disallowed", allow_sidebar_suggestions=False
        )
        user_allowed.join(organization=org)
        user_disallowed.join(organization=org)

        with patch(
            "products.growth.dags.user_product_list.get_valid_product_paths", return_value={"product_analytics"}
        ):
            context = build_op_context(
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
            assert metadata["created"].value == 1  # type: ignore

    @pytest.mark.django_db
    def test_populate_respects_allow_sidebar_suggestions_null_defaults_to_allowed(self):
        org = Organization.objects.create(name="Test Org")
        team = Team.objects.create(organization=org, name="Test Team")
        user_null = User.objects.create(email="null@example.com", first_name="Null", allow_sidebar_suggestions=None)
        user_null.join(organization=org)

        with patch(
            "products.growth.dags.user_product_list.get_valid_product_paths", return_value={"product_analytics"}
        ):
            context = build_op_context(
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
            context = build_op_context(
                op_config={
                    "product_paths": ["product_analytics", "session_replay"],
                }
            )

            populate_user_product_list(context)

            entries = UserProductList.objects.filter(user=user, team=team)
            assert entries.count() == 2
            assert set(entries.values_list("product_path", flat=True)) == {"product_analytics", "session_replay"}

            metadata = context.get_output_metadata("result")
            assert metadata["created"].value == 2  # type: ignore

    @pytest.mark.django_db
    def test_populate_skips_existing_entries(self):
        org = Organization.objects.create(name="Test Org")
        team = Team.objects.create(organization=org, name="Test Team")
        user = User.objects.create(email="test@example.com", first_name="Test", allow_sidebar_suggestions=True)
        user.join(organization=org)

        UserProductList.objects.create(
            user=user, team=team, product_path="product_analytics", enabled=True, reason="product_intent"
        )

        with patch(
            "products.growth.dags.user_product_list.get_valid_product_paths", return_value={"product_analytics"}
        ):
            context = build_op_context(
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
            assert metadata["created"].value == 0  # type: ignore
            assert metadata["skipped"].value == 1  # type: ignore

    @pytest.mark.django_db
    def test_populate_multiple_teams(self):
        org = Organization.objects.create(name="Test Org")
        team1 = Team.objects.create(organization=org, name="Test Team 1")
        team2 = Team.objects.create(organization=org, name="Test Team 2")
        user = User.objects.create(email="test@example.com", first_name="Test", allow_sidebar_suggestions=True)
        user.join(organization=org)

        with patch(
            "products.growth.dags.user_product_list.get_valid_product_paths", return_value={"product_analytics"}
        ):
            context = build_op_context(
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
            assert metadata["created"].value == 2  # type: ignore

    @pytest.mark.django_db
    def test_populate_filters_by_require_existing_product(self):
        org = Organization.objects.create(name="Test Org")
        team = Team.objects.create(organization=org, name="Test Team")
        user_with_product = User.objects.create(
            email="with@example.com", first_name="With", allow_sidebar_suggestions=True
        )
        user_without_product = User.objects.create(
            email="without@example.com", first_name="Without", allow_sidebar_suggestions=True
        )
        user_with_product.join(organization=org)
        user_without_product.join(organization=org)

        UserProductList.objects.create(
            user=user_with_product, team=team, product_path="product_analytics", enabled=True
        )

        with patch(
            "products.growth.dags.user_product_list.get_valid_product_paths",
            return_value={"product_analytics", "session_replay"},
        ):
            context = build_op_context(
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
            "products.growth.dags.user_product_list.get_valid_product_paths", return_value={"product_analytics"}
        ):
            context = build_op_context(
                op_config={
                    "product_paths": [],
                }
            )

            with pytest.raises(dagster.Failure, match="product_paths cannot be empty"):
                populate_user_product_list(context)

    @pytest.mark.django_db
    def test_populate_fails_with_invalid_product_paths(self):
        with patch(
            "products.growth.dags.user_product_list.get_valid_product_paths", return_value={"product_analytics"}
        ):
            context = build_op_context(
                op_config={
                    "product_paths": ["invalid_product"],
                }
            )

            with pytest.raises(dagster.Failure, match="Invalid product paths"):
                populate_user_product_list(context)

    @pytest.mark.django_db
    def test_populate_fails_with_invalid_require_existing_product(self):
        with patch(
            "products.growth.dags.user_product_list.get_valid_product_paths", return_value={"product_analytics"}
        ):
            context = build_op_context(
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
            "products.growth.dags.user_product_list.get_valid_product_paths", return_value={"product_analytics"}
        ):
            context = build_op_context(
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
            email="data@example.com", first_name="Data", allow_sidebar_suggestions=True, role_at_organization="data"
        )
        user_no_role = User.objects.create(
            email="norole@example.com", first_name="NoRole", allow_sidebar_suggestions=True, role_at_organization=None
        )
        user_engineering.join(organization=org)
        user_data.join(organization=org)
        user_no_role.join(organization=org)

        with patch(
            "products.growth.dags.user_product_list.get_valid_product_paths", return_value={"product_analytics"}
        ):
            context = build_op_context(
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
            assert metadata["created"].value == 1  # type: ignore

    @pytest.mark.django_db
    def test_populate_fails_with_invalid_role_at_organization(self):
        with patch(
            "products.growth.dags.user_product_list.get_valid_product_paths", return_value={"product_analytics"}
        ):
            context = build_op_context(
                op_config={
                    "product_paths": ["product_analytics"],
                    "role_at_organization": "invalid_role",
                }
            )

            with pytest.raises(dagster.Failure, match="Invalid role_at_organization"):
                populate_user_product_list(context)


class TestPopulateUserProductListJob:
    @pytest.mark.django_db
    def test_job_execution_success(self):
        org = Organization.objects.create(name="Test Org")
        team = Team.objects.create(organization=org, name="Test Team")
        user = User.objects.create(email="test@example.com", first_name="Test", allow_sidebar_suggestions=True)
        user.join(organization=org)

        with patch(
            "products.growth.dags.user_product_list.get_valid_product_paths", return_value={"product_analytics"}
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
                }
            )

            assert result.success

            entry = UserProductList.objects.get(user=user, team=team, product_path="product_analytics")
            assert entry.reason == "product_intent"

    @pytest.mark.django_db
    def test_job_respects_allow_sidebar_suggestions(self):
        org = Organization.objects.create(name="Test Org")
        team = Team.objects.create(organization=org, name="Test Team")
        user_allowed = User.objects.create(
            email="allowed@example.com", first_name="Allowed", allow_sidebar_suggestions=True
        )
        user_disallowed = User.objects.create(
            email="disallowed@example.com", first_name="Disallowed", allow_sidebar_suggestions=False
        )
        user_allowed.join(organization=org)
        user_disallowed.join(organization=org)

        with patch(
            "products.growth.dags.user_product_list.get_valid_product_paths", return_value={"product_analytics"}
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
                }
            )

            assert result.success

            allowed_entry = UserProductList.objects.filter(user=user_allowed, team=team)
            disallowed_entry = UserProductList.objects.filter(user=user_disallowed, team=team)

            assert allowed_entry.count() == 1
            assert disallowed_entry.count() == 0
