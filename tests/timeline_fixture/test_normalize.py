from src.timeline_fixture.normalize import normalize_files


def test_normalize_files_returns_sorted_unique_paths():
    assert normalize_files(["b", "a", "b"]) == ["a", "b"]
