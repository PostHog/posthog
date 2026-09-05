"""Unit tests for the desktop preview profile.

Pure logic only — no network, no live box, no SDK needed. Guards the identity
contract with the desktop client (scheme/redirect URI/app id), idempotent
script shapes, the metadata document, and the readiness parser.

The identity constants here must stay in sync with
products/desktop/packages/shared/src/desktop-preview.ts: the installer derives
its redirect URI from that file, and a drift would make every OAuth callback
land on a scheme the server never registered.
"""

from __future__ import annotations

import json
import pathlib
import importlib.util

import unittest

# Import the module by path: the package __init__ pulls the hogland SDK (an
# optional per-run dependency), and this module is pure logic that must be
# testable without it.
_spec = importlib.util.spec_from_file_location(
    "desktop_profile",
    pathlib.Path(__file__).resolve().parent.parent / "hogbox_preview" / "desktop_profile.py",
)
desktop_profile = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(desktop_profile)

DESKTOP_TESTER_EMAILS = desktop_profile.DESKTOP_TESTER_EMAILS
build_deployment_metadata_document = desktop_profile.build_deployment_metadata_document
build_desktop_readiness_script = desktop_profile.build_desktop_readiness_script
build_oauth_seed_script = desktop_profile.build_oauth_seed_script
desktop_app_id = desktop_profile.desktop_app_id
desktop_redirect_uri = desktop_profile.desktop_redirect_uri
desktop_scheme = desktop_profile.desktop_scheme
parse_readiness_output = desktop_profile.parse_readiness_output


class IdentityContract(unittest.TestCase):
    """The derived identity must match desktopPreviewIdentity in the app."""

    def test_scheme_matches_desktop_identity(self):
        self.assertEqual(desktop_scheme(123), "posthog-code-preview-pr-123")
        self.assertEqual(desktop_scheme(1), "posthog-code-preview-pr-1")

    def test_redirect_uri_is_scheme_callback(self):
        self.assertEqual(desktop_redirect_uri(123), "posthog-code-preview-pr-123://callback")

    def test_app_id_matches_desktop_identity(self):
        self.assertEqual(desktop_app_id(123), "com.posthog.array.preview.pr123")

    def test_identity_varies_per_pr(self):
        self.assertNotEqual(desktop_scheme(123), desktop_scheme(124))
        self.assertNotEqual(desktop_app_id(123), desktop_app_id(124))
        self.assertNotEqual(desktop_redirect_uri(123), desktop_redirect_uri(124))


class OAuthSeedScript(unittest.TestCase):
    def test_registers_the_preview_redirect_uri(self):
        script = build_oauth_seed_script(pr_number=123, organization_id=None)
        self.assertIn("posthog-code-preview-pr-123://callback", script)

    def test_uses_the_public_array_client_id(self):
        # The client id is a public identifier shared with the development
        # build (packages/shared/src/oauth.ts POSTHOG_DEV_CLIENT_ID); the
        # desktop client sends it as-is.
        script = build_oauth_seed_script(pr_number=123, organization_id=None)
        self.assertIn("DC5uRLVbGI02YQ82grxgnK6Qn12SXWpCqdPb60oZ", script)

    def test_is_idempotent_shape_update_or_create(self):
        script = build_oauth_seed_script(pr_number=123, organization_id=None)
        self.assertIn("update_or_create", script)
        self.assertIn("get_or_create", script)

    def test_seeds_two_synthetic_testers(self):
        script = build_oauth_seed_script(pr_number=123, organization_id=None)
        for email in DESKTOP_TESTER_EMAILS:
            self.assertIn(email, script)
        self.assertIn("example.com", script)

    def test_grants_the_privileged_gateway_scope(self):
        # The desktop's explicit scope list includes llm_gateway:read; an app
        # seeded without it fails /authorize with invalid_scope.
        script = build_oauth_seed_script(pr_number=123, organization_id=None)
        self.assertIn("llm_gateway:read", script)

    def test_carries_no_secret_material(self):
        # Client ids and PKCE are public; a leaked secret here would land in a
        # public repo and a public PR comment.
        script = build_oauth_seed_script(pr_number=123, organization_id=None)
        self.assertNotIn("client_secret", script.replace("client_type", ""))

    def test_pins_the_organization_when_supplied(self):
        script = build_oauth_seed_script(pr_number=123, organization_id="0197c0ffee")
        self.assertIn("0197c0ffee", script)


