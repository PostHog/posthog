from products.tasks.backend.pr_urls import merge_pr_output, read_head_branches


def test_merge_pr_output_preserves_distinct_head_branches() -> None:
    existing = {
        "head_branches": [{"repository": "posthog/posthog", "branch": "posthog-code/first"}],
    }
    incoming = {
        "head_branches": [{"repository": "PostHog/Code", "branch": "posthog-code/second"}],
    }

    merged = merge_pr_output(existing, incoming)

    assert merged["head_branches"] == [
        {"repository": "posthog/code", "branch": "posthog-code/second"},
        {"repository": "posthog/posthog", "branch": "posthog-code/first"},
    ]


def test_read_head_branches_deduplicates_normalized_pairs() -> None:
    assert read_head_branches(
        {
            "head_branches": [
                {"repository": " PostHog/PostHog ", "branch": "posthog-code/fix"},
                {"repository": "posthog/posthog", "branch": "posthog-code/fix"},
                {"repository": "posthog/posthog", "branch": "posthog-code/other"},
                {"repository": "posthog/posthog"},
            ]
        }
    ) == [
        {"repository": "posthog/posthog", "branch": "posthog-code/fix"},
        {"repository": "posthog/posthog", "branch": "posthog-code/other"},
    ]
