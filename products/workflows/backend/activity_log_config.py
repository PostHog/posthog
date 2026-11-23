FIELD_EXCLUSIONS = {
    "HogFlow": [
        # System-maintained skip-forward map for deleted steps, refreshed as a side effect of graph
        # writes — bookkeeping, not a user edit, so keep it out of change diffs.
        "action_redirects",
    ],
}


FIELD_WITH_MASKED_CONTENTS = {
    "HogFlow": [
        # Full content snapshot including action inputs (auth headers, API keys) — record that a
        # draft was staged/published/discarded, never its contents.
        "draft",
        # Encrypted secret function inputs (Fernet ciphertext) — a diff would be noise at best and
        # leak-adjacent at worst; record that they changed, never the values.
        "encrypted_inputs",
        "draft_encrypted_inputs",
        # The action graph can carry secret function inputs (auth headers, API keys). New writes strip
        # them into encrypted_inputs, but a legacy row's first write would diff its still-plaintext
        # `before` against the stripped `after`, leaking the secret. Record that actions changed, never
        # the contents — the per-version content audit lives in the revisions feature instead.
        "actions",
        # Reverse FK into WorkflowProposal's fail-closed manager, and a suggestion filed or resolved
        # is not a workflow edit.
        "proposals",
    ],
}
