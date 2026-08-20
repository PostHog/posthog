import time

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User

from ...models.community_skills import CommunitySkill, CommunitySkillFile, CommunitySkillVote
from ...models.skills import LLMSkill
from ..skill_template_services import (
    MAX_RENDERED_SKILL_BYTES,
    MAX_TEMPLATE_BINDINGS_BYTES,
    MAX_TEMPLATE_VARIABLE_BYTES,
    MissingTemplateVariableError,
    TemplateRenderTooLargeError,
    TemplateVariableTooLargeError,
    UnknownSuppliedVariableError,
    UnknownTemplatePlaceholderError,
    is_template,
    parse_template_variables,
    render_template_skill,
)

try:
    from ee.models.rbac.access_control import AccessControl
except ImportError:
    pass


def _create_community_skill(
    *,
    slug: str = "web-analytics-triage",
    name: str = "Web analytics triage",
    trust_tier: str = "official",
    install_count: int = 0,
    deleted: bool = False,
) -> CommunitySkill:
    return CommunitySkill.objects.create(
        slug=slug,
        name=name,
        description="Investigate a change in web traffic.",
        body="# Triage\nDo the thing.",
        trust_tier=trust_tier,
        tags=["web-analytics"],
        install_count=install_count,
        deleted=deleted,
    )


def _create_template_skill(*, slug: str = "feed-scout") -> CommunitySkill:
    return CommunitySkill.objects.create(
        slug=slug,
        name="Feed scout",
        description="Watch a feed for problems.",
        body="# Scout\nWatch table {{ feed_table }} on {{ default_branch }}.",
        trust_tier="official",
        source_sha="sha123",
        metadata={
            "variables": [
                {"name": "feed_table", "prompt": "Warehouse table", "required": True},
                {"name": "default_branch", "prompt": "Branch", "default": "main"},
            ]
        },
    )


