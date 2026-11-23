import pytest

from products.stacks.backend import engine
from products.stacks.backend.engine import EngineError, StackDescription, translate_in
from products.stacks.backend.engine.addresses import address
from products.stacks.backend.engine.mappings import load_mapping, natural_key_kinds
from products.stacks.backend.engine.tests.test_translate_out import ENGINE_WORDS


def definition(kind: str, key: str) -> StackDescription:
    return {"version": 1, "resources": [{"kind": kind, "key": key, "body": {"name": key}}]}


@pytest.mark.parametrize(
    ("kind", "key"),
    [
        ("model", "9orders"),
        ("flag", "flag.with.a.dot"),
        ("flag", "a" * 401),
        ("event", "A\x00B"),
        ("event", "\x00"),
        ("event", " Checkout"),
        ("event", "Checkout\u0085"),
        ("event", "\u00a0\t"),
        ("property_group", "A\x00B"),
        ("property_group", "\x00"),
        ("property_group", "\tCart"),
        ("property_group", "Cart\u00a0"),
        ("property_group", "\u2003\n"),
        ("model", "daily-orders"),
        ("model", "system"),
        ("model", "system.builds"),
        ("model", "models"),
        ("endpoint", "9orders"),
        ("endpoint", "_private"),
        ("endpoint", "orders.us"),
        ("endpoint", "bulk_update_tags"),
        ("endpoint", "last_execution_times"),
        ("metric", "_orders"),
        ("metric", "9orders"),
        ("metric", "Paid orders"),
        ("metric", "paid-orders"),
        ("metric", "bulk_delete"),
        ("metric", "bulk_approve"),
        ("endpoint", "é"),
        ("metric", "a" * 129),
        ("model", "a" * 129),
        ("endpoint", "a" * 129),
    ],
)
def test_invalid_natural_key_is_reported_on_the_definition(kind: str, key: str) -> None:
    with pytest.raises(EngineError) as captured:
        translate_in(definition(kind, key), [], {})
    error = captured.value.errors[0]
    assert (error["code"], error["kind"], error["key"], error["path"]) == ("invalid_definition", kind, key, "key")
    assert engine.validate_key(kind, key) == error
    assert not ENGINE_WORDS.search(error["message"])


@pytest.mark.parametrize(
    ("kind", "key"),
    [
        ("model", "$paid.orders_2"),
        ("flag", "A" * 400),
        ("model", "_daily"),
        ("model", "models.orders"),
        ("model", "systemwide"),
        ("model", "a" * 128),
        ("endpoint", "Paid-Orders_2"),
        ("endpoint", "a" * 128),
        ("metric", "Paid_Orders2"),
        ("metric", "a" * 128),
        ("event", "進 / checkout"),
        ("event", "進"),
        ("event", "A\nB"),
        ("property_group", "進 / checkout"),
        ("property_group", "A\tB"),
    ],
)
def test_valid_api_names_reach_the_configuration(kind: str, key: str) -> None:
    assert engine.validate_key(kind, key) is None
    config = translate_in(definition(kind, key), [], {}).config
    resource_type, label = address(kind, key).split(".")
    assert config["resource"][resource_type][label]["name"] == key


@pytest.mark.parametrize("kind", sorted(natural_key_kinds()))
def test_sdk_can_read_the_complete_natural_key_rule(kind: str) -> None:
    rule = load_mapping(kind)
    assert rule["key_pattern"].startswith("^") and rule["key_pattern"].endswith("$")
    assert isinstance(rule["key_max_length"], int) and rule["key_max_length"] > 0
    assert rule["key_sources"] and all(source.endswith(".py") for source in rule["key_sources"])


def test_validate_key_returns_an_error_for_unknown_kinds_and_uses_slug_limits() -> None:
    error = engine.validate_key("unknown-example", "short")
    assert error and error["code"] == "kind_unsupported"
    assert engine.validate_key("insight", "a" * 100) is None
    assert engine.validate_key("insight", "a" * 101)
    assert engine.validate_key("survey", "Survey Name")
    assert engine.validate_key("event", "🦔" * 400) is None
