import re

import yaml

from products.skills.backend.api.community_publish_services import (
    CommunitySkillPublishError,
    render_community_skill_files,
    render_skill_md,
)

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

    def test_requires_name_and_description(self) -> None:
        for kwargs in ({"name": "  ", "description": "d"}, {"name": "n", "description": ""}):
            try:
                render_skill_md(body="b", **kwargs)
            except CommunitySkillPublishError:
                continue
            raise AssertionError(f"expected CommunitySkillPublishError for {kwargs}")


class TestRenderCommunitySkillFiles:
    def test_skill_md_path_and_bundled_files(self) -> None:
        rendered = render_community_skill_files(
            slug="make-pr",
            name="Make PR",
            description="Open a PR.",
            body="body",
            files=[{"path": "references/playbook.md", "content": "hints", "content_type": "text/markdown"}],
        )
        paths = {f.path for f in rendered}
        assert paths == {"skills/make-pr/SKILL.md", "skills/make-pr/references/playbook.md"}

    def test_rejects_bad_slug(self) -> None:
        for bad in ["Make-PR", "make_pr", "-bad", "double--hyphen", "x" * 65]:
            try:
                render_community_skill_files(slug=bad, name="n", description="d", body="b")
            except CommunitySkillPublishError:
                continue
            raise AssertionError(f"expected rejection for slug {bad!r}")

    def test_rejects_path_traversal_in_bundled_file(self) -> None:
        try:
            render_community_skill_files(
                slug="make-pr",
                name="n",
                description="d",
                body="b",
                files=[{"path": "../escape.md", "content": "x", "content_type": "text/plain"}],
            )
        except CommunitySkillPublishError:
            return
        raise AssertionError("expected rejection for path traversal")
