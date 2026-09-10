import json

from products.review_hog.backend.reviewer.artefact_content import ReviewIssueFinding
from products.review_hog.backend.reviewer.models.github_meta import PRMetadata
from products.review_hog.backend.reviewer.models.issues_review import Issue, IssuePriority, LineRange
from products.review_hog.backend.reviewer.models.split_pr_into_chunks import Chunk, FileInfo
from products.review_hog.backend.reviewer.tools.issues_review import _covered_findings_for_chunk, build_review_prompt


def _finding(file: str, title: str) -> ReviewIssueFinding:
    return ReviewIssueFinding(
        issue_key=f"r1:{file}:1:logic:1-1-1",
        run_index=1,
        title=title,
        file=file,
        lines=[LineRange(start=1)],
        body="the problem",
        suggestion="our private fix",
        priority=IssuePriority.SHOULD_FIX,
    )


def _issue(file: str, title: str) -> Issue:
    return Issue(
        id="1-1-1",
        title=title,
        file=file,
        lines=[LineRange(start=1)],
        issue="the wave problem",
        suggestion="the wave fix",
        priority=IssuePriority.SHOULD_FIX,
    )


def _chunk(*files: str) -> Chunk:
    return Chunk(chunk_id=1, files=[FileInfo(filename=f) for f in files], chunk_type="feature")


def _pr_metadata() -> PRMetadata:
    return PRMetadata(
        number=1,
        title="t",
        state="open",
        draft=False,
        created_at="c",
        updated_at="u",
        author="octocat",
        base_branch="main",
        head_branch="feat",
        commits=1,
        additions=1,
        deletions=0,
        changed_files=1,
    )


def _render_prompt(**overrides: object) -> str:
    kwargs: dict = {
        "skill_name": "review-hog-perspective-logic-correctness",
        "skill_version": 2,
        "chunk": _chunk("a.py"),
        "pr_metadata": _pr_metadata(),
        "pr_comments": [],
        "pr_files": [],
        "prior_findings": [],
    }
    kwargs.update(overrides)
    return build_review_prompt(**kwargs)


def test_covered_findings_filters_to_chunk_files_and_omits_suggestion() -> None:
    # The covered set feeds one chunk's review: only that chunk's files belong (other files are noise),
    # and our suggestion stays out (the agent must recognize the problem, not be handed our fix).
    out = _covered_findings_for_chunk(
        [_finding("a.py", "in chunk"), _finding("z.py", "other file")], [], _chunk("a.py")
    )
    assert out is not None
    parsed = json.loads(out)
    assert [f["title"] for f in parsed] == ["in chunk"]
    assert "suggestion" not in parsed[0]
    assert "our private fix" not in out


def test_covered_findings_is_none_when_nothing_on_chunk_files() -> None:
    # None lets the prompt omit the section entirely (no empty "already covered" block on a first run).
    assert _covered_findings_for_chunk([_finding("a.py", "x")], [], _chunk("b.py")) is None


def test_covered_findings_merges_same_turn_wave_issues_on_chunk_files() -> None:
    # Without the wave's issues in the covered block (chunk-filtered, `issue` mapped to `problem`),
    # the blind-spot check just re-reports the wave.
    out = _covered_findings_for_chunk([], [_issue("a.py", "wave issue"), _issue("z.py", "other file")], _chunk("a.py"))

    assert out is not None
    parsed = json.loads(out)
    assert [f["title"] for f in parsed] == ["wave issue"]
    assert parsed[0]["problem"] == "the wave problem"
    assert "the wave fix" not in out


def test_review_prompt_pins_the_skill_and_injects_wave_lenses_for_the_blind_spot_check() -> None:
    # The sweep = a normal pulled skill + the wave's lens list + dig-deeper framing; losing any of
    # the three silently degrades it to a generic re-review.
    prompt = _render_prompt(
        skill_name="review-hog-blind-spots-general",
        skill_version=3,
        same_turn_findings=[_issue("a.py", "covered wave problem")],
        dig_deeper=True,
        blind_spot_check=True,
        wave_perspectives={"review-hog-perspective-logic-correctness": "Checks the change's logic."},
    )

    assert 'skill-get(skill_name="review-hog-blind-spots-general", version=3)' in prompt
    assert "review-hog-perspective-logic-correctness" in prompt
    assert "Checks the change's logic." in prompt
    assert "go DEEPER" in prompt
    assert "covered wave problem" in prompt
    assert 'listed in "already_covered_findings_for_chunk" above' in prompt
    # The intro's parallel-isolation framing licenses re-reporting — the sweep gets the after-the-wave
    # variant instead.
    assert "without worrying about what the other perspectives might report" not in prompt
    assert "You are the blind-spot check" in prompt


def test_blind_spot_prompt_says_the_wave_found_nothing_instead_of_dangling() -> None:
    # A clean chunk is a normal wave outcome: the covered block is absent, so the lens lead-in must
    # say so rather than point at a section that does not exist.
    prompt = _render_prompt(
        skill_name="review-hog-blind-spots-general",
        skill_version=3,
        blind_spot_check=True,
        wave_perspectives={"review-hog-perspective-logic-correctness": "Checks the change's logic."},
    )

    assert "They raised no findings on this chunk's files" in prompt
    assert "already_covered_findings_for_chunk" not in prompt


def test_blind_spot_prompt_with_only_cross_turn_covered_findings_does_not_deny_the_list() -> None:
    # A clean wave this turn can coexist with covered findings from earlier reviews of the PR; the
    # lens lead-in must point at that list, not claim none exists right after rendering it.
    prompt = _render_prompt(
        skill_name="review-hog-blind-spots-general",
        skill_version=3,
        blind_spot_check=True,
        wave_perspectives={"review-hog-perspective-logic-correctness": "Checks the change's logic."},
        prior_findings=[_finding("a.py", "old problem")],
    )

    assert "old problem" in prompt
    assert "They raised no new findings on this chunk this turn" in prompt
    assert "there is no covered list" not in prompt


def test_blind_spot_prompt_on_a_zero_lens_chunk_says_it_is_the_only_reviewer() -> None:
    # Perspective selection can leave a chunk with no lenses at all; the sweep must be told it is
    # the chunk's only reviewer, not fed the specialist parallel-isolation framing.
    prompt = _render_prompt(
        skill_name="review-hog-blind-spots-general",
        skill_version=3,
        blind_spot_check=True,
        wave_perspectives={},
    )

    assert "you are its ONLY reviewer" in prompt
    assert "no ground is spoken for" in prompt
    assert "without worrying about what the other perspectives might report" not in prompt
    assert "You are the blind-spot check" not in prompt


def test_review_prompt_gives_regular_perspectives_no_cross_perspective_context() -> None:
    # A wave unit must stay blind to its siblings — leaking the lens list or the dig-deeper framing
    # into regular perspective prompts would collapse the isolation the parallel topology relies on.
    prompt = _render_prompt()

    assert 'skill-get(skill_name="review-hog-perspective-logic-correctness", version=2)' in prompt
    assert "ALREADY reviewed this exact chunk" not in prompt
    assert "go DEEPER" not in prompt
    assert "without worrying about what the other perspectives might report" in prompt
