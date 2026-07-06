"""Tests for the OSS repo registry (pure data helpers)."""

from __future__ import annotations

from pathlib import Path

from products.signals.eval.agentic import repos


def test_registry_full_names_are_lowercased_and_well_formed():
    for key, repo in repos.REGISTRY.items():
        assert repo.key == key
        assert repo.full_name == repo.full_name.lower()
        assert "/" in repo.full_name
        assert repo.owner and repo.repo
        assert repo.ref and repo.clone_url.endswith(".git")


def test_candidate_full_names_preserves_order():
    names = repos.candidate_full_names(["cal", "posthog-python"])
    assert names == ["calcom/cal.com", "posthog/posthog-python"]


def test_by_full_name_is_case_insensitive():
    assert repos.by_full_name("CalCom/Cal.com") is repos.get("cal")
    assert repos.by_full_name("nope/nope") is None


def test_get_unknown_raises():
    try:
        repos.get("does-not-exist")
    except KeyError as exc:
        assert "unknown OSS repo" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected KeyError")


def test_sandbox_mount_map_render():
    rendered = repos.sandbox_mount_map({"calcom/cal.com": Path("/tmp/cal"), "posthog/posthog-js": Path("/tmp/js")})
    assert rendered == "calcom/cal.com:/tmp/cal,posthog/posthog-js:/tmp/js"
