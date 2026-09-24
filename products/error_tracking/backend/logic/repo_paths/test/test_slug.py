import json
from pathlib import Path

from django.test import SimpleTestCase

from products.error_tracking.backend.logic.repo_paths.slug import repo_slug

CASES_FILE = Path(__file__).resolve().parents[6] / "rust" / "cymbal" / "tests" / "static" / "repo_slug_cases.json"


class TestRepoSlug(SimpleTestCase):
    def test_matches_the_cases_cymbal_runs(self) -> None:
        cases = json.loads(CASES_FILE.read_text())
        assert cases

        for case in cases:
            with self.subTest(remote_url=case["remote_url"]):
                slug = repo_slug(case["remote_url"])
                assert (str(slug) if slug is not None else None) == case["slug"]
