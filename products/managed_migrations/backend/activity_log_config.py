FIELD_EXCLUSIONS = {
    "BatchImport": [
        "lease_id",
        "leased_until",
        "status_message",
        "state",
        "secrets",
        "lease_id",
        "backoff_attempt",
        "backoff_until",
        "pending_commit",
    ],
}


FIELD_WITH_MASKED_CONTENTS = {
    "BatchImport": [
        "import_config",
    ],
}
