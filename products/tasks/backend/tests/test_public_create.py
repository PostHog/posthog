from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from products.tasks.backend.facade.run_config import REASONING_EFFORTS
from products.tasks.backend.presentation.serializers import PublicReasoningEffort, TaskRunOptionsRequestSerializer
from products.tasks.backend.public_create import (
    asks_for_run,
    create_fields_from_options,
    idempotent_request,
    options_from_request,
    public_idempotency_key,
    request_fingerprint,
)
from products.tasks.backend.task_profiles import PUBLIC_RUN_OPTIONS

OPTION_SAMPLES: dict[str, tuple[Any, dict[str, Any]]] = {
    "runtime": ("pi", {"runtime": "pi"}),
    "adapter": ("codex", {"runtime_adapter": "codex"}),
    "model": ("claude-sonnet-5", {"model": "claude-sonnet-5"}),
    "reasoning_effort": ("high", {"reasoning_effort": "high"}),
    "repositories": (
        [{"name": "posthog/posthog", "initial_branch": "main"}],
        {"repositories": ["posthog/posthog"], "branch": "main"},
    ),
    "output_schema": ({"type": "object"}, {"json_schema": {"type": "object"}}),
    "permission_mode": ("plan", {"initial_permission_mode": "plan"}),
    "auto_publish": (True, {"auto_publish": True}),
}


class TestPublicCreateOptions(SimpleTestCase):
    def test_the_endpoint_accepts_exactly_the_public_run_options(self) -> None:
        self.assertEqual(set(TaskRunOptionsRequestSerializer().fields), PUBLIC_RUN_OPTIONS)
        self.assertEqual(set(OPTION_SAMPLES), PUBLIC_RUN_OPTIONS)

    def test_the_endpoint_accepts_every_reasoning_effort_tier(self) -> None:
        self.assertEqual(PublicReasoningEffort.values, list(REASONING_EFFORTS))

    @parameterized.expand([(name, value, expected) for name, (value, expected) in OPTION_SAMPLES.items()])
    def test_each_option_reaches_the_create_fields(self, name: str, value: Any, expected: dict[str, Any]) -> None:
        options = options_from_request({name: value})

        self.assertEqual(create_fields_from_options(options), expected)

    @parameterized.expand(
        [
            ("without_a_branch", [{"name": "posthog/posthog"}], {"repositories": ["posthog/posthog"]}),
            (
                "branch_of_the_first_repository",
                [
                    {"name": "posthog/posthog", "initial_branch": "main"},
                    {"name": "posthog/code", "initial_branch": "dev"},
                ],
                {"repositories": ["posthog/posthog", "posthog/code"], "branch": "main"},
            ),
            (
                "branch_of_a_later_repository_only",
                [{"name": "posthog/posthog"}, {"name": "posthog/code", "initial_branch": "dev"}],
                {"repositories": ["posthog/posthog", "posthog/code"]},
            ),
        ]
    )
    def test_repositories_start_the_first_run_from_the_first_branch(
        self, _name: str, repositories: list[dict[str, str]], expected: dict[str, Any]
    ) -> None:
        options = options_from_request({"repositories": repositories})

        self.assertEqual(create_fields_from_options(options), expected)

    @parameterized.expand(
        [
            ("omitted", {}, {}),
            ("empty", {"repositories": []}, {"repositories": []}),
            ("empty_beside_other_options", {"repositories": [], "model": "m"}, {"repositories": [], "model": "m"}),
        ]
    )
    def test_an_empty_repositories_option_stays_distinct_from_an_omitted_one(
        self, _name: str, data: dict[str, Any], expected: dict[str, Any]
    ) -> None:
        fields = create_fields_from_options(options_from_request(data), repositories_given="repositories" in data)

        self.assertEqual(fields, expected)

    def test_options_left_unset_create_no_fields(self) -> None:
        self.assertEqual(create_fields_from_options(options_from_request({})), {})


