FIELD_EXCLUSIONS = {
    "StamphogRepoConfig": [
        # Reverse relation to the repo's review history. The diff would read every pull request row
        # on each settings toggle, and none of it is configuration.
        "pull_requests",
    ],
}
