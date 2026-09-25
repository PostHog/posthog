from collections.abc import Generator

import pytest

import numpy as np


@pytest.fixture(autouse=True)
def seed_experiment_statistics() -> Generator[None]:
    random_state = np.random.get_state()
    np.random.seed(0)
    yield
    np.random.set_state(random_state)
