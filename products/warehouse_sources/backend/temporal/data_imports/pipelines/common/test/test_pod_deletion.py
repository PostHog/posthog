from datetime import UTC, datetime
from pathlib import Path

import pytest
import time_machine

import requests_mock

from products.warehouse_sources.backend.temporal.data_imports.pipelines.common.pod_deletion import PodDeletionDeadline

POD_URL = "https://10.0.0.1:443/api/v1/namespaces/workers/pods/worker-abc"


def _service_account(tmp_path: Path) -> Path:
    (tmp_path / "token").write_text("fake-token\n")
    (tmp_path / "namespace").write_text("workers\n")
    (tmp_path / "ca.crt").write_text("fake-ca")
    return tmp_path


@pytest.mark.parametrize(
    "response,expected",
    [
        pytest.param({"json": {"metadata": {"deletionTimestamp": "2026-11-04T12:10:00Z"}}}, 600.0, id="being_deleted"),
        pytest.param({"json": {"metadata": {}}}, None, id="not_being_deleted"),
        pytest.param({"status_code": 403, "json": {}}, None, id="no_permission"),
    ],
)
@time_machine.travel(datetime(2026, 11, 4, 12, 0, tzinfo=UTC), tick=False)
def test_the_pod_deadline_comes_from_the_deletion_timestamp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, response: dict, expected: float | None
) -> None:
    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.0.0.1")
    deadline = PodDeletionDeadline(service_account_dir=_service_account(tmp_path), pod_name="worker-abc")

    with requests_mock.Mocker() as mocker:
        mocker.get(POD_URL, **response)
        assert deadline.seconds_until_kill() == expected
        assert deadline.seconds_until_kill() == expected
        assert mocker.call_count == 1


def test_a_pod_without_a_service_account_token_reads_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.0.0.1")
    deadline = PodDeletionDeadline(service_account_dir=tmp_path, pod_name="worker-abc")

    with requests_mock.Mocker() as mocker:
        assert deadline.seconds_until_kill() is None
        assert mocker.call_count == 0
