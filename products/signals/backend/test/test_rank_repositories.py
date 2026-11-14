from __future__ import annotations

import sys
import json
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from unittest import TestCase

from products.signals.scripts import rank_repositories as ranking


class TestRankRepositories(TestCase):
    def payload(self, repositories: list[dict[str, object]], **values: object) -> dict[str, object]:
        return {
            "context": "checkout payments",
            "allowed_repositories": [repo["full_name"] for repo in repositories],
            "repositories": repositories,
            **values,
        }

    def test_project_evidence_takes_priority_over_metadata_and_activity(self) -> None:
        repositories: list[dict[str, object]] = [
            {"full_name": "example/activity", "human_merged_prs_30d": 1000},
            {"full_name": "example/text", "description": "checkout payments"},
            {"full_name": "example/fix", "confirmed_fix_urls": ["https://github.com/example/fix/pull/1"]},
            {"full_name": "example/direct", "project_matches": ["Checkout source map"]},
            {"full_name": "example/pinned"},
        ]
        result = ranking.rank_repositories(self.payload(repositories, pinned_repositories=["example/pinned"]))
        self.assertEqual(
            [repo["repository"] for repo in result["repositories"]],
            ["example/pinned", "example/direct", "example/fix", "example/text", "example/activity"],
        )
        self.assertEqual(
            [repo["confidence"] for repo in result["repositories"]], ["high", "high", "medium", "low", "low"]
        )
        self.assertTrue(result["repositories"][2]["needs_project_evidence"])

    def test_pin_cannot_expand_scope_and_only_pins_override_status_exclusions(self) -> None:
        for flag in ("archived", "fork", "template", "mirror"):
            with self.subTest(flag=flag):
                repositories = [
                    {"full_name": "example/pinned", flag: True},
                    {"full_name": "example/excluded", flag: True},
                    {"full_name": "other/unauthorized"},
                ]
                result = ranking.rank_repositories(
                    self.payload(
                        repositories,
                        allowed_repositories=["example/pinned", "example/excluded"],
                        pinned_repositories=["example/pinned", "other/unauthorized"],
                    )
                )
                self.assertEqual([repo["repository"] for repo in result["repositories"]], ["example/pinned"])
                self.assertEqual(
                    result["excluded"],
                    [
                        {"repository": "example/excluded", "reason": flag},
                        {"repository": "other/unauthorized", "reason": "not_allowed"},
                    ],
                )

    def test_unknown_activity_is_not_a_measured_zero_and_ties_are_stable(self) -> None:
        repositories = [
            {
                "full_name": "example/z",
                "description": "checkout",
                "human_merged_prs_30d": 0,
                "last_human_activity": "2026-01-02T12:00:00Z",
            },
            {
                "full_name": "example/c",
                "description": "checkout",
                "human_merged_prs_30d": 0,
                "last_human_activity": "2026-01-02T13:00:00+01:00",
            },
            {
                "full_name": "example/a",
                "description": "checkout",
                "human_merged_prs_30d": 0,
                "last_human_activity": "2026-01-01T12:00:00Z",
            },
            {"full_name": "example/b", "description": "checkout", "last_human_activity": "2026-01-03T12:00:00Z"},
        ]
        result = ranking.rank_repositories(self.payload(repositories))
        self.assertEqual(
            [repo["repository"] for repo in result["repositories"]],
            ["example/c", "example/z", "example/a", "example/b"],
        )
        self.assertIn("human_merged_prs_30d", result["repositories"][-1]["missing_evidence"])
        self.assertEqual(result, ranking.rank_repositories(self.payload(list(reversed(repositories)))))

    def test_homepage_and_repeated_words_do_not_establish_a_project_match(self) -> None:
        repositories = [
            {"full_name": "example/a", "description": "checkout", "homepage": "https://checkout.example.com"},
            {"full_name": "example/b", "description": "checkout " * 20},
        ]
        result = ranking.rank_repositories(self.payload(repositories))
        first, second = result["repositories"]
        self.assertEqual(first["metadata_similarity"], second["metadata_similarity"])
        self.assertEqual(first["confidence"], "low")
        self.assertTrue(first["needs_project_evidence"])

    def test_invalid_input_does_not_silently_change_scope_or_evidence(self) -> None:
        for payload in (
            {"repositories": []},
            self.payload([{"full_name": "example/repo", "archived": "false"}]),
            self.payload([{"full_name": "example/repo", "human_merged_prs_30d": True}]),
            self.payload([{"full_name": "example/repo", "project_matches": [""]}]),
            self.payload([{"full_name": "example/repo", "last_human_activity": False}]),
            self.payload([{"full_name": "example/repo", "last_human_activity": "2026-01-01T00:00:00"}]),
            self.payload([{"full_name": "Example/Repo"}, {"full_name": "example/repo"}]),
        ):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                ranking.rank_repositories(payload)

    def test_cli_reads_saved_input_and_returns_explanations(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "repositories.json"
            path.write_text(
                json.dumps(
                    self.payload(
                        [{"full_name": "example/checkout", "project_matches": ["Checkout source map"]}],
                        pinned_repositories=["example/missing"],
                        allowed_repositories=["example/checkout", "example/missing"],
                    )
                )
            )
            completed = subprocess.run(
                [sys.executable, ranking.__file__, "--input", str(path), "--limit", "1"],
                capture_output=True,
                text=True,
                check=True,
            )
        result = json.loads(completed.stdout)
        self.assertEqual(result["repositories"][0]["project_matches"], ["Checkout source map"])
        self.assertEqual(result["pinned_without_metadata"], ["example/missing"])
