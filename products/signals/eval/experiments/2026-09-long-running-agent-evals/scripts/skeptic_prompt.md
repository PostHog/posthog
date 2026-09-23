# Skeptic prompt (one report judged real)

A judge decided the defect below is real at commit {commit}. Your job is to refute it. Look for: an inherited ordering or manager the judge missed, a paginator that adds a tie-breaker, a permission layer that scopes the queryset, a bounded or single-page response, a prefetch on a parent queryset, or an existing test that proves the behavior the report denies. Read the code; do not trust either the report or the judge.

Return JSON: {"refuted": true|false, "reason": "...", "evidence": "file:lines"}. Default to refuted=false only when you looked and found nothing.
