import threading

import pytest

from django.test import SimpleTestCase, override_settings

from products.engineering_analytics.backend.logic.queries._curated import ConcurrentReads


@override_settings(TEST=False)
class TestConcurrentReads(SimpleTestCase):
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

    def test_a_failed_read_raises_in_the_caller(self) -> None:
        def fail() -> int:
            raise ValueError("read failed")

        reads = ConcurrentReads()
        succeeded = reads.submit(lambda: 1)
        failed = reads.submit(fail)

        with pytest.raises(ValueError, match="read failed"):
            reads.run()
        assert succeeded.result() == 1
        assert isinstance(failed.exception(timeout=0), ValueError)
