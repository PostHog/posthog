import re
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from django.test import override_settings

import yaml
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from parameterized import parameterized

from posthog.models.github_integration_base import GitHubIntegrationError

from products.skills.backend.api.community_publish_services import (
    MAX_TAG_LENGTH,
    CommunitySkillPublishError,
    CommunitySkillPublishValidationError,
    get_community_skills_publisher,
    publish_skill_to_community,
    publisher_branch_key,
    render_community_skill_files,
    render_skill_md,
)
from products.skills.backend.api.skill_services import MAX_SKILL_BODY_BYTES, MAX_SKILL_FILE_BYTES, MAX_SKILL_FILE_COUNT
from products.skills.backend.marketplace.packaging import SPEC_DESCRIPTION_MAX_LENGTH

# Mirror of the community-skills repo's frontmatter parser (scripts/build_registry.py) so these
# tests fail if we ever render a SKILL.md the repo's own CI would reject.
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)$", re.DOTALL)


def _parse(content: str) -> tuple[dict, str]:
    match = FRONTMATTER_RE.match(content)
    assert match is not None, "rendered SKILL.md must start with a YAML frontmatter block"
    return yaml.safe_load(match.group(1)) or {}, match.group(2).strip()


class TestRenderSkillMd:
    def test_renders_required_fields_and_body(self) -> None:
        content = render_skill_md(
            name="Make PR", description="Open a PR for the current branch.", body="# Make PR\n\nDo it."
        )
        frontmatter, body = _parse(content)
        assert frontmatter["name"] == "Make PR"
        assert frontmatter["description"] == "Open a PR for the current branch."
        assert frontmatter["trust_tier"] == "community"
        assert body == "# Make PR\n\nDo it."

    def test_optional_fields_omitted_when_empty(self) -> None:
        frontmatter, _ = _parse(render_skill_md(name="X", description="Y", body="Z"))
        for omitted in ("tags", "author_handle", "license", "compatibility", "allowed_tools"):
            assert omitted not in frontmatter

    def test_optional_fields_included_when_set(self) -> None:
        content = render_skill_md(
            name="Make PR",
            description="Open a PR.",
            body="body",
            tags=["github", "workflow"],
            allowed_tools=["query", "docs-search"],
            license="MIT",
            compatibility="Requires gh",
            author_handle="andymaguire",
        )
        frontmatter, _ = _parse(content)
        assert frontmatter["tags"] == ["github", "workflow"]
        assert frontmatter["allowed_tools"] == ["query", "docs-search"]
        assert frontmatter["license"] == "MIT"
        assert frontmatter["compatibility"] == "Requires gh"
        assert frontmatter["author_handle"] == "andymaguire"

    def test_preserves_leading_whitespace_in_the_body(self) -> None:
        # strip() would turn an opening indented code block into an ordinary paragraph, so the
        # published skill would instruct differently from the skill it was published from.
        content = render_skill_md(name="X", description="Y", body="    indented code\n\ntext\n\n\n")

        assert content.endswith("---\n\n    indented code\n\ntext\n")

    @parameterized.expand(
        [
            ("blank name", "  ", "d", "b"),
            ("blank description", "n", "", "b"),
            # install_community_skill refuses a blank body as having no instructions, so publishing
            # one merges a listing that nobody can ever install.
            ("blank body", "n", "d", "  \n  "),
            # Longer than the Agent Skills spec allows, so validate_for_export refuses the skill once
            # someone installs it from the catalog.
            ("description over the spec cap", "n", "x" * (SPEC_DESCRIPTION_MAX_LENGTH + 1), "b"),
            # Longer than CommunitySkill.name: the PR would merge and ingest would then drop the entry.
            ("name over 64 chars", "x" * 65, "d", "b"),
            # The name becomes the commit message, where a trailer would reattribute the App's commit.
            ("name spanning two lines", "Make PR\nCo-authored-by: someone <a@b.c>", "d", "b"),
        ]
    )
    def test_requires_the_fields_a_listing_cannot_do_without(
        self, _label: str, name: str, description: str, body: str
    ) -> None:
        with pytest.raises(CommunitySkillPublishError):
            render_skill_md(name=name, description=description, body=body)

    @parameterized.expand(
        [
            ("with a space in it", "not a handle"),
            ("with a double hyphen", "andy--maguire"),
            # 77 characters: the pattern's repetition can contribute a hyphen and a character each, so
            # nothing bounds the total unless the length is held beside it, and the listing would
            # attribute the skill to a handle GitHub cannot hold.
            ("longer than a GitHub username", "-".join("a" for _ in range(39))),
        ]
    )
    def test_rejects_an_author_handle_that_is_not_a_github_username(self, _label: str, handle: str) -> None:
        with pytest.raises(CommunitySkillPublishError):
            render_skill_md(name="n", description="d", body="b", author_handle=handle)

    @parameterized.expand(
        [
            ("a tool name with a space", ["Bash Write"]),
            ("a tool name with a newline", ["Bash\nWrite"]),
            ("a tool name that is not a string", [123]),
        ]
    )
    def test_rejects_allowed_tools_ingest_would_drop(self, _label: str, allowed_tools: list[Any]) -> None:
        # create_skill stores what a tool call passed without the REST serializer's checks, and
        # ingest rejects a whitespace-bearing or non-string tool name, so publishing one opens a
        # pull request that merges and whose skill never appears in the catalog.
        with pytest.raises(CommunitySkillPublishError):
            render_skill_md(name="n", description="d", body="b", allowed_tools=allowed_tools)


