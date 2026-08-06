import json
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from unittest.mock import patch

import dagster
from clickhouse_driver import Client

from posthog.clickhouse.cluster import ClickhouseCluster

from products.growth.backend.constants import identity_matching_dataset_read_args
from products.growth.dags import identity_matching
from products.growth.dags.identity_matching import (
    CANDIDATE_PAIRS,
    DEVICE_DAYS,
    LINKS,
    LOGREG_MODEL_VERSION,
    PERSON_TIMELINE,
    RULES_MODEL_VERSION,
    IdentityMatchingConfig,
    MatchingDataset,
    identity_matching_job,
    is_identity_matching_registered,
    validate_team_allowed,
)

TEAM_ID = 99

# Each stage writes Parquet to a per-run S3 prefix; reads glob it back via `s3(...)`.
_S3_READ_SETTINGS = {"s3_throw_on_zero_files_match": "0"}


def _read_dataset(
    client: Client, dataset: MatchingDataset, job_id: UUID, columns: str, suffix: str = ""
) -> list[tuple[Any, ...]]:
    args = identity_matching_dataset_read_args(TEAM_ID, str(job_id), dataset.folder, dataset.structure)
    return client.execute(f"SELECT {columns} FROM s3({args}) {suffix}", settings=_S3_READ_SETTINGS)


HOUSEHOLD_IP = "10.0.0.1"
BOB_IP = "10.0.0.2"
CARA_IP = "10.0.0.9"
CORPORATE_IP = "203.0.113.5"

DESKTOP_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
MOBILE_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1"
WEBVIEW_UA = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/120.0.0.0 Mobile Safari/537.36 wv) LinkedInApp"
)


def _event(event: str, distinct_id: str, timestamp: datetime, properties: dict[str, Any]) -> tuple[Any, ...]:
    return (uuid4(), event, json.dumps(properties), timestamp, TEAM_ID, distinct_id)


def _device_props(ip: str, ua: str, device_type: str, city: str, language: str, path: str) -> dict[str, Any]:
    return {
        "$ip": ip,
        "$raw_user_agent": ua,
        "$device_type": device_type,
        "$browser": "Chrome",
        "$os": "Mac OS X" if device_type == "Desktop" else "iOS",
        "$timezone": "Europe/Lisbon",
        "$browser_language": language,
        "$geoip_city_name": city,
        "$geoip_subdivision_1_code": "PT-11",
        "$geoip_postal_code": "1000",
        "$pathname": path,
    }


def _fixture_events() -> list[tuple[Any, ...]]:
    anna_desktop = lambda path: _device_props(HOUSEHOLD_IP, DESKTOP_UA, "Desktop", "Lisbon", "en-GB", path)
    anna_phone = lambda path: _device_props(HOUSEHOLD_IP, MOBILE_UA, "Mobile", "Lisbon", "en-GB", path)
    bob_desktop = lambda path: _device_props(BOB_IP, DESKTOP_UA, "Desktop", "Porto", "pt-PT", path)
    bob_phone = lambda ip, path: _device_props(ip, MOBILE_UA, "Mobile", "Porto", "pt-PT", path)
    cara_device = lambda path: _device_props(CARA_IP, WEBVIEW_UA, "Mobile", "Faro", "pt-PT", path)

    events = [
        # Anna researches on her laptop, then identifies on Jan 2.
        _event("$pageview", "laptop-anna-anon", datetime(2025, 1, 1, 10), anna_desktop("/pricing")),
        _event("$pageview", "laptop-anna-anon", datetime(2025, 1, 1, 11), anna_desktop("/docs")),
        _event(
            "$identify",
            "anna@x.com",
            datetime(2025, 1, 2, 9),
            {**anna_desktop("/signup"), "$anon_distinct_id": "laptop-anna-anon"},
        ),
        _event("$pageview", "anna@x.com", datetime(2025, 1, 3, 20), anna_desktop("/pricing")),
        _event("$pageview", "anna@x.com", datetime(2025, 1, 4, 20), anna_desktop("/dashboard")),
        _event("$pageview", "anna@x.com", datetime(2025, 1, 5, 20), anna_desktop("/dashboard")),
        # Anna's phone browses from the household IP on three evenings; the first touch is a
        # paid click that her identified history lacks.
        _event("$pageview", "phone-anna", datetime(2025, 1, 3, 21), {**anna_phone("/pricing"), "gclid": "abc123"}),
        _event("$pageview", "phone-anna", datetime(2025, 1, 4, 21), anna_phone("/blog/why")),
        _event("$pageview", "phone-anna", datetime(2025, 1, 5, 21), anna_phone("/pricing")),
        # Bob (same household one evening — the hard negative) identifies on Jan 2 and
        # browses from his own IP.
        _event(
            "$identify",
            "bob@x.com",
            datetime(2025, 1, 2, 12),
            {**bob_desktop("/signup"), "$anon_distinct_id": "laptop-bob-anon"},
        ),
        _event("$pageview", "bob@x.com", datetime(2025, 1, 5, 9), bob_desktop("/integrations")),
        _event("$pageview", "bob@x.com", datetime(2025, 1, 6, 9), bob_desktop("/integrations")),
        # Bob's phone: one day on the household IP (overlapping Anna's anchors), two days on
        # Bob's own IP overlapping Bob's anchor activity.
        _event("$pageview", "phone-bob", datetime(2025, 1, 4, 22), bob_phone(HOUSEHOLD_IP, "/integrations")),
        _event("$pageview", "phone-bob", datetime(2025, 1, 5, 10), bob_phone(BOB_IP, "/integrations")),
        _event("$pageview", "phone-bob", datetime(2025, 1, 6, 10), bob_phone(BOB_IP, "/integrations")),
        # Cara: an ad click opened in an in-app webview shares the IP and the byte-identical
        # webview UA with her identified device.
        _event(
            "$identify",
            "cara@x.com",
            datetime(2025, 1, 2, 15),
            {**cara_device("/signup"), "$anon_distinct_id": "first-cara"},
        ),
        _event("$pageview", "cara@x.com", datetime(2025, 1, 3, 15), cara_device("/docs")),
        _event("$pageview", "webview-cara", datetime(2025, 1, 3, 16), cara_device("/docs")),
        # Events without $ip must not break the run.
        _event("$pageview", "no-ip-dave", datetime(2025, 1, 4, 8), {"$pathname": "/pricing"}),
        # Zed's anonymous id sorts before his identified id: the canonical person key must
        # still be the identified side.
        _event(
            "$identify",
            "zed@x.com",
            datetime(2025, 1, 2, 18),
            {
                **_device_props("10.0.0.77", DESKTOP_UA, "Desktop", "Braga", "pt-PT", "/signup"),
                "$anon_distinct_id": "0-zed-anon",
            },
        ),
    ]
    # A corporate IP with more devices than the block cap: excluded from candidates.
    events += [
        _event(
            "$pageview",
            f"corp-{i}",
            datetime(2025, 1, 3, 9),
            _device_props(CORPORATE_IP, DESKTOP_UA, "Desktop", "Lisbon", "en-GB", "/enterprise"),
        )
        for i in range(30)
    ]
    # The retroactive merges that grade the run, both after the feature window ends.
    events += [
        _event(
            "$identify",
            "anna@x.com",
            datetime(2025, 1, 10, 9),
            {**anna_phone("/login"), "$anon_distinct_id": "phone-anna"},
        ),
        _event(
            "$identify",
            "bob@x.com",
            datetime(2025, 1, 11, 9),
            {**bob_phone(BOB_IP, "/login"), "$anon_distinct_id": "phone-bob"},
        ),
    ]
    return events


