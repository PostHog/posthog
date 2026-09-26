import pytest

from products.tasks.backend.models import Task
from products.tasks.backend.origin_attribution import RUN_ATTENDED_BY_ORIGIN, is_unattended_run


def test_every_origin_product_is_classified():
    # A missing origin reads as unattended, which drops a whole user-facing surface out of
    # the attended sandbox-volume metric without anyone noticing. Classifying a new origin
    # is part of adding it.
    assert set(RUN_ATTENDED_BY_ORIGIN) == set(Task.OriginProduct.values)


@pytest.mark.parametrize(
    ("origin_product", "internal", "expected"),
    [
        # The report pipeline's research and implementation runs share `signal_report` with the
        # Inbox CTAs a person clicks, so only `internal` separates them.
        ("signal_report", True, True),
        ("signal_report", False, False),
        ("user_created", False, False),
        # The image builder reads like build machinery, but a person opens the session and
        # chats with it, so the attended sandbox-volume metric must keep it.
        ("image_builder", False, False),
        ("signals_scout", False, True),
    ],
)
def test_is_unattended_run(origin_product, internal, expected):
    assert is_unattended_run(origin_product=origin_product, internal=internal) is expected
