from dataclasses import dataclass
from typing import Literal

import dagster
import pydantic

from posthog.dags.common import JobOwners
from posthog.dags.common.ops import get_all_team_ids_op
from posthog.exceptions_capture import capture_exception
from posthog.models.file_system.user_product_list import UserProductList, get_user_product_list_count
from posthog.models.team import Team
from posthog.models.user import ROLE_CHOICES, User
from posthog.products import Products


def get_valid_product_paths() -> set[str]:
    """Get all valid product paths from products.json and hardcoded sidebar products"""
    valid_paths = set[str](Products.get_product_paths())
    return valid_paths


class PopulateConfig(dagster.Config):
    """Configuration for UserProductList populate operations"""

    product_paths: list[str] = pydantic.Field(
        default=[],
        description="List of product paths to add to users' product lists",
    )
    reason: str | None = pydantic.Field(
        default=None,
        description="Reason for creating UserProductList entries",
        examples=UserProductList.Reason.values,
    )
    reason_text: str | None = pydantic.Field(
        default=None,
        description="Optional freeform text to be displayed to the user on hover",
    )
    require_existing_product: str | None = pydantic.Field(
        default=None,
        description="Only create entries for users who already have this product enabled in their UserProductList",
    )
    role_at_organization: str | None = pydantic.Field(
        default=None,
        description="Only process users with this role_at_organization value (e.g., 'engineering', 'data', 'product')",
    )


@dagster.op()
def populate_user_product_list(context: dagster.OpExecutionContext, config: PopulateConfig) -> None:
    """
    Populate UserProductList with configurable options:
    - Set a specific reason for created entries
    - Set optional reason_text for display to users
    - Only create for users who have a specific product enabled
    - Filter by role_at_organization (e.g., 'engineering', 'data', 'product')
    """
    if not config.product_paths:
        raise dagster.Failure("product_paths cannot be empty")

    # Validate product paths against valid products
    valid_paths = get_valid_product_paths()
    invalid_paths = [path for path in config.product_paths if path not in valid_paths]
    if invalid_paths:
        raise dagster.Failure(f"Invalid product paths: {invalid_paths}. Valid options: {sorted(valid_paths)}")

    # Validate require_existing_product if provided
    if config.require_existing_product is not None and config.require_existing_product not in valid_paths:
        raise dagster.Failure(
            f"Invalid require_existing_product: {config.require_existing_product}. Valid options: {sorted(valid_paths)}"
        )

    # Validate reason if provided
    if config.reason:
        if config.reason not in UserProductList.Reason.values:
            raise dagster.Failure(f"Invalid reason: {config.reason}. Valid options: {UserProductList.Reason.values}")

    # Validate role_at_organization if provided

    valid_roles = [choice[0] for choice in ROLE_CHOICES]
    if config.role_at_organization is not None and config.role_at_organization not in valid_roles:
        raise dagster.Failure(
            f"Invalid role_at_organization: {config.role_at_organization}. Valid options: {valid_roles}"
        )

    context.log.info(f"Starting populate for {len(config.product_paths)} products: {config.product_paths}")

    # Build user queryset with filters
    users = User.objects.all().order_by("date_joined")

    # Filter by existing products requirement
    if config.require_existing_product:
        users_with_product = (
            UserProductList.objects.filter(product_path=config.require_existing_product, enabled=True)
            .values_list("user_id", flat=True)
            .distinct()
        )
        users = users.filter(id__in=users_with_product)
        context.log.info(f"Only processing users with '{config.require_existing_product}' enabled")

    # Filter by role_at_organization if specified
    if config.role_at_organization:
        users = users.filter(role_at_organization=config.role_at_organization)
        context.log.info(f"Only processing users with role_at_organization='{config.role_at_organization}'")

    # Respect user preference for sidebar suggestions
    users = users.exclude(allow_sidebar_suggestions=False)
    context.log.info("Excluding users with allow_sidebar_suggestions=False")

    total_users = users.count()
    context.log.info(f"Processing {total_users} users")

    created_count = 0
    skipped_count = 0

    for user in users.iterator(chunk_size=1000):
        # Get all teams this user has access to through organization membership
        teams = Team.objects.filter(organization__members=user).distinct()

        for team in teams:
            for product_path in config.product_paths:
                _, created = UserProductList.objects.get_or_create(
                    team=team,
                    user=user,
                    product_path=product_path,
                    defaults={"enabled": True, "reason": config.reason, "reason_text": config.reason_text},
                )

                if created:
                    created_count += 1
                else:
                    skipped_count += 1

                if created_count != 0 and created_count % 1000 == 0:
                    context.log.info(
                        f"Progress: {created_count} created, {skipped_count} skipped (processed user {user.id})"
                    )

    context.log.info(f"Populate complete: {created_count} created, {skipped_count} skipped")

    context.add_output_metadata(
        {
            "created": dagster.MetadataValue.int(created_count),
            "skipped": dagster.MetadataValue.int(skipped_count),
            "total_products": dagster.MetadataValue.int(len(config.product_paths)),
            "reason": dagster.MetadataValue.text(config.reason or "None"),
        }
    )