def _insert_fixture_events(client: Client) -> None:
    client.execute(
        "INSERT INTO writable_events (uuid, event, properties, timestamp, team_id, distinct_id) VALUES",
        _fixture_events(),
    )


def _run_job(cluster: ClickhouseCluster, **config_overrides: Any) -> tuple[dagster.ExecuteInProcessResult, UUID]:
    config_kwargs: dict[str, Any] = {
        "team_id": TEAM_ID,
        "date_start": "2025-01-01",
        "date_end": "2025-01-08",
        "eval_horizon_days": 7,
        "ip_day_block_cap": 10,
        "ip_window_device_cap": 20,
        "rule_min_score": 1.0,
        "rule_min_margin": 0.0,
        # Keep every best-per-orphan logreg link on the tiny fixture; the prod default (0.5) would
        # filter on the model's unstable probabilities and make link assertions flaky.
        "logreg_min_prob": 0.0,
        "min_training_positives": 2,
        "min_training_negatives": 1,
        **config_overrides,
    }
    config = IdentityMatchingConfig(**config_kwargs)
    result = identity_matching_job.execute_in_process(
        run_config=dagster.RunConfig({"prepare_run": config}),
        # Slack posting is skipped off-Cloud, so a no-op resource satisfies the op requirement.
        resources={"cluster": cluster, "slack": dagster.ResourceDefinition.none_resource()},
    )
    return result, UUID(result.dagster_run.run_id)


