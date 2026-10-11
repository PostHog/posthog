from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "builds": {
        "description": "One row per CI build reported to Coveralls across every configured repository, "
        "with its coverage totals and commit metadata.",
        "docs_url": "https://docs.coveralls.io/api-introduction",
        "columns": {
            "id": "Unique identifier of the build on Coveralls.",
            "repo_name": "Repository the build belongs to, in owner/repo form.",
            "branch": "Git branch the build ran against.",
            "url": "URL associated with the build, when set.",
            "badge_url": "URL of the coverage badge image generated for this build.",
            "commit_sha": "SHA of the commit the coverage report was generated for.",
            "commit_message": "Message of the commit the coverage report was generated for.",
            "committer_name": "Name of the commit author.",
            "committer_email": "Email of the commit author.",
            "created_at": "When the build was created on Coveralls.",
            "updated_at": "When the build was last updated on Coveralls (e.g. after a recalculation).",
            "calculated_at": "When Coveralls last calculated the build's coverage.",
            "covered_percent": "Percentage of relevant lines covered by tests in this build.",
            "coverage_change": "Change in covered_percent compared to the previous build.",
            "covered_lines": "Number of relevant lines executed by tests.",
            "missed_lines": "Number of relevant lines not executed by tests.",
            "relevant_lines": "Total number of lines considered relevant for coverage.",
            "covered_branches": "Number of relevant branches executed by tests.",
            "missed_branches": "Number of relevant branches not executed by tests.",
            "relevant_branches": "Total number of branches considered relevant for coverage.",
        },
    },
    "repositories": {
        "description": "Repository-level Coveralls configuration for each configured repository, from "
        "the /api/v1/repos endpoint (requires a personal API token).",
        "docs_url": "https://docs.coveralls.io/api-repos-endpoint",
        "columns": {
            "service": "Git hosting service the repository lives on (github, gitlab, or bitbucket).",
            "name": "Repository name in owner/repo form.",
            "comment_on_pull_requests": "Whether Coveralls comments coverage results on pull requests.",
            "send_build_status": "Whether Coveralls sends commit status checks to the git service.",
            "commit_status_fail_threshold": "Minimum coverage percentage below which the commit status fails.",
            "commit_status_fail_change_threshold": "Maximum allowed coverage drop before the commit status fails.",
            "created_at": "When the repository was added to Coveralls.",
            "updated_at": "When the repository's Coveralls configuration was last updated.",
        },
    },
}
