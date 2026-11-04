import uuid

import pytest
from posthog.test.base import NonAtomicBaseTest
from unittest.mock import patch

from django.db import connection

import psycopg
from psycopg import sql

from products.messaging.backend.models.transactional_email_key import TransactionalEmailKey
from products.messaging.backend.services import transactional_email
from products.workflows.backend.facade.models import HogFlow


class TestTransactionalEmailKeyLock(NonAtomicBaseTest):
    def _other_connection(self) -> psycopg.Connection:
        db = connection.settings_dict
        return psycopg.connect(
            dbname=db["NAME"],
            user=db["USER"],
            password=db["PASSWORD"],
            host=db["HOST"] or None,
            port=db["PORT"] or None,
            autocommit=True,
        )

    def test_a_new_key_counts_a_key_another_sender_committed_while_it_waited_for_the_lock(self) -> None:
        lock = transactional_email._lock_team_keys
        lock_free_for_another_sender: list[bool] = []

        def lock_then_another_sender_takes_the_last_key(team_id: int) -> None:
            lock(team_id)
            with self._other_connection() as other:
                row = other.execute(
                    "SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 0))",
                    [f"{transactional_email.TRANSACTIONAL_EMAIL_KEY_LOCK}:{team_id}"],
                ).fetchone()
                assert row is not None
                lock_free_for_another_sender.append(row[0])
                other.execute(
                    sql.SQL(
                        "INSERT INTO {} (id, team_id, key, hog_flow_id, created_at) VALUES (%s, %s, %s, %s, now())"
                    ).format(sql.Identifier(TransactionalEmailKey._meta.db_table)),
                    [uuid.uuid4(), team_id, "welcome", uuid.uuid4()],
                )

        with (
            patch.object(transactional_email, "TRANSACTIONAL_EMAIL_KEY_LIMIT", 1),
            patch.object(
                transactional_email, "_lock_team_keys", side_effect=lock_then_another_sender_takes_the_last_key
            ),
            pytest.raises(transactional_email.TooManyKeys),
        ):
            transactional_email._key_workflow_id(self.team.id, "receipt")

        assert lock_free_for_another_sender == [False]
        assert list(
            TransactionalEmailKey.objects.for_team(self.team.id, canonical=True).values_list("key", flat=True)
        ) == ["welcome"]
        assert not HogFlow.objects.filter(team=self.team, name="receipt").exists()