class TestRenderCommunitySkillFiles:
    def test_skill_md_path_and_bundled_files(self) -> None:
        rendered = render_community_skill_files(
            slug="make-pr",
            name="Make PR",
            description="Open a PR.",
            body="body",
            files=[
                {"path": "references/playbook.md", "content": "hints", "content_type": "text/markdown"},
                # A skill created through the Max tool can store the backslash spelling, and ingest
                # canonicalizes it, so the publish has to write the forward-slash path ingest will
                # then look for rather than one flat `scripts\\run.sh` tree entry.
                {"path": "scripts\\run.sh", "content": "echo hi", "content_type": "text/plain"},
            ],
        )
        paths = {f.path for f in rendered}
        assert paths == {
            "skills/make-pr/SKILL.md",
            "skills/make-pr/references/playbook.md",
            "skills/make-pr/scripts/run.sh",
        }

    def test_rejects_bad_slug(self) -> None:
        # "new" and the category-tab slugs are rejected by ingest, so publishing one merges a pull
        # request whose skill never appears in the catalog. A trailing newline needs `fullmatch`.
        for bad in ["Make-PR", "make_pr", "-bad", "double--hyphen", "x" * 65, "new", "review-hog", "make-pr\n"]:
            try:
                render_community_skill_files(slug=bad, name="n", description="d", body="b")
            except CommunitySkillPublishError:
                continue
            raise AssertionError(f"expected rejection for slug {bad!r}")

    @parameterized.expand(
        [
            ("path traversal", ["../escape.md"]),
            ("overwriting the rendered SKILL.md", ["SKILL.md"]),
            # Ingest case-folds paths and drops the whole entry on a collision, so publishing both
            # opens a pull request that merges and then never appears in the catalog.
            ("paths differing only by case", ["references/Guide.md", "references/guide.md"]),
            # Same reason: ingest canonicalizes the backslash spelling, so the two paths that look
            # distinct here are one duplicate path by the time the merged entry is read.
            ("the same path spelled with a backslash", ["references\\guide.md", "references/guide.md"]),
            ("an absolute path", ["/references/guide.md"]),
            # A git tree can't hold `references` as both a blob and a directory, so GitHub rejects
            # the whole tree and the skill can't be published at all.
            ("a name used as both file and folder", ["references", "references/guide.md"]),
        ]
    )
    def test_rejects_unpublishable_bundled_file_paths(self, _label: str, paths: list[str]) -> None:
        with pytest.raises(CommunitySkillPublishError):
            render_community_skill_files(
                slug="make-pr",
                name="n",
                description="d",
                body="b",
                files=[{"path": path, "content": "x", "content_type": "text/plain"} for path in paths],
            )


