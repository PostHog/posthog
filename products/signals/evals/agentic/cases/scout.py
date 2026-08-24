from products.signals.evals.agentic.datasets import ScoutCase, ScoutExpectation

CASES: list[ScoutCase] = [
    ScoutCase(
        case_id="scout_error_broad_reach",
        step="scout",
        skill_name="signals-scout-error-tracking",
        seed="error_burst",
        judging_notes=(
            "The project contains a fresh checkout exception affecting many distinct users. The scout should "
            "discover it through project queries, validate its reach, and author one report."
        ),
        expected_query_tools=("query-error-tracking-issues-list", "execute-sql"),
        expected=ScoutExpectation(expected_outcome="emit_report"),
    ),
    ScoutCase(
        case_id="scout_error_low_volume",
        step="scout",
        skill_name="signals-scout-error-tracking",
        seed="error_low_volume",
        judging_notes=(
            "The project contains a fresh checkout exception with only three occurrences from three users. "
            "The canonical disqualifier says not to author a report; remembering the observation is appropriate."
        ),
        expected_query_tools=("query-error-tracking-issues-list", "execute-sql"),
        expected=ScoutExpectation(expected_outcome=("remember", "no_output")),
    ),
    ScoutCase(
        case_id="scout_error_stuck_loop",
        step="scout",
        skill_name="signals-scout-error-tracking",
        seed="error_stuck_loop",
        judging_notes=(
            "A new UploadFinalizeError fires 2,000 times from two users in two hours. This is a narrow-reach retry "
            "storm rather than a broad outage, but the fresh volume and localized finalizeUpload stack make a P3 "
            "report appropriate. It must not be described as affecting 2,000 users."
        ),
        expected_query_tools=("query-error-tracking-issues-list", "execute-sql"),
        expected=ScoutExpectation(expected_outcome="emit_report"),
    ),
    ScoutCase(
        case_id="scout_error_known_upstream_noise",
        step="scout",
        skill_name="signals-scout-error-tracking",
        seed="error_upstream_noise",
        judging_notes=(
            "The project has a recurring OpenAI RateLimitError and a noise scratchpad entry identifying the provider "
            "limit as known upstream behavior. Its recent shape is steady, so the scout should not author a report."
        ),
        expected_query_tools=("query-error-tracking-issues-list", "execute-sql"),
        expected=ScoutExpectation(expected_outcome=("remember", "no_output")),
    ),
    ScoutCase(
        case_id="scout_funnel_steady_denominator_regression",
        step="scout",
        skill_name="signals-scout-product-analytics",
        seed="funnel_regression",
        judging_notes=(
            "A saved activation funnel has a stable entrant count but its latest complete-window conversion is "
            "well below six comparable baseline windows. The scout should query the funnel and author one report."
        ),
        expected_query_tools=("query-funnel",),
        expected=ScoutExpectation(expected_outcome="emit_report"),
    ),
    ScoutCase(
        case_id="scout_funnel_denominator_drop",
        step="scout",
        skill_name="signals-scout-product-analytics",
        seed="funnel_denominator_drop",
        judging_notes=(
            "The saved funnel's latest conversion and entrant count both collapse. The canonical scout treats "
            "that as a volume or capture problem, so it should remember the result without authoring a report."
        ),
        expected_query_tools=("query-funnel",),
        expected=ScoutExpectation(expected_outcome=("remember", "no_output")),
    ),
    ScoutCase(
        case_id="scout_web_vitals_standing_poor_lcp",
        step="scout",
        skill_name="signals-scout-web-vitals",
        seed="web_vitals_poor_lcp",
        judging_notes=(
            "The /files route has 1,200 seven-day samples, stable traffic, and a p75 LCP above 5 seconds while FCP "
            "remains good. The canonical absolute threshold and volume gate require one report even though the page "
            "has been steadily slow rather than newly regressing."
        ),
        expected_query_tools=("execute-sql",),
        expected=ScoutExpectation(expected_outcome="emit_report"),
    ),
    ScoutCase(
        case_id="scout_web_vitals_low_sample_poor_lcp",
        step="scout",
        skill_name="signals-scout-web-vitals",
        seed="web_vitals_low_sample",
        judging_notes=(
            "The /files route has only 30 seven-day samples. Its apparent p75 LCP is poor, but the canonical volume "
            "gate treats that percentile as noise, so the scout should remember or close without a report."
        ),
        expected_query_tools=("execute-sql",),
        expected=ScoutExpectation(expected_outcome=("remember", "no_output")),
    ),
]
