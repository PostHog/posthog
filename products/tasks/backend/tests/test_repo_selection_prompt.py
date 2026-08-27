from products.tasks.backend.logic.repo_selection.agent import _build_repo_selection_prompt


def test_corrections_section_included_only_when_given() -> None:
    base = _build_repo_selection_prompt("ctx", ["acme/a", "acme/b"])
    assert "Past selection corrections" not in base

    with_corrections = _build_repo_selection_prompt("ctx", ["acme/a", "acme/b"], "- 2026-01-01: entry")
    assert "- 2026-01-01: entry" in with_corrections
    # The section sits between the candidate list and the cache instructions, so the agent reads
    # the corrections together with the candidates they constrain.
    assert (
        with_corrections.index("`acme/b`")
        < with_corrections.index("Past selection corrections")
        < with_corrections.index("## The cache")
    )