class TestPublishableSize:
    @parameterized.expand(
        [
            # Ingest's own per-entry caps: breaching one drops the whole entry, so the pull request
            # merges and the skill never appears in the catalog.
            ("body over the catalog cap", "x" * (MAX_SKILL_BODY_BYTES + 1), 1, 10),
            ("more files than the catalog takes", "b", MAX_SKILL_FILE_COUNT + 1, 10),
            ("one file over the catalog cap", "b", 1, MAX_SKILL_FILE_BYTES + 1),
            # GitHub's cap on a single create-tree request, which inlines every file's content.
            ("files summing over the tree cap", "b", 6, MAX_SKILL_FILE_BYTES),
        ]
    )
    def test_rejects_a_skill_no_publish_could_survive(
        self, _label: str, body: str, file_count: int, file_size: int
    ) -> None:
        with pytest.raises(CommunitySkillPublishError):
            render_community_skill_files(
                slug="make-pr",
                name="n",
                description="d",
                body=body,
                files=[
                    {"path": f"references/{index}.md", "content": "x" * file_size, "content_type": "text/markdown"}
                    for index in range(file_count)
                ],
            )

    def test_counts_the_rendered_frontmatter_against_the_tree_cap(self) -> None:
        # Nothing caps how many tags a skill stores, and every one is rendered into SKILL.md, so
        # measuring the fields the files came from instead of the files themselves leaves the
        # difference between them unbounded.
        files = [
            {"path": f"references/{index}.md", "content": "x" * MAX_SKILL_FILE_BYTES, "content_type": "text/markdown"}
            for index in range(4)
        ]
        fields: dict[str, Any] = {"slug": "make-pr", "name": "n", "description": "d", "body": "x" * 990_000}

        render_community_skill_files(**fields, files=files)

        with pytest.raises(CommunitySkillPublishError):
            render_community_skill_files(**fields, files=files, tags=["t" * MAX_TAG_LENGTH] * 4000)

    def test_rejects_a_skill_whose_encoded_payload_blows_the_tree_cap(self) -> None:
        # 3 MB of newlines clears every raw-byte check, and doubles once escaped into the single JSON
        # body the tree write inlines it in. Counted raw, this publishes and then fails against
        # GitHub with a 502 the publisher can do nothing with.
        with pytest.raises(CommunitySkillPublishError):
            render_community_skill_files(
                slug="make-pr",
                name="n",
                description="d",
                body="b",
                files=[
                    {
                        "path": f"references/{index}.md",
                        "content": "\n" * MAX_SKILL_FILE_BYTES,
                        "content_type": "text/markdown",
                    }
                    for index in range(3)
                ],
            )


# Generated per run rather than checked in: a PEM in a public repo trips secret scanners, and the
# publisher settings take a real key because the App JWT is signed for real in these tests.
PUBLISHER_PRIVATE_KEY = (
    rsa.generate_private_key(public_exponent=65537, key_size=2048)
    .private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    .decode()
)
PUBLISHER_SETTINGS = {
    "COMMUNITY_SKILLS_GITHUB_INSTALLATION_ID": "4242",
    "COMMUNITY_SKILLS_GITHUB_REPO": "community-skills",
    "COMMUNITY_SKILLS_GITHUB_APP_CLIENT_ID": "Iv23licommunity",
    "COMMUNITY_SKILLS_GITHUB_APP_PRIVATE_KEY": PUBLISHER_PRIVATE_KEY,
    # A usable core App, which the publish path must never fall back to: that App is installed
    # across the whole PostHog org, so a fallback hands publishing a credential for every
    # repository in it. Configured here so every case below holds publishing to its own App.
    "GITHUB_APP_CLIENT_ID": "core",
    "GITHUB_APP_PRIVATE_KEY": PUBLISHER_PRIVATE_KEY,
}


