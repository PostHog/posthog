import uuid

import pytest

from products.warehouse_sources.backend.facade.models import ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType
from products.warehouse_sources.backend.temporal.data_imports.tests.e2e.conftest import run_external_data_job_workflow

pytestmark = pytest.mark.usefixtures("minio_client")


@pytest.fixture
def external_data_source(team):
    return ExternalDataSource.objects.create(
        source_id=str(uuid.uuid4()),
        connection_id=str(uuid.uuid4()),
        destination_id=str(uuid.uuid4()),
        team=team,
        status="running",
        source_type=ExternalDataSourceType.AWSSES,
        job_inputs={
            "aws_access_key_id": "test-access-key",
            "aws_secret_access_key": "test-secret-key",
            "aws_region": "us-east-1",
        },
    )


@pytest.fixture
def external_data_schema_full_refresh(external_data_source, team):
    return ExternalDataSchema.objects.create(
        name="dedicated_ip_pools",
        team_id=team.pk,
        source_id=external_data_source.pk,
        sync_type="full_refresh",
        sync_type_config={},
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@pytest.mark.parametrize("include_normal_pools", [True, False], ids=["mixed-pools", "reserved-pools-only"])
async def test_aws_ses_reserved_pools_full_refresh(
    team, requests_mock, external_data_source, external_data_schema_full_refresh, include_normal_pools
):
    pools_url = "https://email.us-east-1.amazonaws.com/v2/email/dedicated-ip-pools"
    first_page = ["ses-shared-pool"]
    second_page = ["ses-default-dedicated-pool"]
    expected_rows: list[tuple[str | None, ...]] = [
        ("ses-shared-pool", None, None),
        ("ses-default-dedicated-pool", None, None),
    ]
    expected_columns = ["pool_name", "dedicated_ip_pool_pool_name", "dedicated_ip_pool_scaling_mode"]

    if include_normal_pools:
        first_page.insert(0, "marketing-pool")
        second_page.append("transactional-pool")
        for pool_name, scaling_mode in [("marketing-pool", "MANAGED"), ("transactional-pool", "STANDARD")]:
            requests_mock.get(
                f"{pools_url}/{pool_name}",
                json={"DedicatedIpPool": {"PoolName": pool_name, "ScalingMode": scaling_mode}},
            )
            expected_rows.append((pool_name, pool_name, scaling_mode))
    else:
        expected_columns = ["pool_name"]
        expected_rows = [(row[0],) for row in expected_rows]

    requests_mock.get(
        f"{pools_url}?PageSize=100",
        complete_qs=True,
        json={"DedicatedIpPools": first_page, "NextToken": "second-page"},
    )
    requests_mock.get(
        f"{pools_url}?NextToken=second-page&PageSize=100",
        complete_qs=True,
        json={"DedicatedIpPools": second_page},
    )
    reserved_detail_requests = [
        requests_mock.get(
            f"{pools_url}/{pool_name}",
            status_code=400,
            headers={"x-amzn-ErrorType": "BadRequestException"},
            json={},
        )
        for pool_name in ["ses-shared-pool", "ses-default-dedicated-pool"]
    ]

    result = await run_external_data_job_workflow(
        team=team,
        external_data_source=external_data_source,
        external_data_schema=external_data_schema_full_refresh,
        table_name="awsses_dedicated_ip_pools",
        expected_rows_synced=len(expected_rows),
        expected_total_rows=len(expected_rows),
        expected_columns=expected_columns,
    )

    assert result.results is not None
    assert sorted(tuple(row) for row in result.results) == sorted(expected_rows)
    assert all(detail_request.called for detail_request in reserved_detail_requests)
