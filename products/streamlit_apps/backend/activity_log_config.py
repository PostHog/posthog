FIELD_EXCLUSIONS = {
    "StreamlitApp": [
        # Reverse relations. Version uploads and activations log their own rows, and a version's
        # str() includes the app name, so a rename would show a false versions change.
        "versions",
        "sandbox",
    ],
}


SIGNAL_EXCLUSIONS = {
    # The facade logs a version change as `uploaded_version` or `activated_version` at the write
    # site, so the save that only moves the active version must not add an `updated` row.
    "StreamlitApp": ["active_version", "updated_at"],
}