class TestPublicCreateOptionsRequest(SimpleTestCase):
    @parameterized.expand(
        [
            ("distinct_names", [{"name": "posthog/posthog"}, {"name": "posthog/code"}], True),
            ("same_name", [{"name": "posthog/posthog"}, {"name": "posthog/posthog"}], False),
            ("names_that_differ_in_case", [{"name": "PostHog/PostHog"}, {"name": "posthog/posthog"}], False),
            (
                "same_name_with_other_branches",
                [{"name": "posthog/posthog", "initial_branch": "main"}, {"name": "posthog/posthog"}],
                False,
            ),
            ("duplicate_after_a_distinct_name", [{"name": "a/b"}, {"name": "c/d"}, {"name": "A/B"}], False),
        ]
    )
    def test_repositories_must_be_unique(self, _name: str, repositories: list[dict[str, str]], valid: bool) -> None:
        serializer = TaskRunOptionsRequestSerializer(data={"repositories": repositories})

        self.assertEqual(serializer.is_valid(), valid, serializer.errors)
        if not valid:
            self.assertEqual(
                [str(error) for error in serializer.errors["repositories"]], ["Repositories must be unique"]
            )


class TestPublicCreateIdempotency(SimpleTestCase):
    @parameterized.expand(
        [
            ("same_body", {"title": "a", "options": {"model": "m"}}, {"title": "a", "options": {"model": "m"}}, True),
            (
                "key_order",
                {"title": "a", "description": "b"},
                {"description": "b", "title": "a"},
                True,
            ),
            ("key_ignored", {"title": "a", "idempotency_key": "one"}, {"title": "a", "idempotency_key": "two"}, True),
            ("top_level_field", {"title": "a"}, {"title": "b"}, False),
            ("nested_field", {"options": {"model": "m"}}, {"options": {"model": "n"}}, False),
            ("extra_field", {"title": "a"}, {"title": "a", "description": "b"}, False),
        ]
    )
    def test_request_fingerprint_follows_the_body(
        self, _name: str, first: dict[str, Any], second: dict[str, Any], same: bool
    ) -> None:
        self.assertEqual(request_fingerprint(first) == request_fingerprint(second), same)

    @parameterized.expand(
        [
            ("same_user_same_key", 1, "k", 1, "k", True),
            ("other_user", 1, "k", 2, "k", False),
            ("other_key", 1, "k", 1, "j", False),
        ]
    )
    def test_public_keys_are_per_user(
        self, _name: str, first_user: int, first_key: str, second_user: int, second_key: str, same: bool
    ) -> None:
        self.assertEqual(
            public_idempotency_key(first_user, first_key) == public_idempotency_key(second_user, second_key), same
        )

    @parameterized.expand(
        [
            ("complete", {"profile": "p", "idempotency_key": "k"}, True),
            ("padded_key", {"profile": "p", "idempotency_key": " k "}, True),
            ("without_a_profile", {"idempotency_key": "k"}, False),
            ("without_a_key", {"profile": "p"}, False),
            ("blank_key", {"profile": "p", "idempotency_key": "  "}, False),
            ("key_that_is_not_text", {"profile": "p", "idempotency_key": 5}, False),
            ("body_that_is_not_an_object", ["profile", "idempotency_key"], False),
        ]
    )
    def test_only_a_profiled_request_with_a_text_key_looks_up_a_replay(
        self, _name: str, data: Any, looks: bool
    ) -> None:
        replay_request = idempotent_request(1, data)

        self.assertEqual(replay_request is not None, looks)
        if replay_request is not None:
            self.assertEqual(replay_request.key, public_idempotency_key(1, "k"))
            self.assertEqual(replay_request.fingerprint, request_fingerprint(data))

    @parameterized.expand(
        [
            ("true", {"start_run": True}, True),
            ("text_true", {"start_run": "true"}, True),
            ("number_one", {"start_run": 1}, True),
            ("false", {"start_run": False}, False),
            ("text_false", {"start_run": "false"}, False),
            ("omitted", {}, False),
            ("list", {"start_run": [True]}, False),
        ]
    )
    def test_a_request_asks_for_a_run_the_way_the_serializer_reads_start_run(
        self, _name: str, data: dict[str, Any], asks: bool
    ) -> None:
        self.assertEqual(asks_for_run(data), asks)