@dagster.job(tags={"owner": JobOwners.TEAM_GROWTH.value})
def populate_user_product_list_job():
    """
    Add products to users' product lists with configurable options.
    - product_paths: List of product paths to add (required)
    - reason: Optional reason from UserProductList.Reason
    - reason_text: Optional freeform text to display to users on hover
    - require_existing_product: Only add for users who have this product enabled
    - role_at_organization: Only process users with this role (e.g., 'engineering', 'data')
    """
    populate_user_product_list()


@dataclass(kw_only=True)
class SyncColleaguesProductsResult:
    team_id: int
    users_processed: int
    products_created: int
    status: Literal["success", "failed", "error"]


@dagster.op
def sync_colleagues_products_for_team_op(
    context: dagster.OpExecutionContext,
    team_ids: list[int],
) -> list[SyncColleaguesProductsResult]:
    """Sync colleague products for all users in a batch of teams."""
    results = []

    for team_id in team_ids:
        try:
            team = Team.objects.get(id=team_id)
            users_processed = 0
            products_created = 0

            colleague_product_counts = get_user_product_list_count(team)

            for user in team.all_users_with_access().iterator():
                if user.allow_sidebar_suggestions is False:
                    continue

                created_items = UserProductList.sync_from_team_colleagues(
                    user=user, team=team, colleague_product_counts=colleague_product_counts
                )
                users_processed += 1
                products_created += len(created_items)

            context.log.info(
                f"Team {team_id}: processed {users_processed} users, created {products_created} product entries"
            )

            results.append(
                SyncColleaguesProductsResult(
                    team_id=team_id,
                    users_processed=users_processed,
                    products_created=products_created,
                    status="success",
                )
            )
        except Team.DoesNotExist:
            context.log.warning(f"Team {team_id} not found")
            results.append(
                SyncColleaguesProductsResult(
                    team_id=team_id,
                    users_processed=0,
                    products_created=0,
                    status="failed",
                )
            )
        except Exception as e:
            context.log.exception(f"Failed to process team {team_id}")
            capture_exception(e, {"team_id": team_id, "team": "team-growth"})
            results.append(
                SyncColleaguesProductsResult(
                    team_id=team_id,
                    users_processed=0,
                    products_created=0,
                    status="error",
                )
            )

    success_results = [r for r in results if r.status == "success"]
    failed_results = [r for r in results if r.status in ("failed", "error")]

    context.add_output_metadata(
        {
            "batch_size": dagster.MetadataValue.int(len(team_ids)),
            "processed": dagster.MetadataValue.int(len(results)),
            "success_count": dagster.MetadataValue.int(len(success_results)),
            "failed_count": dagster.MetadataValue.int(len(failed_results)),
            "total_users_processed": dagster.MetadataValue.int(sum(r.users_processed for r in results)),
            "total_products_created": dagster.MetadataValue.int(sum(r.products_created for r in results)),
        }
    )

    return results


@dagster.op
def aggregate_colleagues_sync_results_op(
    context: dagster.OpExecutionContext, results: list[list[SyncColleaguesProductsResult]]
) -> None:
    """Aggregate results from all team processing ops."""
    flat_results = [r for batch in results for r in batch]

    total_teams = len(flat_results)
    success_count = sum(1 for r in flat_results if r.status == "success")
    failed_count = sum(1 for r in flat_results if r.status in ("failed", "error"))
    total_users_processed = sum(r.users_processed for r in flat_results)
    total_products_created = sum(r.products_created for r in flat_results)

    context.log.info(
        f"Completed processing {total_teams} teams: {success_count} succeeded, {failed_count} failed. "
        f"Processed {total_users_processed} users, created {total_products_created} product entries"
    )

    context.add_output_metadata(
        {
            "total_teams": dagster.MetadataValue.int(total_teams),
            "success_count": dagster.MetadataValue.int(success_count),
            "failed_count": dagster.MetadataValue.int(failed_count),
            "total_users_processed": dagster.MetadataValue.int(total_users_processed),
            "total_products_created": dagster.MetadataValue.int(total_products_created),
        }
    )

    if failed_count > 0:
        failed_team_ids = [r.team_id for r in flat_results if r.status in ("failed", "error")]
        context.log.warning(f"Failed to sync colleague products for {failed_count} teams: {failed_team_ids}")


@dagster.job(
    description="Syncs products used by colleagues to each user's product list for all teams",
    executor_def=dagster.multiprocess_executor.configured({"max_concurrent": 10}),
    tags={"owner": JobOwners.TEAM_GROWTH.value},
)
def sync_colleagues_products_monthly_job():
    """
    Monthly job that syncs products used by colleagues to each user's product list.
    For each team, finds the most popular products among colleagues and suggests them to users.
    """
    team_ids = get_all_team_ids_op()
    results = team_ids.map(sync_colleagues_products_for_team_op)
    aggregate_colleagues_sync_results_op(results.collect())


