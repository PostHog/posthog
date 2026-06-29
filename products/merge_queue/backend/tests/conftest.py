import pytest

from products.merge_queue.backend.engine import lifecycle
from products.merge_queue.backend.flaky import StaticFlakyOracle
from products.merge_queue.backend.models import Partition, Strategy

MASTER_HEAD = "m" * 40


class EngineEnv:
    """Installs deterministic engine collaborators and captures launched trials."""

    def __init__(self):
        self.launched: list[int] = []
        self.flaky: set[str] = set()

    def set_flaky(self, *test_ids: str) -> None:
        self.flaky = set(test_ids)
        lifecycle.set_flaky_oracle(StaticFlakyOracle(self.flaky))


@pytest.fixture
def engine():
    env = EngineEnv()
    lifecycle.set_master_head_resolver(lambda repo: MASTER_HEAD)
    lifecycle.set_trial_launcher(env.launched.append)
    lifecycle.set_flaky_oracle(StaticFlakyOracle(set()))
    yield env
    lifecycle.set_master_head_resolver(lifecycle._no_master_head)
    lifecycle.set_trial_launcher(lifecycle._default_launcher)
    lifecycle.set_flaky_oracle(StaticFlakyOracle(set()))


@pytest.fixture
def partition_factory(db):
    def make(
        name: str = "default", *, strategy: Strategy = Strategy.OPTIMISTIC, predicate: str = "approved"
    ) -> Partition:
        return Partition.objects.create(name=name, predicate=predicate, strategy=strategy)

    return make
