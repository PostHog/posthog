import json

import pytest

from parameterized import parameterized

from products.review_hog.backend.reviewer.models.issues_review import IssuePriority, salvage_issues_review


def _issue_dict(**overrides: object) -> dict[str, object]:
    issue: dict[str, object] = {
        "id": "1-2-1",
        "title": "Something",
        "file": "src/app.py",
        "lines": [{"start": 10, "end": 20}],
        "issue": "A problem",
        "suggestion": "A fix",
        "priority": "must_fix",
    }
    issue.update(overrides)
    return issue


class TestSalvageIssuesReview:
    @parameterized.expand(
        [
            # The reported symptom: the model emits a well-formed issue but drops `priority`.
            ("missing", {"priority": None}),
            ("absent_key", "drop"),
            # A misspelled / out-of-enum value is the same class of slip and must not hard-fail.
            ("invalid_value", {"priority": "critical"}),
        ]
    )
    def test_fills_priority_when_missing_or_invalid(self, _name: str, mutation: object) -> None:
        issue = _issue_dict()
        if mutation == "drop":
            del issue["priority"]
        else:
            assert isinstance(mutation, dict)
            issue.update(mutation)

        review = salvage_issues_review(json.dumps({"issues": [issue]}))

        assert len(review.issues) == 1
        # A dropped/invalid priority is defaulted rather than discarding the whole chunk...
        assert review.issues[0].priority == IssuePriority.SHOULD_FIX
        # ...and the rest of the well-formed issue survives intact.
        assert review.issues[0].id == "1-2-1"
        assert review.issues[0].file == "src/app.py"

    def test_preserves_valid_priorities(self) -> None:
        # Guard against over-eager replacement: a valid priority must never be rewritten.
        review = salvage_issues_review(
            json.dumps({"issues": [_issue_dict(priority="must_fix"), _issue_dict(id="1-2-2", priority="consider")]})
        )

        assert [i.priority for i in review.issues] == [IssuePriority.MUST_FIX, IssuePriority.CONSIDER]

    def test_raises_on_unrecoverable_text(self) -> None:
        # Salvage only rescues the dropped-field case — genuinely non-JSON text still fails the run,
        # so a broken agent turn keeps surfacing as an error instead of being silently swallowed.
        with pytest.raises(Exception):
            salvage_issues_review("I could not complete the review.")
