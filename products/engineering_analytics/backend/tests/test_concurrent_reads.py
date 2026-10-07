import threading

import pytest

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from products.engineering_analytics.backend.logic.queries._curated import ConcurrentReads


class TestConcurrentReads(SimpleTestCase):
    @override_settings(TEST=False)
    def test_reads_run_together_and_return_their_results(self) -> None:
        both_started = threading.Barrier(2, timeout=5)

        def read(value: int) -> int:
            both_started.wait()
            return value

        reads = ConcurrentReads()
        first = reads.submit(lambda: read(1))
        second = reads.submit(lambda: read(2))
        reads.run()

        assert (first.result(), second.result()) == (1, 2)

    @parameterized.expand([("threaded", False), ("inline", True)])
    def test_a_failed_read_raises_after_every_read_settles(self, _name: str, inline: bool) -> None:
        def fail() -> int:
            raise ValueError("read failed")

        reads = ConcurrentReads()
        failed = reads.submit(fail)
        succeeded = reads.submit(lambda: 1)

        with override_settings(TEST=inline), pytest.raises(ValueError, match="read failed"):
            reads.run()
        assert isinstance(failed.exception(timeout=0), ValueError)
        assert succeeded.result(timeout=0) == 1
