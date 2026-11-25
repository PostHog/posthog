from collections.abc import Generator
from pathlib import Path

import pytest
from posthog.test.base import reset_unusable_db_connections

from google.auth.credentials import CredentialsWithRegionalAccessBoundary

from products.warehouse_sources.backend.temporal.data_imports.sources.common.job_context import isolated_job_context

_PRODUCT_TESTS_DIR = Path(__file__).parent


@pytest.fixture(autouse=True)
def _skip_google_regional_access_boundary_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    # google-auth looks up the boundary on a background thread after each token refresh.
    # Against a scripted transport that request takes another call's response.
    monkeypatch.setattr(
        CredentialsWithRegionalAccessBoundary, "_is_regional_access_boundary_lookup_required", lambda self: False
    )


@pytest.fixture(autouse=True)
def _isolate_job_context() -> Generator[None]:
    with isolated_job_context():
        yield


@pytest.hookimpl(wrapper=True)
def pytest_runtest_setup(item: pytest.Item) -> Generator[None]:
    # Some tests in this product run production code that calls close_old_connections() on the
    # main thread (the transaction=True duckgres backfill classes), which severs the shared
    # default connection. Under pytest-xdist the next test on the same worker — often a migration
    # TestCase whose setUp drives MigrationExecutor(connection) — would then fail with
    # "the connection is closed". Drop the dead handle before each test so Django reconnects.
    reset_unusable_db_connections()
    return (yield)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_teardown(item: pytest.Item, nextitem: pytest.Item | None) -> Generator[None]:
    # Belt to the pre-test brace above: also clear a severed connection immediately after the
    # test that severed it, so the poison never escapes to a victim in another product's shard
    # (which has no such fixture) or survives into a rerun of the same test.
    try:
        return (yield)
    finally:
        reset_unusable_db_connections()


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    # The Temporal end-to-end tests of this product flake, so every test here retries twice.
    # Every conftest sees every collected item in this hook, so the path check keeps the retries
    # off other trees in a mixed session. A flaky marker on the test itself takes precedence.
    for item in items:
        if item.path.is_relative_to(_PRODUCT_TESTS_DIR) and item.get_closest_marker("flaky") is None:
            item.add_marker(pytest.mark.flaky(reruns=2, reruns_delay=1))
