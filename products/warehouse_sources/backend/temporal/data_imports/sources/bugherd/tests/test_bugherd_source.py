from products.warehouse_sources.backend.temporal.data_imports.sources.bugherd.bugherd import BugherdResumeConfig


def test_bugherd_resume_config_requires_page() -> None:
    resume_config = BugherdResumeConfig(page=7)
    assert resume_config.page == 7
