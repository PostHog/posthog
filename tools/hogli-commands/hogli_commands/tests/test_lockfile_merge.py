from __future__ import annotations

import pytest

from hogli.manifest import REPO_ROOT
from hogli_commands.lockfile_merge import _is_supported_layout, missing_resolutions

LOCKFILE_HEAD = """lockfileVersion: {version}

importers:

  .:
    dependencies:
"""


def _lockfile(importer_deps: str, packages: str = "", snapshots: str = "", version: str = "'9.0'") -> str:
    head = LOCKFILE_HEAD.format(version=version)
    return f"{head}{importer_deps}\npackages:\n\n{packages}\nsnapshots:\n\n{snapshots}"


class TestLockfileMerge:
    """A clean git merge of two valid lockfiles can produce an invalid one. These
    lock the shapes that made the first parser report live dependencies as broken,
    because a false positive here warns on every push."""

    @pytest.mark.parametrize(
        "importer_deps,packages,snapshots,version,expected",
        [
            pytest.param(
                "      posthog-js:\n        specifier: 'catalog:'\n        version: 1.433.6(react@18.3.1)\n",
                "",
                "  posthog-js@1.433.9(react@18.3.1): {}\n",
                "'9.0'",
                ["posthog-js@1.433.6(react@18.3.1)"],
                id="version-master-replaced-is-reported",
            ),
            pytest.param(
                "      posthog-js:\n        specifier: 'catalog:'\n        version: 1.433.9(react@18.3.1)\n",
                "",
                "  posthog-js@1.433.9(react@18.3.1): {}\n",
                "'9.0'",
                [],
                id="peer-suffixed-version-resolves",
            ),
            pytest.param(
                "      '@posthog/mcp-analytics':\n        specifier: 'catalog:'\n        version: '@posthog/mcp@0.16.3'\n",
                "",
                "  '@posthog/mcp@0.16.3': {}\n",
                "'9.0'",
                [],
                id="aliased-dependency-resolves-by-version-alone",
            ),
            pytest.param(
                "      uWebSockets.js:\n        specifier: https://example.com/a.tar.gz\n        version: https://example.com/a.tar.gz\n",
                "  uWebSockets.js@https://example.com/a.tar.gz:\n    resolution: {tarball: https://example.com/a.tar.gz}\n",
                "",
                "'9.0'",
                [],
                id="tarball-url-key-containing-a-colon-resolves",
            ),
            pytest.param(
                "      local-thing:\n        specifier: workspace:*\n        version: link:../local-thing\n",
                "",
                "",
                "'9.0'",
                [],
                id="workspace-link-needs-no-resolution",
            ),
            pytest.param(
                "      posthog-js:\n        specifier: 'catalog:'\n        version: 1.433.9\n",
                "",
                "",
                "'9.0'",
                ["posthog-js@1.433.9"],
                id="a-lockfile-that-resolves-nothing-is-broken-not-clean",
            ),
            pytest.param(
                "      posthog-js:\n        specifier: 'catalog:'\n        version: 1.433.9\n",
                "",
                "",
                "'10.0'",
                [],
                id="an-unknown-layout-is-not-this-parsers-to-judge",
            ),
        ],
    )
    def test_detects_only_genuinely_unresolved_dependencies(
        self, importer_deps: str, packages: str, snapshots: str, version: str, expected: list[str]
    ) -> None:
        assert missing_resolutions(_lockfile(importer_deps, packages, snapshots, version)) == expected

    def test_the_repos_own_lockfile_is_clean(self) -> None:
        # A parser regression that reports a false positive here would warn on
        # every push, so this guards the checked-in lockfile rather than a fixture.
        lockfile = (REPO_ROOT / "pnpm-lock.yaml").read_text()
        # Asserted first: an unsupported layout makes the line below pass while
        # the check does nothing, so a pnpm major bump must fail here instead.
        assert _is_supported_layout(lockfile)
        assert missing_resolutions(lockfile) == []
