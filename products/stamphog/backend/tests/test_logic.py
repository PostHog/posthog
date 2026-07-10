from django.test import SimpleTestCase

from parameterized import parameterized

from products.stamphog.backend.logic.gates import GateInput, run_gates
from products.stamphog.backend.logic.policy import Policy, PolicyError, load_policy
from products.stamphog.backend.logic.reviewer import parse_reviewer_output

MINIMAL_POLICY_YAML = """
deny:
  secrets:
    match:
      paths:
        - "secrets?"
    exempt_path_prefixes:
      - "docs/"
allow:
  path_patterns:
    - "changelog"
  extensions_only:
    - .md
size_gate:
  max_lines: 500
  max_files: 20
tiers:
  t1_subclasses:
    T1a-tiny:
      max_lines: 20
      max_files: 2
      breadth: single-area
    T1b-small:
      max_lines: 100
      max_files: 5
      breadth: not-cross-cutting
"""


def _make_file(path: str, additions: int = 1, deletions: int = 0) -> dict:
    return {"filename": path, "additions": additions, "deletions": deletions}


class LoadPolicyTests(SimpleTestCase):
    def test_parses_minimal_valid_policy(self) -> None:
        policy = load_policy({".stamphog/policy.yml": MINIMAL_POLICY_YAML}, {})

        assert policy.size_gate.max_lines == 500
        assert "secrets" in policy.deny

    def test_missing_policy_file_fails_closed(self) -> None:
        with self.assertRaises(PolicyError):
            load_policy({}, {})

    @parameterized.expand(
        [
            (
                "deny_missing_match_patterns",
                """
deny:
  secrets: {}
allow:
  path_patterns: ["changelog"]
  extensions_only: [".md"]
size_gate: {max_lines: 500, max_files: 20}
tiers:
  t1_subclasses:
    T1a-tiny: {max_lines: 20, max_files: 2, breadth: single-area}
""",
            ),
            (
                "size_gate_not_a_mapping",
                """
deny:
  secrets:
    match:
      paths: ["secrets?"]
allow:
  path_patterns: ["changelog"]
  extensions_only: [".md"]
size_gate: not-a-mapping
tiers:
  t1_subclasses:
    T1a-tiny: {max_lines: 20, max_files: 2, breadth: single-area}
""",
            ),
            (
                "tiers_empty_subclasses",
                """
deny:
  secrets:
    match:
      paths: ["secrets?"]
allow:
  path_patterns: ["changelog"]
  extensions_only: [".md"]
size_gate: {max_lines: 500, max_files: 20}
tiers:
  t1_subclasses: {}
""",
            ),
        ]
    )
    def test_malformed_section_fails_closed(self, _name: str, broken_yaml: str) -> None:
        with self.assertRaises(PolicyError):
            load_policy({".stamphog/policy.yml": broken_yaml}, {})

    def test_team_overrides_bump_size_gate_ceiling(self) -> None:
        # StamphogRepoConfig.policy_overrides deep-merges onto the parsed YAML,
        # so a team can raise its own ceiling without editing policy.yml.
        policy = load_policy(
            {".stamphog/policy.yml": MINIMAL_POLICY_YAML},
            {"size_gate": {"max_lines": 900}},
        )

        assert policy.size_gate.max_lines == 900
        assert policy.size_gate.max_files == 20

    def test_folder_override_ignored_without_a_declared_ceiling(self) -> None:
        approvals = "---\nstamphog:\n  size_gate:\n    max_files: 15\n---\n"
        policy = load_policy(
            {
                ".stamphog/policy.yml": MINIMAL_POLICY_YAML,
                "products/foo/AGENT_APPROVALS.md": approvals,
            },
            {},
        )

        # No declared overrides ceiling in the base policy means folder grants
        # contribute nothing rather than raising - confirms the fail-closed default.
        assert policy.folder_max_files == {}

    def test_folder_override_ignored_when_keys_dont_match_allow_list(self) -> None:
        policy_with_ceiling = MINIMAL_POLICY_YAML + "overrides:\n  size_gate.max_files:\n    ceiling: 50\n"
        approvals_with_extra_key = "---\nstamphog:\n  size_gate:\n    max_files: 15\n  other: true\n---\n"
        policy = load_policy(
            {
                ".stamphog/policy.yml": policy_with_ceiling,
                "products/foo/AGENT_APPROVALS.md": approvals_with_extra_key,
            },
            {},
        )

        assert policy.folder_max_files == {}

    def test_folder_override_respects_declared_ceiling(self) -> None:
        policy_with_ceiling = MINIMAL_POLICY_YAML + "overrides:\n  size_gate.max_files:\n    ceiling: 10\n"
        approvals_over_ceiling = "---\nstamphog:\n  size_gate:\n    max_files: 999\n---\n"
        policy = load_policy(
            {
                ".stamphog/policy.yml": policy_with_ceiling,
                "products/foo/AGENT_APPROVALS.md": approvals_over_ceiling,
            },
            {},
        )

        # A folder can't grant itself more files than the policy's own ceiling allows.
        assert policy.folder_max_files == {}


def _policy() -> Policy:
    return load_policy({".stamphog/policy.yml": MINIMAL_POLICY_YAML}, {})


