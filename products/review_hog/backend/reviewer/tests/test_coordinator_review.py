from products.review_hog.backend.reviewer.tools.coordinator_review import CoordinatorUnit, coordinator_prompt
from products.review_hog.backend.reviewer.tools.prompt_helpers import PROMPT_CACHE_MARKER


def _unit(task_name: str, prompt: str) -> CoordinatorUnit:
    return CoordinatorUnit(task_name=task_name, pass_number=2000, chunk_id=1, source="s", prompt=prompt)


def test_coordinator_prompts_share_everything_before_the_cache_marker() -> None:
    # Every coordinator session reads the text before the marker from one cache entry, so a filled-in value
    # above it makes each session pay for its whole prompt again.
    small = coordinator_prompt([_unit("main_1", "short")], model="gpt-a", reasoning_effort="low")
    large = coordinator_prompt(
        [_unit("main_1", "a longer\nprompt"), _unit("contracts_security_1", "x")],
        model="gpt-b",
        reasoning_effort="high",
    )

    small_shared, small_rest = small.split(PROMPT_CACHE_MARKER)
    large_shared, large_rest = large.split(PROMPT_CACHE_MARKER)

    assert small_shared == large_shared
    assert "main_1" in small_rest
    assert "contracts_security_1" in large_rest
