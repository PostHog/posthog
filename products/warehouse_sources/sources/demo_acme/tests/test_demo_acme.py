from products.warehouse_sources.sources.demo_acme._config import DemoAcmeSourceConfig
from products.warehouse_sources.sources.demo_acme.source import DemoAcmeResumeConfig, DemoAcmeSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver


def test_resume_starts_at_the_saved_page_and_checkpoints_each_next_page() -> None:
    driver = SourceDriver(DemoAcmeSource(), DemoAcmeSourceConfig(api_key="test-key"))

    result = driver.run(
        "Widgets",
        [
            ScriptedResponse(json={"data": [{"id": 1}]}),
            ScriptedResponse(json={"data": [{"id": 2}]}),
            ScriptedResponse(json={"data": []}),
        ],
        resume_state=DemoAcmeResumeConfig(next_page=3),
    )

    assert result.raised is None
    assert result.params("page") == ["3", "4", "5"]
    assert [row["id"] for row in result.rows] == [1, 2]
    assert result.saved_states == [DemoAcmeResumeConfig(next_page=4), DemoAcmeResumeConfig(next_page=5)]