class TestCommunitySkillsPublisher:
    def _response(self, status_code: int, payload: dict) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.json.return_value = payload
        return response

    @override_settings(**PUBLISHER_SETTINGS)
    @patch("products.skills.backend.api.community_publish_services._publisher_app_request")
    def test_mints_a_token_scoped_to_the_publish_repository(self, mock_request: MagicMock) -> None:
        mock_request.side_effect = [
            self._response(200, {"account": {"login": "PostHog", "type": "Organization"}}),
            self._response(201, {"token": "ghs_x"}),
        ]

        publisher = get_community_skills_publisher()
        assert publisher is not None
        # Every write the publisher makes must share the App-JWT calls' egress label.
        assert publisher.source == "community_skills"

        mint_body = mock_request.call_args.kwargs["json_body"]
        assert mint_body["repositories"] == ["community-skills"]
        # A publish writes files and opens a pull request. Anything else the installation holds is
        # blast radius this transient token has no use for.
        assert mint_body["permissions"] == {"contents": "write", "pull_requests": "write", "metadata": "read"}

    @parameterized.expand(
        [
            ("the app is not installed here", 404, False),
            ("github refuses the app credentials", 401, False),
            ("github fails the mint", 500, True),
        ]
    )
    def test_only_a_refused_installation_reads_as_not_configured(
        self, _label: str, token_status: int, is_gateway_failure: bool
    ) -> None:
        # None here becomes the endpoint's 503, which tells the publisher this instance can't publish
        # at all. A transient failure must not say that: it sends them to the manual path over an
        # outage that clears by itself.
        with (
            override_settings(**PUBLISHER_SETTINGS),
            patch("products.skills.backend.api.community_publish_services._publisher_app_request") as mock_request,
        ):
            mock_request.side_effect = [
                self._response(200, {"account": {"login": "PostHog", "type": "Organization"}}),
                self._response(token_status, {}),
            ]

            if is_gateway_failure:
                with pytest.raises(CommunitySkillPublishError):
                    get_community_skills_publisher()
            else:
                assert get_community_skills_publisher() is None

    @override_settings(**PUBLISHER_SETTINGS)
    @patch("products.skills.backend.api.community_publish_services._publisher_app_request")
    def test_github_being_unreachable_while_minting_raises_a_publish_error(self, mock_request: MagicMock) -> None:
        # The App-JWT calls go to the transport directly, so a timeout arrives raw rather than as the
        # GitHubIntegrationError api_request would wrap it in. Unhandled, the endpoint answers 500.
        mock_request.side_effect = requests.ConnectTimeout("boom")

        with pytest.raises(CommunitySkillPublishError):
            get_community_skills_publisher()

    @parameterized.expand(
        [
            ("no client id", {"COMMUNITY_SKILLS_GITHUB_APP_CLIENT_ID": ""}),
            ("no private key", {"COMMUNITY_SKILLS_GITHUB_APP_PRIVATE_KEY": ""}),
            ("a private key that cannot sign", {"COMMUNITY_SKILLS_GITHUB_APP_PRIVATE_KEY": "not-a-pem"}),
            ("no installation", {"COMMUNITY_SKILLS_GITHUB_INSTALLATION_ID": ""}),
        ]
    )
    def test_an_unusable_publisher_app_never_reaches_github(self, _label: str, overrides: dict[str, str]) -> None:
        # Publishing is off on this instance, which is the endpoint's 503. Reaching GitHub anyway
        # would answer a deployment nobody can retry their way out of as though it were an outage,
        # and reaching it under the core App would publish with an org-wide credential.
        with (
            override_settings(**{**PUBLISHER_SETTINGS, **overrides}),
            patch(
                "products.skills.backend.api.community_publish_services._publisher_app_request",
                side_effect=AssertionError("GitHub was called with an unusable publisher App"),
            ),
        ):
            assert get_community_skills_publisher() is None