class RunGatesTests(SimpleTestCase):
    def test_deny_listed_path_hard_fails_regardless_of_size(self) -> None:
        gate_input = GateInput(
            pr={},
            files=[_make_file("secrets/token.py")],
            policy=_policy(),
            is_draft=False,
        )

        result = run_gates(gate_input)

        assert result.passed is False
        assert result.tier == "T2-never"
        assert "secrets" in result.reason

    def test_deny_listed_path_exempted_by_prefix_passes(self) -> None:
        gate_input = GateInput(
            pr={},
            files=[_make_file("docs/secrets.md")],
            policy=_policy(),
            is_draft=False,
        )

        result = run_gates(gate_input)

        assert result.passed is True

    @parameterized.expand(
        [
            ("draft", {"is_draft": True}, "draft"),
            ("merge_conflicts", {"is_draft": False, "has_merge_conflicts": True}, "merge conflicts"),
            ("changes_requested", {"is_draft": False, "has_changes_requested_review": True}, "changes-requested"),
        ]
    )
    def test_prerequisite_gates_short_circuit_before_deny_list(
        self, _name: str, extra_kwargs: dict, expected_reason_fragment: str
    ) -> None:
        gate_input = GateInput(
            pr={},
            files=[_make_file("safe.py")],
            policy=_policy(),
            **extra_kwargs,
        )

        result = run_gates(gate_input)

        assert result.passed is False
        assert result.tier == "T2-never"
        assert expected_reason_fragment in result.reason

    def test_size_ceiling_exceeded_fails_but_still_reports_tier(self) -> None:
        gate_input = GateInput(
            pr={},
            files=[_make_file("app/big.py", additions=600)],
            policy=_policy(),
            is_draft=False,
        )

        result = run_gates(gate_input)

        assert result.passed is False
        assert "changed lines" in result.reason
        # Tier classification still runs so the caller has context on a failed gate.
        assert result.tier != ""

    @parameterized.expand(
        [
            ("allow_listed_only", ["CHANGELOG.md"], "T0-deterministic"),
            ("test_only", ["products/foo/tests/test_bar.py"], "T0-deterministic"),
            ("tiny_single_area", ["app/small.py"], "T1a-tiny"),
        ]
    )
    def test_tier_classification_for_low_risk_shapes(self, _name: str, paths: list[str], expected_tier: str) -> None:
        gate_input = GateInput(
            pr={},
            files=[_make_file(p, additions=5) for p in paths],
            policy=_policy(),
            is_draft=False,
        )

        result = run_gates(gate_input)

        assert result.passed is True
        assert result.tier == expected_tier

    def test_cross_cutting_change_past_subclass_ceilings_falls_back_to_complex(self) -> None:
        gate_input = GateInput(
            pr={},
            files=[
                _make_file("app_a/file.py", additions=50),
                _make_file("app_b/file.py", additions=50),
                _make_file("app_c/file.py", additions=50),
            ],
            policy=_policy(),
            is_draft=False,
        )

        result = run_gates(gate_input)

        assert result.passed is True
        assert result.tier == "T1d-complex"

    def test_folder_override_widens_file_ceiling_only_for_its_own_scope(self) -> None:
        policy_with_ceiling = MINIMAL_POLICY_YAML + "overrides:\n  size_gate.max_files:\n    ceiling: 50\n"
        approvals = "---\nstamphog:\n  size_gate:\n    max_files: 30\n---\n"
        policy = load_policy(
            {
                ".stamphog/policy.yml": policy_with_ceiling,
                "products/foo/AGENT_APPROVALS.md": approvals,
            },
            {},
        )
        # 22 files under products/foo would fail the global 20-file ceiling, but
        # the folder's delegated 30-file grant covers files scoped under it.
        foo_files = [_make_file(f"products/foo/file_{i}.py", additions=1) for i in range(22)]

        gate_input = GateInput(pr={}, files=foo_files, policy=policy, is_draft=False)

        result = run_gates(gate_input)

        assert result.passed is True

    def test_ungoverned_files_still_checked_against_global_ceiling_despite_folder_grant(self) -> None:
        policy_with_ceiling = MINIMAL_POLICY_YAML + "overrides:\n  size_gate.max_files:\n    ceiling: 50\n"
        approvals = "---\nstamphog:\n  size_gate:\n    max_files: 30\n---\n"
        policy = load_policy(
            {
                ".stamphog/policy.yml": policy_with_ceiling,
                "products/foo/AGENT_APPROVALS.md": approvals,
            },
            {},
        )
        # A folder's leniency must not leak to files outside it - 22 ungoverned
        # files should still trip the base 20-file global ceiling.
        other_files = [_make_file(f"other/file_{i}.py", additions=1) for i in range(22)]

        gate_input = GateInput(pr={}, files=other_files, policy=policy, is_draft=False)

        result = run_gates(gate_input)

        assert result.passed is False
        assert "global" in result.reason


class ParseReviewerOutputTests(SimpleTestCase):
    def test_parses_clean_verdict_line(self) -> None:
        raw = '{"verdict": "APPROVE", "reasoning": "Looks fine.", "issues": []}'

        verdict = parse_reviewer_output(raw)

        assert verdict.verdict == "approved"
        assert verdict.reasoning == "Looks fine."
        assert verdict.showstoppers == []

    def test_scans_past_noisy_log_lines_for_the_last_verdict(self) -> None:
        raw = "\n".join(
            [
                "some uv log line",
                '{"not": "a verdict"}',
                '{"verdict": "REFUSE", "reasoning": "Bad idea.", "issues": ["no tests"]}',
                "trailing sdk teardown noise",
            ]
        )

        verdict = parse_reviewer_output(raw)

        assert verdict.verdict == "refused"
        assert verdict.showstoppers == ["no tests"]

    def test_garbage_output_falls_back_to_escalate(self) -> None:
        verdict = parse_reviewer_output("not json at all\nstill not json")

        assert verdict.verdict == "escalate"
        assert verdict.showstoppers

    def test_unrecognized_verdict_string_escalates_with_note(self) -> None:
        raw = '{"verdict": "MAYBE", "reasoning": "Unsure.", "issues": []}'

        verdict = parse_reviewer_output(raw)

        assert verdict.verdict == "escalate"
        assert any("MAYBE" in note for note in verdict.showstoppers)
