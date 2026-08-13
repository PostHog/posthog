from src.timeline_fixture.normalize import normalize_files


def test_normalize_files_keeps_first_seen_order():
    assert normalize_files(["b", "a", "b"]) == ["b", "a"]
