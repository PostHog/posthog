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
]
