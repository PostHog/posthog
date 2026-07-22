from typing import Any

from unittest.mock import patch

from products.review_hog.backend.reviewer.outcomes.github_fetch import fetch_compare_files

_FETCH = "products.review_hog.backend.reviewer.outcomes.github_fetch.github_api_request"


class _Response:
    def __init__(self, files: list[dict[str, Any]]) -> None:
        self._files = files

    def json(self) -> dict[str, Any]:
        return {"files": self._files}


def test_full_page_triggers_next_page_until_short_page():
    # GitHub caps a compare at 300 files per page; without pagination a post-review master merge
    # truncates the evidence and findings in dropped files durably classify as ignored.
    pages = {
        1: [{"filename": f"a{i}.py"} for i in range(300)],
        2: [{"filename": "tail.py"}],
    }

    def fake(method: str, path: str, **kwargs: Any) -> _Response:
        return _Response(pages[kwargs["params"]["page"]])

    with patch(_FETCH, side_effect=fake):
        files = fetch_compare_files(owner="o", repo="r", base_sha="base", head_sha="head", token="t")

    assert len(files) == 301
    assert files[-1]["filename"] == "tail.py"
