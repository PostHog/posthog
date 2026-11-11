import datetime as dt

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import OperationalError, connection

from products.replay_vision.backend.temporal import query_budget
from products.replay_vision.backend.temporal.query_budget import bounded_queries


class TestBoundedQueries(BaseTest):
    def test_a_later_statement_only_gets_what_is_left_of_the_block_budget(self) -> None:
        clock = iter([0.0, 0.0, 100.0])
        with patch.object(query_budget.time, "time", side_effect=lambda: next(clock)):
            with self.assertRaisesRegex(OperationalError, "statement timeout"):
                with bounded_queries(dt.timedelta(seconds=60)):
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT 1")
                        cursor.execute("SELECT pg_sleep(0.2)")

    def test_the_caller_transaction_gets_its_timeout_back_when_the_block_raises(self) -> None:
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL statement_timeout = '7s'")
        with self.assertRaises(ValueError):
            with bounded_queries(dt.timedelta(seconds=60)):
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
                raise ValueError
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('statement_timeout')")
            self.assertEqual(cursor.fetchone()[0], "7s")
