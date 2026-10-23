from products.signals.backend.emission._incident_text import latest_text, page_scoped_id


def test_latest_text_treats_missing_timestamps_as_oldest():
    items = [
        {"message": "newest", "created_at": "2026-01-01T02:00:00Z"},
        {"message": "no stamp"},
        {"message": "older", "created_at": "2026-01-01T01:00:00Z"},
    ]
    assert latest_text(items, text_keys=("message",), time_keys=("created_at",)) == "newest"


def test_latest_text_falls_back_to_list_order_without_timestamps():
    items = [{"message": "first"}, {"message": "last"}]
    assert latest_text(items, text_keys=("message",), time_keys=("created_at",)) == "last"
    assert latest_text(items, text_keys=("message",), time_keys=("created_at",), newest_first=True) == "first"


def test_latest_text_ignores_mixed_timestamp_types():
    items = [{"message": "a", "ts": "2026"}, {"message": "b", "ts": 5}]
    assert latest_text(items, text_keys=("message",), time_keys=("ts",)) == "b"


def test_page_scoped_id():
    assert page_scoped_id("p1", "i1") == "p1:i1"
    assert page_scoped_id(None, "i1") == "i1"
