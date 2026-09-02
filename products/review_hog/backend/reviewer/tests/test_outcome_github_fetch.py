from typing import Any

from unittest.mock import patch

from products.review_hog.backend.reviewer.outcomes.github_fetch import (
    _MAX_REVIEW_COMMENTS,
    fetch_compare_files,
    fetch_review_comments,
)
from products.review_hog.backend.reviewer.tools.github_meta import GITHUB_COMPARE_FILES_CAP

_MODULE = "products.review_hog.backend.reviewer.outcomes.github_fetch"
_FETCH = f"{_MODULE}.github_api_request"
# The paginator calls `github_api_request` from its own module, so bounding it is patched there.
_PAGINATED_FETCH = "products.review_hog.backend.reviewer.tools.github_client.github_api_request"
# The module's logger, not `caplog`: caplog reads records that propagate to the root handler, and
# whether they do depends on the logging config the suite happens to run under — green locally, empty
# under CI's config. Patching the logger asserts the same thing without depending on that.
_LOGGER = f"{_MODULE}.logger"


class _Response:
    def __init__(self, files: list[dict[str, Any]]) -> None:
        self._files = files

    def json(self) -> dict[str, Any]:
        return {"files": self._files}


class _ListResponse:
    def __init__(self, items: list[dict[str, Any]]) -> None:
        self._items = items

    def json(self) -> list[dict[str, Any]]:
        return self._items


def test_capped_compare_warns_and_does_not_request_another_page():
    # GitHub returns a compare's changed files only on the first page, capped at 300 for the whole
    # comparison — `page` walks the commits array, not the files. Requesting page 2 spends an egress
    # call against the installation's budget and returns no extra files, so the cap has to surface as
    # a warning instead: findings in the dropped files look untouched and classify as ignored.
    capped = [{"filename": f"a{i}.py"} for i in range(GITHUB_COMPARE_FILES_CAP)]
    with patch(_LOGGER) as log, patch(_FETCH, return_value=_Response(capped)) as request:
        files = fetch_compare_files(owner="o", repo="r", base_sha="base", head_sha="head", token="t")

    assert len(files) == GITHUB_COMPARE_FILES_CAP
    assert request.call_count == 1
    log.warning.assert_called_once()
    assert "file cap" in log.warning.call_args.args[0]


def test_uncapped_compare_returns_files_without_warning():
    with patch(_LOGGER) as log, patch(_FETCH, return_value=_Response([{"filename": "a.py"}])) as request:
        files = fetch_compare_files(owner="o", repo="r", base_sha="base", head_sha="head", token="t")

    assert [f["filename"] for f in files] == ["a.py"]
    assert request.call_count == 1
    log.warning.assert_not_called()


def test_review_comments_stop_paging_at_the_cap():
    # Comment volume is set by whoever comments on the PR, and the paginator otherwise walks pages
    # until a short one. An endless thread would spend the installation's shared egress budget on a
    # single report; exhausting it stops the team's whole sweep with the report unstamped, so the
    # next hourly sweep drains the same pages again and the team never gets past it.
    full_page = [{"id": i, "in_reply_to_id": None} for i in range(100)]
    with patch(_LOGGER) as log, patch(_PAGINATED_FETCH, return_value=_ListResponse(full_page)) as request:
        comments = fetch_review_comments(owner="o", repo="r", pr_number=1, token="t")

    assert len(comments) == _MAX_REVIEW_COMMENTS
    # Bounded egress: one page beyond the cap to detect truncation, then it stops.
    assert request.call_count == (_MAX_REVIEW_COMMENTS // 100) + 1
    log.warning.assert_called_once()
    assert "review comments" in log.warning.call_args.args[0]


def test_review_comments_under_the_cap_are_returned_whole():
    with patch(_LOGGER) as log, patch(_PAGINATED_FETCH, return_value=_ListResponse([{"id": 1}])) as request:
        comments = fetch_review_comments(owner="o", repo="r", pr_number=1, token="t")

    assert comments == [{"id": 1}]
    assert request.call_count == 1
    log.warning.assert_not_called()
