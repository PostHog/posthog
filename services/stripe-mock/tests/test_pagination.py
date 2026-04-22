import pytest

from stripe_mock.pagination import paginate_list, paginate_search


class TestPaginateList:
    def _items(self, n: int) -> list[dict]:
        return [{"id": f"obj_{i:03d}", "name": f"item {i}"} for i in range(n)]

    def test_returns_first_page(self):
        result = paginate_list(self._items(5), "/v1/things", limit=3)
        assert result["object"] == "list"
        assert len(result["data"]) == 3
        assert result["has_more"] is True
        assert result["url"] == "/v1/things"

    def test_returns_all_when_under_limit(self):
        result = paginate_list(self._items(3), "/v1/things", limit=10)
        assert len(result["data"]) == 3
        assert result["has_more"] is False

    def test_starting_after_skips_to_cursor(self):
        items = self._items(10)
        result = paginate_list(items, "/v1/things", limit=3, starting_after="obj_004")
        assert result["data"][0]["id"] == "obj_005"
        assert len(result["data"]) == 3

    def test_starting_after_last_item_returns_empty(self):
        items = self._items(3)
        result = paginate_list(items, "/v1/things", limit=10, starting_after="obj_002")
        assert result["data"] == []
        assert result["has_more"] is False

    def test_starting_after_unknown_id_returns_from_start(self):
        items = self._items(3)
        result = paginate_list(items, "/v1/things", limit=10, starting_after="nonexistent")
        assert len(result["data"]) == 3

    def test_limit_clamped_to_100(self):
        result = paginate_list(self._items(200), "/v1/things", limit=200)
        assert len(result["data"]) == 100

    def test_empty_collection(self):
        result = paginate_list([], "/v1/things", limit=10)
        assert result["data"] == []
        assert result["has_more"] is False

    @pytest.mark.parametrize("limit", [0, -1])
    def test_limit_minimum_is_1(self, limit):
        result = paginate_list(self._items(5), "/v1/things", limit=limit)
        assert len(result["data"]) == 1


class TestPaginateSearch:
    def _items(self, n: int) -> list[dict]:
        return [{"id": f"obj_{i:03d}"} for i in range(n)]

    def test_first_page_with_no_token(self):
        result = paginate_search(self._items(10), "/v1/things/search", limit=3)
        assert result["object"] == "search_result"
        assert len(result["data"]) == 3
        assert result["has_more"] is True
        assert "next_page" in result
        assert result["url"] == "/v1/things/search"
        assert result["total_count"] == 10

    def test_next_page_token_advances(self):
        items = self._items(10)
        page1 = paginate_search(items, "/v1/things/search", limit=4)
        page2 = paginate_search(items, "/v1/things/search", limit=4, page_token=page1["next_page"])
        assert page2["data"][0]["id"] == "obj_004"
        assert len(page2["data"]) == 4

    def test_last_page_has_no_next_page(self):
        items = self._items(5)
        result = paginate_search(items, "/v1/things/search", limit=10)
        assert result["has_more"] is False
        assert "next_page" not in result

    def test_full_iteration_via_tokens(self):
        items = self._items(25)
        all_ids: list[str] = []
        token = None
        for _ in range(100):
            result = paginate_search(items, "/v1/x/search", limit=10, page_token=token)
            all_ids.extend(d["id"] for d in result["data"])
            if not result["has_more"]:
                break
            token = result["next_page"]
        assert len(all_ids) == 25
        assert all_ids == [f"obj_{i:03d}" for i in range(25)]