@patch(
    "products.skills.backend.api.community_skills.posthoganalytics.feature_enabled",
    return_value=True,
)
class TestCommunitySkillAPI(APIBaseTest):
    def _url(self, path: str = "") -> str:
        return f"/api/projects/{self.team.id}/community_skills/{path}"

    def test_list_returns_published_skills_ordered_by_installs(self, _mock_flag) -> None:
        _create_community_skill(slug="alpha", install_count=1)
        _create_community_skill(slug="beta", install_count=5)

        response = self.client.get(self._url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        self.assertEqual([s["slug"] for s in results], ["beta", "alpha"])
        self.assertNotIn("body", results[0])  # list serializer omits body

    def test_list_excludes_deleted(self, _mock_flag) -> None:
        _create_community_skill(slug="visible")
        _create_community_skill(slug="gone", deleted=True)

        response = self.client.get(self._url())
        self.assertEqual([s["slug"] for s in response.json()["results"]], ["visible"])

    def test_filter_by_trust_tier(self, _mock_flag) -> None:
        _create_community_skill(slug="official-one", trust_tier="official")
        _create_community_skill(slug="community-one", trust_tier="community")

        response = self.client.get(self._url(), {"trust_tier": "community"})
        self.assertEqual([s["slug"] for s in response.json()["results"]], ["community-one"])

    def test_filter_by_tag_is_case_insensitive(self, _mock_flag) -> None:
        _create_community_skill(slug="tagged")  # stored tag is lowercase "web-analytics"
        # A differently-cased tag query must still match the stored tag.
        response = self.client.get(self._url(), {"tag": "Web-Analytics"})
        self.assertEqual([s["slug"] for s in response.json()["results"]], ["tagged"])

    def test_retrieve_by_slug_includes_body(self, _mock_flag) -> None:
        _create_community_skill(slug="web-analytics-triage")
        response = self.client.get(self._url("web-analytics-triage/"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["body"], "# Triage\nDo the thing.")

    def test_install_creates_team_skill_and_increments_count(self, _mock_flag) -> None:
        skill = _create_community_skill(slug="web-analytics-triage")
        CommunitySkillFile.objects.create(skill=skill, path="references/playbook.md", content="hints")

        response = self.client.post(self._url("web-analytics-triage/install/"), {})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)

        installed = LLMSkill.objects.get(team=self.team, name="web-analytics-triage")
        self.assertEqual(installed.body, "# Triage\nDo the thing.")
        self.assertEqual(installed.metadata["community_skill_slug"], "web-analytics-triage")
        self.assertEqual(installed.files.count(), 1)

        skill.refresh_from_db()
        self.assertEqual(skill.install_count, 1)

    def test_install_with_custom_name(self, _mock_flag) -> None:
        _create_community_skill(slug="web-analytics-triage")
        response = self.client.post(self._url("web-analytics-triage/install/"), {"new_name": "my-triage"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        self.assertTrue(LLMSkill.objects.filter(team=self.team, name="my-triage").exists())

    def test_install_default_name_conflict_omits_new_name_attr(self, _mock_flag) -> None:
        _create_community_skill(slug="web-analytics-triage")
        LLMSkill.objects.create(team=self.team, name="web-analytics-triage", description="x", body="y")

        response = self.client.post(self._url("web-analytics-triage/install/"), {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        # Caller never supplied new_name, so the response must not blame that field.
        self.assertNotIn("attr", response.json())

    def test_install_custom_name_conflict_blames_new_name(self, _mock_flag) -> None:
        _create_community_skill(slug="web-analytics-triage")
        LLMSkill.objects.create(team=self.team, name="taken", description="x", body="y")

        response = self.client.post(self._url("web-analytics-triage/install/"), {"new_name": "taken"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json().get("attr"), "new_name")

    def test_install_blank_new_name_falls_back_to_slug(self, _mock_flag) -> None:
        _create_community_skill(slug="web-analytics-triage")
        # A controlled empty text input sends "" — it must mean "use the default", not 400.
        response = self.client.post(self._url("web-analytics-triage/install/"), {"new_name": ""})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        self.assertTrue(LLMSkill.objects.filter(team=self.team, name="web-analytics-triage").exists())

    def test_install_rejects_unsafe_bundled_file_path(self, _mock_flag) -> None:
        skill = _create_community_skill(slug="web-analytics-triage")
        # A traversal path in the catalog must not be persisted into the team skill.
        CommunitySkillFile.objects.create(skill=skill, path="../escape.md", content="x")

        response = self.client.post(self._url("web-analytics-triage/install/"), {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(LLMSkill.objects.filter(team=self.team).exists())
        skill.refresh_from_db()
        self.assertEqual(skill.install_count, 0)

    @parameterized.expand(
        [
            # signals-scout-* auto-registers and runs with privileged scout scopes.
            ("scout_namespace", "signals-scout-evil"),
            # A canonical ReviewHog name auto-enables and runs in the installing user's PR reviews.
            ("reviewhog_canonical", "review-hog-perspective-logic-correctness"),
        ]
    )
    def test_install_rejects_reserved_auto_running_names(self, _mock_flag, _name, reserved_name) -> None:
        _create_community_skill(slug="web-analytics-triage")
        # These namespaces auto-run community-controlled instructions on install, so they're refused.
        response = self.client.post(self._url("web-analytics-triage/install/"), {"new_name": reserved_name})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(LLMSkill.objects.filter(team=self.team, name=reserved_name).exists())

    def test_install_strips_internal_reviewhog_provenance(self, _mock_flag) -> None:
        skill = _create_community_skill(slug="web-analytics-triage")
        # ReviewHog prunes rows by seeded_by, so these keys must not be copied through on install —
        # otherwise a catalog entry could make a user's freshly installed skill disappear.
        CommunitySkill.objects.filter(pk=skill.pk).update(
            metadata={"seeded_by": "review_hog", "canonical_hash": "deadbeef", "keep": "me"}
        )
        response = self.client.post(self._url("web-analytics-triage/install/"), {})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)

        installed = LLMSkill.objects.get(team=self.team, name="web-analytics-triage")
        self.assertNotIn("seeded_by", installed.metadata)
        self.assertNotIn("canonical_hash", installed.metadata)
        self.assertEqual(installed.metadata["keep"], "me")

    def test_install_rejects_blank_description(self, _mock_flag) -> None:
        skill = _create_community_skill(slug="web-analytics-triage")
        # A blank description installs a skill that later fails export validation.
        CommunitySkill.objects.filter(pk=skill.pk).update(description="   ")
        response = self.client.post(self._url("web-analytics-triage/install/"), {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(LLMSkill.objects.filter(team=self.team).exists())

    def test_install_unknown_slug_returns_404(self, _mock_flag) -> None:
        response = self.client.post(self._url("does-not-exist/install/"), {})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_retrieve_surfaces_template_variables(self, _mock_flag) -> None:
        _create_template_skill(slug="feed-scout")
        response = self.client.get(self._url("feed-scout/"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        variables = response.json()["template_variables"]
        self.assertEqual([v["name"] for v in variables], ["feed_table", "default_branch"])
        self.assertEqual(
            variables[0], {"name": "feed_table", "prompt": "Warehouse table", "is_required": True, "default": ""}
        )
        self.assertFalse(variables[1]["is_required"])  # has a default

    def test_install_template_renders_variables(self, _mock_flag) -> None:
        skill = _create_template_skill(slug="feed-scout")
        CommunitySkillFile.objects.create(
            skill=skill, path="references/notes.md", content="Query {{ feed_table }} carefully."
        )

        response = self.client.post(
            self._url("feed-scout/install/"),
            {"variables": {"feed_table": "slack_abc", "default_branch": "develop"}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)

        installed = LLMSkill.objects.get(team=self.team, name="feed-scout")
        self.assertEqual(installed.body, "# Scout\nWatch table slack_abc on develop.")
        self.assertEqual(installed.files.get(path="references/notes.md").content, "Query slack_abc carefully.")
        # The instantiated skill is concrete, not a template.
        self.assertNotIn("variables", installed.metadata)
        self.assertEqual(installed.metadata["instantiated_from"], "feed-scout@sha123")
        self.assertEqual(
            installed.metadata["variable_bindings"], {"feed_table": "slack_abc", "default_branch": "develop"}
        )

    def test_install_template_uses_default_when_omitted(self, _mock_flag) -> None:
        _create_template_skill(slug="feed-scout")
        response = self.client.post(
            self._url("feed-scout/install/"),
            {"variables": {"feed_table": "slack_abc"}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        installed = LLMSkill.objects.get(team=self.team, name="feed-scout")
        self.assertEqual(installed.body, "# Scout\nWatch table slack_abc on main.")

    def test_install_template_missing_required_returns_400(self, _mock_flag) -> None:
        _create_template_skill(slug="feed-scout")
        response = self.client.post(self._url("feed-scout/install/"), {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["attr"], "variables")
        self.assertFalse(LLMSkill.objects.filter(team=self.team, name="feed-scout").exists())

    def test_install_template_oversized_variable_returns_400(self, _mock_flag) -> None:
        _create_template_skill(slug="feed-scout")
        response = self.client.post(
            self._url("feed-scout/install/"),
            {"variables": {"feed_table": "x" * (MAX_TEMPLATE_VARIABLE_BYTES + 1)}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(LLMSkill.objects.filter(team=self.team, name="feed-scout").exists())

    def test_install_template_undeclared_placeholder_is_logged(self, _mock_flag) -> None:
        skill = _create_template_skill(slug="feed-scout")
        skill.body = "Watch {{ feed_table }} and {{ undeclared }}."
        skill.save(update_fields=["body"])

        with patch("products.skills.backend.api.community_skills.logger.exception") as mock_exception:
            response = self.client.post(
                self._url("feed-scout/install/"),
                {"variables": {"feed_table": "slack_abc"}},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        # The hand-built 500 bypasses DRF's exception handler, so this log line is the only signal
        # that a catalog entry is broken.
        mock_exception.assert_called_once()
        self.assertFalse(LLMSkill.objects.filter(team=self.team, name="feed-scout").exists())

    def test_vote_toggles_on_and_off(self, _mock_flag) -> None:
        _create_community_skill(slug="web-analytics-triage")

        first = self.client.post(self._url("web-analytics-triage/vote/"))
        self.assertEqual(first.json(), {"vote_count": 1, "has_voted": True})

        second = self.client.post(self._url("web-analytics-triage/vote/"))
        self.assertEqual(second.json(), {"vote_count": 0, "has_voted": False})
        self.assertFalse(CommunitySkillVote.objects.exists())


@pytest.mark.ee
@patch(
    "products.skills.backend.api.community_skills.posthoganalytics.feature_enabled",
    return_value=True,
)
class TestCommunitySkillWriteAccess(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
        ]
        self.organization.save()

        viewer = User.objects.create_and_join(self.organization, "skills-viewer@posthog.com", "testtest")
        AccessControl.objects.create(
            team=self.team,
            resource="llm_skill",
            resource_id=None,
            access_level="viewer",
            organization_member=OrganizationMembership.objects.get(user=viewer, organization=self.organization),
        )
        self.client.force_login(viewer)

    @parameterized.expand([("install",), ("vote",)])
    def test_viewer_cannot_write(self, _mock_flag, action: str) -> None:
        _create_community_skill(slug="web-analytics-triage")

        response = self.client.post(f"/api/projects/{self.team.id}/community_skills/web-analytics-triage/{action}/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.content)
        self.assertFalse(LLMSkill.objects.filter(team=self.team).exists())
        self.assertFalse(CommunitySkillVote.objects.exists())


class TestCommunitySkillFeatureFlagGate(APIBaseTest):
    @parameterized.expand(
        [
            ("only_community_flag_enabled", {"llm-analytics-community-skills"}, status.HTTP_200_OK),
            ("no_flags_enabled", set(), status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_gate_depends_only_on_the_community_flag(
        self, _name: str, enabled_flags: set[str], expected_status: int
    ) -> None:
        _create_community_skill(slug="web-analytics-triage")

        with patch(
            "products.skills.backend.api.community_skills.posthoganalytics.feature_enabled",
            side_effect=lambda flag, *args, **kwargs: flag in enabled_flags,
        ):
            response = self.client.get(f"/api/projects/{self.team.id}/community_skills/")

        self.assertEqual(response.status_code, expected_status, response.content)


class TestSkillTemplateRendering(APIBaseTest):
    @parameterized.expand(
        [
            ("no metadata", None, False),
            ("empty", {}, False),
            ("non-list variables", {"variables": "nope"}, False),
            ("empty list", {"variables": []}, False),
            ("declared", {"variables": [{"name": "repo"}]}, True),
        ]
    )
    def test_is_template(self, _name, metadata, expected) -> None:
        self.assertEqual(is_template(metadata), expected)

    def test_parse_skips_malformed_and_dedupes(self) -> None:
        variables = parse_template_variables(
            {
                "variables": [
                    {"name": "repo"},
                    {"no_name": 1},
                    "bad",
                    {"name": "repo"},
                    {"name": "branch", "default": "main"},
                ]
            }
        )
        self.assertEqual([v.name for v in variables], ["repo", "branch"])
        # Bare declaration defaults to required; a default makes it optional.
        self.assertTrue(variables[0].required)
        self.assertFalse(variables[1].required)

    def test_render_substitutes_and_records_bindings(self) -> None:
        rendered = render_template_skill(
            variables=parse_template_variables({"variables": [{"name": "repo", "required": True}]}),
            body="watch {{ repo }}",
            files=[{"path": "a.md", "content": "ref {{ repo }}", "content_type": "text/plain"}],
            supplied={"repo": "posthog/posthog"},
        )
        self.assertEqual(rendered.body, "watch posthog/posthog")
        self.assertEqual(rendered.files[0]["content"], "ref posthog/posthog")
        self.assertEqual(rendered.bindings, {"repo": "posthog/posthog"})

    def test_render_missing_required_raises(self) -> None:
        with self.assertRaises(MissingTemplateVariableError):
            render_template_skill(
                variables=parse_template_variables({"variables": [{"name": "repo", "required": True}]}),
                body="watch {{ repo }}",
                files=[],
                supplied={},
            )

    def test_render_unknown_placeholder_raises(self) -> None:
        with self.assertRaises(UnknownTemplatePlaceholderError):
            render_template_skill(
                variables=parse_template_variables({"variables": [{"name": "repo", "required": True}]}),
                body="watch {{ repo }} and {{ undeclared }}",
                files=[],
                supplied={"repo": "x"},
            )

    def test_render_rejects_unrenderable_variable_name(self) -> None:
        # A declared name the placeholder regex can't match (hyphen) must fail, not install dangling.
        with self.assertRaises(UnknownTemplatePlaceholderError):
            render_template_skill(
                variables=parse_template_variables({"variables": [{"name": "repo-name", "required": True}]}),
                body="watch {{ repo-name }}",
                files=[],
                supplied={"repo-name": "x"},
            )

    def test_render_explicit_blank_overrides_default(self) -> None:
        rendered = render_template_skill(
            variables=parse_template_variables({"variables": [{"name": "suffix", "default": "!"}]}),
            body="hi{{ suffix }}",
            files=[],
            supplied={"suffix": ""},
        )
        self.assertEqual(rendered.body, "hi")

    def test_render_explicit_blank_required_raises(self) -> None:
        with self.assertRaises(MissingTemplateVariableError):
            render_template_skill(
                variables=parse_template_variables({"variables": [{"name": "repo", "required": True}]}),
                body="{{ repo }}",
                files=[],
                supplied={"repo": ""},
            )

    def test_render_unknown_supplied_key_raises(self) -> None:
        with self.assertRaises(UnknownSuppliedVariableError):
            render_template_skill(
                variables=parse_template_variables({"variables": [{"name": "feed_table", "required": True}]}),
                body="{{ feed_table }}",
                files=[],
                supplied={"feed_table": "x", "feedtable": "typo"},
            )

    def test_render_allows_braces_inside_supplied_value(self) -> None:
        # Validation is on the source template, so a value containing literal {{ }} is not re-parsed.
        rendered = render_template_skill(
            variables=parse_template_variables({"variables": [{"name": "snippet", "required": True}]}),
            body="config: {{ snippet }}",
            files=[],
            supplied={"snippet": "{{ not_a_var }}"},
        )
        self.assertEqual(rendered.body, "config: {{ not_a_var }}")

    def test_render_oversized_output_raises(self) -> None:
        # A value well inside the per-variable cap still amplifies past the body limit when the
        # template repeats its placeholder, so the size check can't assume a small input.
        with self.assertRaises(TemplateRenderTooLargeError):
            render_template_skill(
                variables=parse_template_variables({"variables": [{"name": "v", "required": True}]}),
                body="{{ v }}" * 200,
                files=[],
                supplied={"v": "x" * 9_000},
            )

    @parameterized.expand(
        [
            ("one oversized value", 1, MAX_TEMPLATE_VARIABLE_BYTES + 1),
            (
                "values oversized in total",
                MAX_TEMPLATE_BINDINGS_BYTES // MAX_TEMPLATE_VARIABLE_BYTES + 1,
                MAX_TEMPLATE_VARIABLE_BYTES,
            ),
        ]
    )
    def test_render_rejects_oversized_bindings(self, _name, count, size) -> None:
        names = [f"v{i}" for i in range(count)]
        with self.assertRaises(TemplateVariableTooLargeError):
            render_template_skill(
                variables=parse_template_variables({"variables": [{"name": n, "required": True} for n in names]}),
                # Unrendered on purpose: bindings are persisted to the installed skill's metadata
                # whether or not they appear in the body, so render-size checks don't bound them.
                body="no placeholders here",
                files=[],
                supplied=dict.fromkeys(names, "x" * size),
            )

    def test_render_rejects_oversized_total_across_files(self) -> None:
        # Each file renders to ~700 KB, under the 1 MB per-file cap, but 200 of them are 140 MB.
        # A per-file limit bounds nothing in aggregate, so the whole-skill cap has to exist.
        with self.assertRaises(TemplateRenderTooLargeError) as ctx:
            render_template_skill(
                variables=parse_template_variables({"variables": [{"name": "v", "required": True}]}),
                body="small",
                files=[
                    {"path": f"references/{i}.md", "content": "{{ v }}" * 100, "content_type": "text/plain"}
                    for i in range(200)
                ],
                supplied={"v": "x" * 7_000},
            )
        self.assertIn(str(MAX_RENDERED_SKILL_BYTES), str(ctx.exception))

    def test_render_scans_unmatched_delimiters_in_one_pass(self) -> None:
        # Unclosed `{{` stay literal. A `{{.*?}}` regex rescans the rest of the input for each of
        # them, so this body took tens of seconds to validate before the scan became single-pass.
        body = "{{" * 32_000
        started = time.monotonic()
        rendered = render_template_skill(variables=[], body=body, files=[], supplied=None)
        self.assertEqual(rendered.body, body)
        self.assertLess(time.monotonic() - started, 5)
