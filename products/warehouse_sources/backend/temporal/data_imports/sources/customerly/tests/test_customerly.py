import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.customerly.customerly import (
    PAGE_SIZE,
    CustomerlyAuthenticationError,
    CustomerlyResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.customerly.source import CustomerlySource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.customerly import (
    CustomerlySourceConfig,
)


def _driver(access_token: str = "token") -> SourceDriver:
    return SourceDriver(CustomerlySource(), CustomerlySourceConfig(access_token=access_token))


def _users_page(count: int, start: int = 0) -> ScriptedResponse:
    return ScriptedResponse(json={"data": {"users": [{"crmhero_user_id": start + i} for i in range(count)]}})


class TestAuthErrorDetection:
    def test_auth_failure_masquerading_as_500_is_not_retried(self) -> None:
        # Customerly reports bad tokens as HTTP 500; treating that as a retryable server
        # error would retry a permanent credential failure forever.
        result = _driver("bad-token").run(
            "users",
            always(ScriptedResponse(status=500, json={"error": {"message": "Access token not found.", "code": 0}})),
        )

        assert isinstance(result.raised, CustomerlyAuthenticationError)
        assert len(result.requests) == 4


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
        ],
    )
    def test_status_mapping(self, status_code: int, expected: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            assert validate_credentials("token") is expected

        assert {request.path for request in network.requests_log} == {"/v1/tags"}

    def test_swallows_exceptions(self) -> None:
        with scripted_network(always(ConnectionError("boom"))) as network:
            assert validate_credentials("token") is False

        assert {request.path for request in network.requests_log} == {"/v1/tags"}


class TestGetRows:
    def test_paginates_until_short_page(self) -> None:
        result = _driver().run("users", [_users_page(PAGE_SIZE), _users_page(3, start=PAGE_SIZE)])

        assert result.raised is None
        assert [len(batch) for batch in result.items] == [PAGE_SIZE, 3]
        assert result.params("page") == ["0", "1"]
        # State is saved only after a full page, pointing at the next page to fetch.
        assert result.saved_states == [CustomerlyResumeConfig(page=1)]

    def test_resumes_from_saved_page(self) -> None:
        result = _driver().run("users", [_users_page(1)], resume_state=CustomerlyResumeConfig(page=7))

        assert result.raised is None
        assert result.params("page") == ["7"]

    def test_tags_are_normalized_into_rows(self) -> None:
        result = _driver().run("tags", [ScriptedResponse(json={"data": ["onboarding", "remarketing"]})])

        assert result.raised is None
        assert result.items == [[{"name": "onboarding"}, {"name": "remarketing"}]]
        assert result.paths == ["/v1/tags"]


class TestArticlesFanOut:
    def test_fans_out_over_collections_in_ascending_id_order(self) -> None:
        collections = {"data": [{"knowledge_base_collection_id": 6050}, {"knowledge_base_collection_id": 4517}]}
        articles_4517 = {"data": [{"knowledge_base_article_id": 1, "knowledge_base_collection_id": 4517}]}
        articles_6050 = {"data": [{"knowledge_base_article_id": 2, "knowledge_base_collection_id": 6050}]}
        result = _driver().run(
            "knowledge_base_articles",
            [
                ScriptedResponse(json=collections),
                ScriptedResponse(json=articles_4517),
                ScriptedResponse(json=articles_6050),
            ],
        )

        assert result.raised is None
        assert result.paths == ["/v1/knowledge/collections", "/v1/knowledge/articles/", "/v1/knowledge/articles/"]
        assert result.params("knowledge_base_collection_id") == [None, "4517", "6050"]
        assert [item["knowledge_base_article_id"] for item in result.rows] == [1, 2]

    def test_checkpoints_next_collection_after_each_collection(self) -> None:
        collections = {"data": [{"knowledge_base_collection_id": 4517}]}
        result = _driver().run(
            "knowledge_base_articles",
            [ScriptedResponse(json=collections), ScriptedResponse(json={"data": [{"knowledge_base_article_id": 1}]})],
        )

        assert result.raised is None
        assert result.saved_states == [CustomerlyResumeConfig(page=0, collection_id=4518)]

    def test_resume_skips_completed_collections_and_starts_at_saved_page(self) -> None:
        collections = {"data": [{"knowledge_base_collection_id": 4517}, {"knowledge_base_collection_id": 6050}]}
        result = _driver().run(
            "knowledge_base_articles",
            [ScriptedResponse(json=collections), ScriptedResponse(json={"data": [{"knowledge_base_article_id": 9}]})],
            resume_state=CustomerlyResumeConfig(page=3, collection_id=6050),
        )

        assert result.raised is None
        assert result.paths == ["/v1/knowledge/collections", "/v1/knowledge/articles/"]
        assert result.params("knowledge_base_collection_id") == [None, "6050"]
        assert result.params("page") == [None, "3"]
