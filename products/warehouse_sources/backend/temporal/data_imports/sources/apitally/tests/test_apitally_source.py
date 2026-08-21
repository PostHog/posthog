from products.warehouse_sources.backend.temporal.data_imports.sources.apitally.apitally import ApitallyResumeConfig


def test_apitally_resume_config_defaults_to_no_token() -> None:
    assert ApitallyResumeConfig().next_token is None