class DeploymentMetadata(unittest.TestCase):
    def test_document_is_json_with_the_expected_identity(self):
        doc = build_deployment_metadata_document(
            pr_number=123,
            commit_sha="1" * 40,
            deployment_generation=4,
        )
        parsed = json.loads(doc)
        self.assertEqual(parsed["prNumber"], 123)
        self.assertEqual(parsed["commitSha"], "1" * 40)
        self.assertEqual(parsed["deploymentGeneration"], 4)
        self.assertEqual(parsed["schemaVersion"], 1)

    def test_document_serves_the_exact_sha(self):
        # The installed client compares commitSha against its manifest; a
        # truncated SHA would let an old installer pass against a new backend.
        sha = "abcdef" * 6 + "1234"
        doc = build_deployment_metadata_document(pr_number=123, commit_sha=sha, deployment_generation=1)
        self.assertIn(sha, doc)


class Readiness(unittest.TestCase):
    def test_script_probes_the_expected_surfaces(self):
        script = build_desktop_readiness_script(
            pr_number=123,
            backend_origin="https://preview.example.com",
            oauth_client_id="example-client",
            commit_sha="1" * 40,
        )
        self.assertIn("/static/desktop-preview/deployment.json", script)
        self.assertIn("/api/login/", script)
        self.assertIn("/oauth/authorize", script)
        self.assertIn("/api/users/@me/", script)
        self.assertIn("posthog-code-preview-pr-123://callback", script)

    def test_parser_reads_ok_marker(self):
        self.assertEqual(parse_readiness_output("noise\nDESKTOP_READY_OK\n")["status"], "ok")

    def test_parser_extracts_the_first_failure(self):
        out = "step a\nDESKTOP_READY_FAIL metadata-wrong-sha-abc1234\nDESKTOP_READY_FAIL later\n"
        parsed = parse_readiness_output(out)
        self.assertEqual(parsed["status"], "failed")
        self.assertEqual(parsed["reason"], "metadata-wrong-sha-abc1234")

    def test_parser_fails_closed_without_a_verdict(self):
        parsed = parse_readiness_output("just noise")
        self.assertEqual(parsed["status"], "failed")
        self.assertTrue(parsed["reason"])


class ConsumerProfile(unittest.TestCase):
    def setUp(self):
        self.parse = desktop_profile.parse_consumer_profile

    def test_accepts_a_valid_profile(self):
        parsed = self.parse({"schemaVersion": 1, "capabilities": ["canvas-compiler"], "featureFlags": {"a-flag": True}})
        self.assertEqual(parsed["capabilities"], ["canvas-compiler"])

    def test_rejects_unknown_capabilities(self):
        with self.assertRaises(desktop_profile.ConsumerProfileError):
            self.parse({"schemaVersion": 1, "capabilities": ["arbitrary-shell"], "featureFlags": {}})

    def test_rejects_non_boolean_flag_values(self):
        with self.assertRaises(desktop_profile.ConsumerProfileError):
            self.parse({"schemaVersion": 1, "capabilities": [], "featureFlags": {"a-flag": "true"}})

    def test_preserves_false_overrides(self):
        parsed = self.parse({"schemaVersion": 1, "capabilities": [], "featureFlags": {"a-flag": False}})
        self.assertIs(parsed["featureFlags"]["a-flag"], False)

    def test_rejects_a_wrong_schema_version(self):
        with self.assertRaises(desktop_profile.ConsumerProfileError):
            self.parse({"schemaVersion": 2, "capabilities": [], "featureFlags": {}})

    def test_rejects_commands_or_mounts(self):
        # The shape check rejects unexpected keys implicitly: only the four
        # known keys parse. A command string is not a capability name.
        with self.assertRaises(desktop_profile.ConsumerProfileError):
            self.parse({"schemaVersion": 1, "capabilities": ["rm -rf /"], "featureFlags": {}})


if __name__ == "__main__":
    unittest.main()
