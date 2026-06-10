from products.posthog_ai.backend.context_wrapper import AttachedContext, ContextService


def test_wrap_empty_returns_content_verbatim():
    assert ContextService().wrap_user_message("hello", []) == "hello"


def test_wrap_one_of_each_entity_type():
    attached: list[AttachedContext] = [
        {"type": "dashboard", "id": 123, "name": "Marketing Funnel"},
        {"type": "insight", "id": "abc-def", "name": "Daily Signups"},
        {"type": "event", "id": "$pageview", "name": "Pageview"},
        {"type": "action", "id": 7, "name": "Signed up"},
        {"type": "error_tracking_issue", "id": "019249ab-0000", "name": "TypeError in checkout"},
        {"type": "evaluation", "id": "eval-1", "name": "Tone eval"},
        {"type": "notebook", "id": "nb-9", "name": "Launch notes"},
    ]
    wrapped = ContextService().wrap_user_message("Why did checkout drop?", attached)
    assert wrapped == (
        "<posthog_context>\n"
        "The user attached the following PostHog entities. "
        "Use the appropriate tools to retrieve their details only if relevant to the request.\n"
        '- Dashboard #123 ("Marketing Funnel")\n'
        '- Insight #abc-def ("Daily Signups")\n'
        '- Event #$pageview ("Pageview")\n'
        '- Action #7 ("Signed up")\n'
        '- Error tracking issue #019249ab-0000 ("TypeError in checkout")\n'
        '- Evaluation #eval-1 ("Tone eval")\n'
        '- Notebook #nb-9 ("Launch notes")\n'
        "</posthog_context>\n"
        "\n"
        "Why did checkout drop?"
    )


def test_wrap_mixed_with_free_text():
    attached: list[AttachedContext] = [
        {"type": "dashboard", "id": 1, "name": "Funnel"},
        {"type": "text", "value": "I think this regressed in last Thursday's deploy"},
    ]
    wrapped = ContextService().wrap_user_message("Investigate", attached)
    assert wrapped == (
        "<posthog_context>\n"
        "The user attached the following PostHog entities. "
        "Use the appropriate tools to retrieve their details only if relevant to the request.\n"
        '- Dashboard #1 ("Funnel")\n'
        '- Free text: "I think this regressed in last Thursday\'s deploy"\n'
        "</posthog_context>\n"
        "\n"
        "Investigate"
    )


def test_wrap_missing_name_falls_back_to_id_only():
    attached: list[AttachedContext] = [
        {"type": "dashboard", "id": 42},
        {"type": "insight", "id": "xyz"},
    ]
    wrapped = ContextService().wrap_user_message("Look", attached)
    assert wrapped == (
        "<posthog_context>\n"
        "The user attached the following PostHog entities. "
        "Use the appropriate tools to retrieve their details only if relevant to the request.\n"
        "- Dashboard #42\n"
        "- Insight #xyz\n"
        "</posthog_context>\n"
        "\n"
        "Look"
    )


def test_prune_dedupes_repeated_entity_refs():
    prior = [("dashboard", 123), ("insight", "abc")]
    attached: list[AttachedContext] = [
        {"type": "dashboard", "id": 123, "name": "Funnel"},
        {"type": "insight", "id": "abc", "name": "Signups"},
        {"type": "action", "id": 9, "name": "New action"},
    ]
    deduped = ContextService().prune_repeated_entity_refs(attached, prior=prior)
    assert deduped == [{"type": "action", "id": 9, "name": "New action"}]


def test_prune_dedupes_within_same_batch():
    attached: list[AttachedContext] = [
        {"type": "dashboard", "id": 1},
        {"type": "dashboard", "id": 1, "name": "Same dashboard"},
    ]
    deduped = ContextService().prune_repeated_entity_refs(attached, prior=[])
    assert deduped == [{"type": "dashboard", "id": 1}]


def test_prune_never_dedupes_repeated_text():
    attached: list[AttachedContext] = [
        {"type": "text", "value": "Error A"},
        {"type": "text", "value": "Error A"},
    ]
    deduped = ContextService().prune_repeated_entity_refs(attached, prior=[("text", "Error A")])
    assert deduped == attached


def test_prune_then_wrap_empties_to_bare_content():
    # When dedupe removes everything, wrap forwards the message without any block.
    prior = [("dashboard", 1)]
    attached: list[AttachedContext] = [{"type": "dashboard", "id": 1, "name": "Funnel"}]
    deduped = ContextService().prune_repeated_entity_refs(attached, prior=prior)
    assert ContextService().wrap_user_message("just text", deduped) == "just text"
