from src.timeline_fixture.summary import file_count


def test_file_count_deduplicates_paths():
    assert file_count(["a", "a", "b"]) == 2