def test_identity_matching_job(cluster: ClickhouseCluster) -> None:
    cluster.any_host(_insert_fixture_events).result()

    result, job_id = _run_job(cluster)
    assert result.success

    def get_phone_anna_device_days(client: Client) -> list[tuple[Any, ...]]:
        return _read_dataset(client, DEVICE_DAYS, job_id, "day, ips", "WHERE distinct_id = 'phone-anna' ORDER BY day")

    phone_anna_days = cluster.any_host(get_phone_anna_device_days).result()
    assert len(phone_anna_days) == 3
    assert all(ips == [HOUSEHOLD_IP] for _, ips in phone_anna_days)

    def get_timeline(client: Client) -> dict[str, tuple[int, str, str]]:
        rows = _read_dataset(client, PERSON_TIMELINE, job_id, "distinct_id, is_anchor, person_key, label_person_key")
        return {distinct_id: (is_anchor, person_key, label) for distinct_id, is_anchor, person_key, label in rows}

    timeline = cluster.any_host(get_timeline).result()
    assert timeline["anna@x.com"] == (1, "anna@x.com", "")
    assert timeline["laptop-anna-anon"] == (1, "anna@x.com", "")
    assert timeline["bob@x.com"] == (1, "bob@x.com", "")
    assert timeline["cara@x.com"] == (1, "cara@x.com", "")
    # The identified side stays canonical even when the anonymous id sorts first.
    assert timeline["zed@x.com"] == (1, "zed@x.com", "")
    assert timeline["0-zed-anon"] == (1, "zed@x.com", "")
    # Post-window merges become evaluation labels, not anchors.
    assert timeline["phone-anna"] == (0, "", "anna@x.com")
    assert timeline["phone-bob"] == (0, "", "bob@x.com")
    assert "corp-0" not in timeline

    def get_pairs(client: Client) -> dict[tuple[str, str], tuple[int, int, int, int]]:
        rows = _read_dataset(
            client,
            CANDIDATE_PAIRS,
            job_id,
            "orphan_distinct_id, anchor_person_key, shared_ip_days, label, ua_exact_match, orphan_is_webview",
        )
        return {(orphan, anchor): tuple(rest) for orphan, anchor, *rest in rows}

    pairs = cluster.any_host(get_pairs).result()
    assert pairs[("phone-anna", "anna@x.com")][:2] == (3, 1)
    assert pairs[("phone-bob", "anna@x.com")][:2] == (1, 0)
    assert pairs[("phone-bob", "bob@x.com")][:2] == (2, 1)
    cara_pair = pairs[("webview-cara", "cara@x.com")]
    assert cara_pair[1] == -1
    assert cara_pair[2] == 1  # byte-identical user agent
    assert cara_pair[3] == 1  # webview signature
    assert not any(orphan.startswith("corp-") or anchor.startswith("corp-") for orphan, anchor in pairs)

    def get_links(client: Client) -> dict[tuple[str, str], str]:
        rows = _read_dataset(client, LINKS, job_id, "model_version, orphan_distinct_id, anchor_person_key")
        return {(model_version, orphan): anchor for model_version, orphan, anchor in rows}

    links = cluster.any_host(get_links).result()
    assert links[(RULES_MODEL_VERSION, "phone-anna")] == "anna@x.com"
    assert links[(RULES_MODEL_VERSION, "phone-bob")] == "bob@x.com"
    assert links[(RULES_MODEL_VERSION, "webview-cara")] == "cara@x.com"
    # Each orphan with candidates gets exactly one best link per model.
    logreg_links = {orphan for model_version, orphan in links if model_version == LOGREG_MODEL_VERSION}
    assert logreg_links == {"phone-anna", "phone-bob", "webview-cara"}


def test_logreg_skips_without_labels(cluster: ClickhouseCluster) -> None:
    cluster.any_host(_insert_fixture_events).result()

    result, job_id = _run_job(cluster, min_training_positives=50)
    assert result.success

    def get_logreg_link_count(client: Client) -> int:
        [[count]] = _read_dataset(client, LINKS, job_id, "count()", f"WHERE model_version = '{LOGREG_MODEL_VERSION}'")
        return count

    assert cluster.any_host(get_logreg_link_count).result() == 0


def test_eval_labels_survive_edge_truncation(cluster: ClickhouseCluster) -> None:
    cluster.any_host(_insert_fixture_events).result()

    # Exactly 4 identity edges precede window end and 2 post-window merges follow. Capping at 4
    # fills the anchor-edge budget entirely, so the single oldest-first query the job used to run
    # would drop both post-window merges and yield zero labels; the split fetch keeps them.
    result, job_id = _run_job(cluster, max_identity_edges=4)
    assert result.success

    def get_labels(client: Client) -> dict[str, str]:
        rows = _read_dataset(
            client, PERSON_TIMELINE, job_id, "distinct_id, label_person_key", "WHERE label_person_key != ''"
        )
        return dict(rows)

    assert cluster.any_host(get_labels).result() == {"phone-anna": "anna@x.com", "phone-bob": "bob@x.com"}


@pytest.mark.parametrize(
    "cloud_deployment,team_id,allowed",
    [
        (None, 999, True),
        ("LOCAL", 999, True),
        ("DEV", 999, True),
        ("US", 2, True),
        ("US", 999, False),
        ("EU", 2, False),
        ("EU", 999, False),
    ],
)
def test_team_guard_per_environment(cloud_deployment: str | None, team_id: int, allowed: bool) -> None:
    with patch.object(identity_matching.settings, "CLOUD_DEPLOYMENT", cloud_deployment):
        if allowed:
            validate_team_allowed(team_id)
        else:
            with pytest.raises(dagster.Failure):
                validate_team_allowed(team_id)


@pytest.mark.parametrize(
    "cloud_deployment,registered",
    [(None, True), ("LOCAL", True), ("DEV", True), ("US", True), ("EU", False)],
)
def test_job_registration_per_environment(cloud_deployment: str | None, registered: bool) -> None:
    with patch.object(identity_matching.settings, "CLOUD_DEPLOYMENT", cloud_deployment):
        assert is_identity_matching_registered() is registered
