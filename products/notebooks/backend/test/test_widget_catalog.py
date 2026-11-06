from products.notebooks.backend.facade.widget_catalog import (
    format_notebook_widget_catalog_for_agents,
    get_notebook_widget_catalog,
)


def test_widget_catalog_exports_every_supported_product_view() -> None:
    catalog = get_notebook_widget_catalog()
    expected_views = {
        "FeatureFlag": {"summary", "detail", "editor", "conditions", "implementation"},
        "Survey": {"summary", "detail", "preview", "conditions", "results"},
        "Experiment": {"summary", "detail", "results"},
        "EarlyAccessFeature": {"summary", "detail"},
        "Cohort": {"summary", "detail"},
        "Insight": {"summary", "detail", "editor", "results"},
        "Recording": {"summary", "detail"},
        "RecordingPlaylist": {"summary", "detail", "conditions"},
        "Person": {"summary", "detail", "activity"},
        "Group": {"summary", "detail", "activity"},
        "ErrorTrackingIssue": {"summary", "detail", "activity"},
        "LLMTrace": {"summary", "detail", "activity"},
        "Dashboard": {"summary", "detail"},
        "Action": {"summary", "detail", "editor"},
        "Workflow": {"summary", "detail", "editor", "results"},
    }

    actual_views = {
        tag_name: {widget.default_view.name or "detail", *widget.views.keys()}
        for tag_name, widget in catalog.widgets.items()
    }

    assert actual_views == expected_views


def test_widget_catalog_prompt_includes_compound_identity_props() -> None:
    prompt = format_notebook_widget_catalog_for_agents()

    assert '<Group id="group-key" groupTypeIndex={0} view="summary" />' in prompt
    assert '"attrs":{"id":"group-key","groupTypeIndex":0,"view":"summary"}' in prompt
    assert "groupTypeIndex: Numeric group type index." in prompt
