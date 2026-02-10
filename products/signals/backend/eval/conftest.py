import json
import datetime
from uuid import uuid4

import pytest

from openai import OpenAI

from posthog.schema import EmbeddingModelName

from posthog.clickhouse.client import sync_execute
from posthog.models import Organization, Team, User

from products.signals.backend.eval.dataset import SEED_REPORTS
from products.signals.backend.models import SignalReport

from ee.hogai.eval.conftest import (
    BraintrustURLReporter,
    capture_stdout as capture_stdout,  # noqa: F401
    pytest_addoption as pytest_addoption,  # noqa: F401
    set_up_evals as set_up_evals,  # noqa: F401
)

EMBEDDING_MODEL = EmbeddingModelName.TEXT_EMBEDDING_3_SMALL_1536
OPENAI_EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536
_NORMALIZED_MODEL = EMBEDDING_MODEL.value.replace("-", "_")
CH_DISTRIBUTED_TABLE = f"distributed_posthog_document_embeddings_{_NORMALIZED_MODEL}"
CH_SHARDED_TABLE = f"sharded_posthog_document_embeddings_{_NORMALIZED_MODEL}"


def generate_embedding_direct(content: str, openai_client: OpenAI) -> list[float]:
    """Call the OpenAI embedding API directly, bypassing the PostHog embedding worker."""
    response = openai_client.embeddings.create(
        model=OPENAI_EMBEDDING_MODEL,
        input=content,
        dimensions=EMBEDDING_DIMENSIONS,
    )
    return response.data[0].embedding


@pytest.hookimpl(trylast=True)
def pytest_configure(config):
    if not str(config.rootdir).endswith("/products/signals/backend/eval"):
        return
    vanilla_reporter = config.pluginmanager.getplugin("terminalreporter")
    braintrust_url_reporter = BraintrustURLReporter(config)
    config.pluginmanager.unregister(vanilla_reporter)
    config.pluginmanager.register(braintrust_url_reporter, "terminalreporter")


@pytest.fixture(scope="session")
def team_with_user(set_up_evals, django_db_blocker):  # noqa: F811
    with django_db_blocker.unblock():
        today = datetime.date.today()
        team_name = f"signal-eval-{today.isoformat()}"

        team = Team.objects.filter(name=team_name).first()
        if team:
            org = team.organization
            user = org.memberships.first().user
        else:
            org = Organization.objects.create(name=team_name)
            user = User.objects.create_user(
                email=f"{team_name}@posthog.com",
                password="eval-not-a-real-password",
                first_name="Signal",
                last_name="Eval",
            )
            org.memberships.create(user=user, level=15)
            team = Team.objects.create(organization=org, name=team_name)

        yield org, team, user


@pytest.fixture(scope="session")
def signal_eval_data(team_with_user, django_db_blocker):
    """Seed ClickHouse with signal embeddings and Postgres with SignalReports.

    Returns a mapping of report key to report UUID string.
    """
    _, team, _ = team_with_user
    openai_client = OpenAI(timeout=60)

    with django_db_blocker.unblock():
        SignalReport.objects.filter(team=team).delete()
        # nosemgrep: semgrep.rules.clickhouse-fstring-param-audit - CH_SHARDED_TABLE is a constant derived from trusted enum EmbeddingModelName
        sync_execute(f"TRUNCATE TABLE IF EXISTS {CH_SHARDED_TABLE}", team_id=team.pk)

        report_id_map: dict[str, str] = {}
        ch_rows: list[tuple] = []
        now = datetime.datetime.now(tz=datetime.UTC)

        for seed_report in SEED_REPORTS:
            report = SignalReport.objects.create(
                team=team,
                status=SignalReport.Status.CANDIDATE,
                total_weight=sum(s.weight for s in seed_report.signals),
                signal_count=len(seed_report.signals),
                title=seed_report.title,
                summary=seed_report.summary,
            )
            report_id = str(report.id)
            report_id_map[seed_report.key] = report_id

            for signal in seed_report.signals:
                embedding = generate_embedding_direct(signal.content, openai_client)
                signal_id = str(uuid4())
                metadata = json.dumps(
                    {
                        "report_id": report_id,
                        "source_product": "session-summaries",
                        "source_type": "pattern",
                        "weight": signal.weight,
                    }
                )
                ch_rows.append(
                    (
                        team.pk,
                        "signals",
                        "signal",
                        "plain",
                        signal_id,
                        now,
                        now,
                        signal.content,
                        metadata,
                        embedding,
                        now,
                        0,
                        0,
                    )
                )

        if ch_rows:
            # nosemgrep: semgrep.rules.clickhouse-fstring-param-audit - CH_DISTRIBUTED_TABLE is a constant derived from trusted enum EmbeddingModelName
            sync_execute(
                f"""
                INSERT INTO {CH_DISTRIBUTED_TABLE} (
                    team_id, product, document_type, rendering,
                    document_id, timestamp, inserted_at,
                    content, metadata,
                    embedding,
                    _timestamp, _offset, _partition
                ) VALUES
                """,
                ch_rows,
                team_id=team.pk,
            )

        print(  # noqa: T201
            f"Seeded {len(ch_rows)} signal embeddings across {len(report_id_map)} reports"
        )

        yield report_id_map