TEAM_A = "11111111-1111-1111-1111-111111111111"
TEAM_B = "22222222-2222-2222-2222-222222222222"
# Branch for slug "make-pr" published by TEAM_A.
TEAM_A_BRANCH = f"community-skill/make-pr-{publisher_branch_key(TEAM_A)}"


class TestPublishSkillToCommunity:
    def _publisher(self, *, open_pr: dict | None = None) -> MagicMock:
        publisher = MagicMock()
        publisher.get_open_pull_request_for_head.return_value = open_pr
        publisher.commit_files_to_branch.return_value = {"success": True, "commit_sha": "abc123"}
        publisher.create_pull_request.return_value = {
            "success": True,
            "pr_number": 12,
            "pr_url": "https://github.com/PostHog/community-skills/pull/12",
        }
        publisher.delete_branch.return_value = {"success": True}
        return publisher

    def _publish(self, publisher: MagicMock, *, publisher_id: str = TEAM_A) -> dict:
        with patch(
            "products.skills.backend.api.community_publish_services.get_community_skills_publisher",
            return_value=publisher,
        ):
            return publish_skill_to_community(
                slug="make-pr",
                publisher_id=publisher_id,
                name="Make PR",
                description="Open a PR.",
                body="body",
                files=[{"path": "references/playbook.md", "content": "hints", "content_type": "text/markdown"}],
            )

    def test_a_skill_that_cannot_be_published_is_rejected_before_the_publisher_is_acquired(self) -> None:
        # Acquiring the publisher talks to GitHub, so a skill that fails rendering used to come back
        # as 502 or 503 whenever the App was down or unconfigured — advice to retry, for a publish
        # that can only succeed once the publisher edits the skill.
        with patch(
            "products.skills.backend.api.community_publish_services.get_community_skills_publisher",
            side_effect=AssertionError("the publisher was acquired before the skill was validated"),
        ):
            with pytest.raises(CommunitySkillPublishValidationError):
                publish_skill_to_community(
                    slug="make-pr", publisher_id=TEAM_A, name="Make PR", description="", body="body"
                )

    def test_commits_every_file_in_one_commit(self) -> None:
        publisher = self._publisher()

        result = self._publish(publisher)

        assert result == {
            "pr_url": "https://github.com/PostHog/community-skills/pull/12",
            "pr_number": 12,
            "branch": TEAM_A_BRANCH,
        }
        publisher.commit_files_to_branch.assert_called_once()
        # The skill's directory is replaced, not merged onto main, so a bundled file dropped since
        # the last publish stops being published instead of surviving on the branch.
        assert publisher.commit_files_to_branch.call_args.kwargs["replace_directory"] == "skills/make-pr"
        committed_files = publisher.commit_files_to_branch.call_args.args[3]
        assert set(committed_files) == {"skills/make-pr/SKILL.md", "skills/make-pr/references/playbook.md"}

    @parameterized.expand(
        [
            ("transient github failure", "GitHub said no", True),
            # A branch that already heads a pull request belongs to that review, not to this call.
            ("pull request already exists", "A pull request already exists for PostHog:community-skill/x.", False),
        ]
    )
    def test_branch_cleanup_when_the_pull_request_fails(self, _label: str, error: str, deleted: bool) -> None:
        publisher = self._publisher()
        publisher.create_pull_request.return_value = {"success": False, "error": error}

        with pytest.raises(CommunitySkillPublishError):
            self._publish(publisher)

        assert publisher.delete_branch.called is deleted
        if deleted:
            assert publisher.delete_branch.call_args.args[1] == TEAM_A_BRANCH

    def test_reuses_the_open_pull_request_for_the_same_skill(self) -> None:
        publisher = self._publisher(
            open_pr={"number": 5, "url": "https://github.com/PostHog/community-skills/pull/5", "base": "main"}
        )

        result = self._publish(publisher)

        assert result["pr_number"] == 5
        publisher.create_pull_request.assert_not_called()
        publisher.commit_files_to_branch.assert_called_once()

    def test_a_reused_pull_request_that_ends_mid_publish_opens_a_new_one(self) -> None:
        # Open when we look before the write, merged by the time the commit lands. Returning it would
        # report success for a review that no longer carries the commit, and leave that commit on a
        # public branch with nothing open over it.
        open_pr = {"number": 5, "url": "https://github.com/PostHog/community-skills/pull/5", "base": "main"}
        publisher = self._publisher(open_pr=open_pr)
        publisher.get_open_pull_request_for_head.side_effect = [open_pr, None]

        result = self._publish(publisher)

        assert result["pr_number"] == 12
        publisher.create_pull_request.assert_called_once()
        publisher.delete_branch.assert_not_called()

    def test_refuses_a_pull_request_retargeted_away_from_the_base_branch(self) -> None:
        # Merging it writes to that other branch, so the skill never reaches the catalog. Reusing it
        # would report a successful publish for content nothing will ever pick up.
        publisher = self._publisher(
            open_pr={"number": 5, "url": "https://github.com/PostHog/community-skills/pull/5", "base": "draft"}
        )

        with pytest.raises(CommunitySkillPublishError):
            self._publish(publisher)

        publisher.commit_files_to_branch.assert_not_called()
        publisher.delete_branch.assert_not_called()

    def test_another_team_publishing_the_same_slug_writes_its_own_branch(self) -> None:
        # Slugs are unique per team, so a slug-only branch would let team B rewrite team A's open PR.
        publisher = self._publisher()

        self._publish(publisher, publisher_id=TEAM_B)

        branch = publisher.commit_files_to_branch.call_args.args[1]
        assert branch.startswith("community-skill/make-pr-")
        assert branch != TEAM_A_BRANCH

    def test_a_concurrent_publish_returns_the_pull_request_that_won_the_race(self) -> None:
        # Both requests force-update the same branch, so the loser's commit is already inside the
        # winner's review. Reporting a failure would deny content that is public by then.
        publisher = self._publisher()
        winner = {"number": 9, "url": "https://github.com/PostHog/community-skills/pull/9", "base": "main"}
        publisher.get_open_pull_request_for_head.side_effect = [None, winner]
        publisher.create_pull_request.return_value = {
            "success": False,
            "error": "A pull request already exists for PostHog:community-skill/x.",
        }

        result = self._publish(publisher)

        assert result["pr_number"] == 9
        publisher.delete_branch.assert_not_called()

    def test_a_pull_request_create_that_times_out_after_landing_keeps_the_branch(self) -> None:
        # api_request doesn't retry a POST, so a transport failure here can still have opened the
        # pull request. Cleaning up blind would delete a branch under live review.
        publisher = self._publisher()
        landed = {"number": 9, "url": "https://github.com/PostHog/community-skills/pull/9", "base": "main"}
        publisher.get_open_pull_request_for_head.side_effect = [None, landed]
        publisher.create_pull_request.side_effect = GitHubIntegrationError("timeout")

        result = self._publish(publisher)

        assert result["pr_number"] == 9
        publisher.delete_branch.assert_not_called()

    def test_a_pull_request_create_that_times_out_with_nothing_landed_deletes_the_branch(self) -> None:
        publisher = self._publisher()
        publisher.get_open_pull_request_for_head.side_effect = [None, None]
        publisher.create_pull_request.side_effect = GitHubIntegrationError("timeout")

        with pytest.raises(CommunitySkillPublishError):
            self._publish(publisher)

        assert publisher.delete_branch.call_args.args[1] == TEAM_A_BRANCH
        # Conditional on our own commit: the branch name is shared with every concurrent publish of
        # this skill from this team, and deleting theirs destroys work only we could have recovered.
        assert publisher.delete_branch.call_args.kwargs["expected_sha"] == "abc123"

    def test_github_being_unreachable_raises_a_publish_error(self) -> None:
        publisher = self._publisher()
        publisher.get_open_pull_request_for_head.side_effect = GitHubIntegrationError("network error")

        with pytest.raises(CommunitySkillPublishError):
            self._publish(publisher)
