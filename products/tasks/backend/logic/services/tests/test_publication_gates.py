import hashlib

import pytest

from products.tasks.backend.logic.services.publication_base import TrustedBaseManifest, TrustedBaseTextBlob
from products.tasks.backend.logic.services.publication_gates import (
    PublicationGatePolicyError,
    assert_publication_gate_paths_safe,
    resolve_publication_gate_policy,
)


def _manifest(policy: str | None) -> TrustedBaseManifest:
    blobs = (
        ()
        if policy is None
        else (TrustedBaseTextBlob(path=".posthog/pulse-publication-gates.json", object_sha="a" * 40, text=policy),)
    )
    return TrustedBaseManifest(
        repository="owner/repository",
        base_sha="b" * 40,
        tree_sha="c" * 40,
        entries=(),
        old_text_blobs=blobs,
    )


def test_resolves_only_a_versioned_protected_base_gate_policy() -> None:
    policy_document = (
        '{"version":2,"gates":[{"label":"focused tests","argv":["pnpm","test","--","--runInBand"]}],'
        '"protected_path_prefixes":["package.json","bin/hogli"]}'
    )

    policy = resolve_publication_gate_policy(_manifest(policy_document))

    assert policy.status == "ready"
    assert policy.source_path == ".posthog/pulse-publication-gates.json"
    assert policy.source_sha256 == hashlib.sha256(policy_document.encode()).hexdigest()
    assert policy.gates[0].label == "focused tests"
    assert policy.gates[0].argv == ("pnpm", "test", "--", "--runInBand")
    assert policy.protected_path_prefixes == ("package.json", "bin/hogli")


def test_refuses_to_publish_when_the_protected_base_has_no_supported_gate_policy() -> None:
    policy = resolve_publication_gate_policy(_manifest("{}"))

    assert policy.status == "unavailable"
    assert policy.reason == "gate_policy_unavailable"
    assert policy.gates == ()


def test_refuses_unknown_keys_and_shell_commands() -> None:
    policy = resolve_publication_gate_policy(
        _manifest('{"version":2,"gates":[{"label":"tests","command":"pytest"}],"extra":true}')
    )

    assert policy.status == "unavailable"


def test_rejects_a_normalized_change_to_a_protected_runner_or_manifest() -> None:
    policy = resolve_publication_gate_policy(
        _manifest(
            '{"version":2,"gates":[{"label":"tests","argv":["pytest"]}],'
            '"protected_path_prefixes":["package.json","bin/hogli","frontend/vite.config.ts"]}'
        )
    )

    with pytest.raises(PublicationGatePolicyError, match="publication_gate_protected_path_changed"):
        assert_publication_gate_paths_safe(policy, ("package.json", "frontend/vite.config.ts"))


def test_rejects_a_change_to_the_gate_policy_even_when_it_is_not_a_configured_prefix() -> None:
    policy = resolve_publication_gate_policy(
        _manifest(
            '{"version":2,"gates":[{"label":"tests","argv":["pytest"]}],"protected_path_prefixes":["package.json"]}'
        )
    )

    with pytest.raises(PublicationGatePolicyError, match="publication_gate_protected_path_changed"):
        assert_publication_gate_paths_safe(policy, (".posthog/pulse-publication-gates.json",))


def test_allows_unprotected_paths_without_prefix_confusion() -> None:
    policy = resolve_publication_gate_policy(
        _manifest(
            '{"version":2,"gates":[{"label":"tests","argv":["pytest"]}],'
            '"protected_path_prefixes":["package.json","bin/hogli"]}'
        )
    )

    assert_publication_gate_paths_safe(policy, ("package.json.bak", "bin/hogli-helper", "products/tasks/example.py"))


@pytest.mark.parametrize("path", ("../package.json", "package.json/../test.py", "/package.json", "package.json\\test"))
def test_rejects_non_normalized_changed_paths(path: str) -> None:
    policy = resolve_publication_gate_policy(
        _manifest(
            '{"version":2,"gates":[{"label":"tests","argv":["pytest"]}],"protected_path_prefixes":["package.json"]}'
        )
    )

    with pytest.raises(PublicationGatePolicyError, match="publication_gate_protected_path_changed"):
        assert_publication_gate_paths_safe(policy, (path,))
