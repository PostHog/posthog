import pytest

from fastapi.testclient import TestClient
from stripe_mock.data.store import store
from stripe_mock.main import app


@pytest.fixture(autouse=True)
def load_basic_scenario():
    store.load_scenario("basic")
    yield


@pytest.fixture()
def client():
    return TestClient(app)