sync_colleagues_products_monthly_schedule = dagster.ScheduleDefinition(
    job=sync_colleagues_products_monthly_job,
    cron_schedule="0 5 15 * *",  # 15th day of every month at 5am UTC
    execution_timezone="UTC",
    name="sync_colleagues_products_monthly_schedule",
)


@dataclass(kw_only=True)
class SyncCrossSellProductsResult:
    team_id: int
    users_processed: int
    products_created: int
    status: Literal["success", "failed", "error"]


@dagster.op
def sync_cross_sell_products_for_team_op(
    context: dagster.OpExecutionContext,
    team_ids: list[int],
) -> list[SyncCrossSellProductsResult]:
    """Sync cross-sell products for all users in a batch of teams."""
    results = []

    for team_id in team_ids:
        try:
            team = Team.objects.get(id=team_id)
            users_processed = 0
            products_created = 0

            for user in team.all_users_with_access().iterator():
                if user.allow_sidebar_suggestions is False:
                    continue

                created_items = UserProductList.sync_cross_sell_products(user=user, team=team)
                users_processed += 1
                products_created += len(created_items)

            context.log.info(
                f"Team {team_id}: processed {users_processed} users, created {products_created} cross-sell product entries"
            )

            results.append(
                SyncCrossSellProductsResult(
                    team_id=team_id,
                    users_processed=users_processed,
                    products_created=products_created,
                    status="success",
                )
            )
        except Team.DoesNotExist:
            context.log.warning(f"Team {team_id} not found")
            results.append(
                SyncCrossSellProductsResult(
                    team_id=team_id,
                    users_processed=0,
                    products_created=0,
                    status="failed",
                )
            )
        except Exception as e:
            context.log.exception(f"Failed to process team {team_id}")
            capture_exception(e, {"team_id": team_id, "team": "team-growth"})
            results.append(
                SyncCrossSellProductsResult(
                    team_id=team_id,
                    users_processed=0,
                    products_created=0,
                    status="error",
                )
            )

    success_results = [r for r in results if r.status == "success"]
    failed_results = [r for r in results if r.status in ("failed", "error")]

    context.add_output_metadata(
        {
            "batch_size": dagster.MetadataValue.int(len(team_ids)),
            "processed": dagster.MetadataValue.int(len(results)),
            "success_count": dagster.MetadataValue.int(len(success_results)),
            "failed_count": dagster.MetadataValue.int(len(failed_results)),
            "total_users_processed": dagster.MetadataValue.int(sum(r.users_processed for r in results)),
            "total_products_created": dagster.MetadataValue.int(sum(r.products_created for r in results)),
        }
    )

    return results


@dagster.op
def aggregate_cross_sell_sync_results_op(
    context: dagster.OpExecutionContext, results: list[list[SyncCrossSellProductsResult]]
) -> None:
    """Aggregate results from all team processing ops."""
    flat_results = [r for batch in results for r in batch]

    total_teams = len(flat_results)
    success_count = sum(1 for r in flat_results if r.status == "success")
    failed_count = sum(1 for r in flat_results if r.status in ("failed", "error"))
    total_users_processed = sum(r.users_processed for r in flat_results)
    total_products_created = sum(r.products_created for r in flat_results)

    context.log.info(
        f"Completed processing {total_teams} teams: {success_count} succeeded, {failed_count} failed. "
        f"Processed {total_users_processed} users, created {total_products_created} cross-sell product entries"
    )

    context.add_output_metadata(
        {
            "total_teams": dagster.MetadataValue.int(total_teams),
            "success_count": dagster.MetadataValue.int(success_count),
            "failed_count": dagster.MetadataValue.int(failed_count),
            "total_users_processed": dagster.MetadataValue.int(total_users_processed),
            "total_products_created": dagster.MetadataValue.int(total_products_created),
        }
    )

    if failed_count > 0:
        failed_team_ids = [r.team_id for r in flat_results if r.status in ("failed", "error")]
        context.log.warning(f"Failed to sync cross-sell products for {failed_count} teams: {failed_team_ids}")


@dagster.job(
    description="Syncs cross-sell products from the same category to users' product lists for all teams",
    executor_def=dagster.multiprocess_executor.configured({"max_concurrent": 10}),
    tags={"owner": JobOwners.TEAM_GROWTH.value},
)
def sync_cross_sell_products_monthly_job():
    """
    Monthly job that syncs cross-sell products to each user's product list.
    For each user, finds products in the same category as their enabled products and suggests them.
    """
    team_ids = get_all_team_ids_op()
    results = team_ids.map(sync_cross_sell_products_for_team_op)
    aggregate_cross_sell_sync_results_op(results.collect())


sync_cross_sell_products_monthly_schedule = dagster.ScheduleDefinition(
    job=sync_cross_sell_products_monthly_job,
    cron_schedule="0 5 1 * *",  # 1st day of every month at 5am UTC
    execution_timezone="UTC",
    name="sync_cross_sell_products_monthly_schedule",
)
