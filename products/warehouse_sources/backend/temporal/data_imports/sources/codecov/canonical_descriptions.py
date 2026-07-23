from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "repos": {
        "description": "A repository Codecov tracks for the configured owner, with its latest coverage totals.",
        "docs_url": "https://docs.codecov.com/reference/repos_list",
        "columns": {
            "name": "Repository name, unique within the owner.",
            "private": "Whether the repository is private on the git provider.",
            "updatestamp": "When Codecov last updated its state for this repository.",
            "author": "Owner of the repository (service, username, name).",
            "language": "Primary programming language of the repository.",
            "branch": "Default branch used for coverage reporting.",
            "active": "Whether the repository has received a coverage upload.",
            "activated": "Whether the repository has been manually activated in Codecov.",
            "totals": "Latest coverage totals for the default branch (files, lines, hits, misses, partials, coverage percentage).",
        },
    },
    "branches": {
        "description": "A branch of a repository that has coverage data in Codecov.",
        "docs_url": "https://docs.codecov.com/reference/repos_branches_list",
        "columns": {
            "repo": "Repository the branch belongs to (injected by the import).",
            "name": "Branch name, unique within the repository.",
            "updatestamp": "When coverage data for the branch was last updated.",
        },
    },
    "commits": {
        "description": "A commit with a coverage upload on the repository's default branch.",
        "docs_url": "https://docs.codecov.com/reference/repos_commits_list",
        "columns": {
            "repo": "Repository the commit belongs to (injected by the import).",
            "commitid": "Full git commit SHA.",
            "message": "Commit message.",
            "timestamp": "Commit timestamp.",
            "ci_passed": "Whether CI passed for this commit, if known.",
            "author": "Commit author (service, username, name).",
            "branch": "Branch the coverage upload was reported against.",
            "totals": "Coverage totals for the commit (files, lines, hits, misses, partials, coverage percentage).",
            "state": "Codecov processing state of the commit report (e.g. complete).",
            "parent": "SHA of the parent commit.",
        },
    },
    "pulls": {
        "description": "A pull request Codecov tracks for a repository, with base/head coverage totals.",
        "docs_url": "https://docs.codecov.com/reference/repos_pulls_list",
        "columns": {
            "repo": "Repository the pull request belongs to (injected by the import).",
            "pullid": "Pull request number on the git provider.",
            "title": "Pull request title.",
            "base_totals": "Coverage totals of the base commit.",
            "head_totals": "Coverage totals of the head commit.",
            "updatestamp": "When Codecov last updated its state for this pull request.",
            "state": "Pull request state (open, merged, closed).",
            "ci_passed": "Whether CI passed on the head commit, if known.",
            "author": "Pull request author (service, username, name).",
            "patch": "Patch coverage totals for the lines changed by the pull request.",
        },
    },
    "flags": {
        "description": "Current coverage per flag (a user-defined grouping of coverage uploads) in a repository.",
        "docs_url": "https://docs.codecov.com/reference/repos_flags_list",
        "columns": {
            "repo": "Repository the flag belongs to (injected by the import).",
            "flag_name": "Flag name, unique within the repository.",
            "coverage": "Latest coverage percentage for the flag.",
        },
    },
    "components": {
        "description": "Current coverage per component (a path/flag-based slice of a repository defined in codecov.yml).",
        "docs_url": "https://docs.codecov.com/reference/repos_components_list",
        "columns": {
            "repo": "Repository the component belongs to (injected by the import).",
            "component_id": "Component identifier from the repository's Codecov configuration.",
            "name": "Display name of the component.",
            "coverage": "Latest coverage percentage for the component.",
        },
    },
    "coverage_trend": {
        "description": "Daily coverage time series for a repository's default branch.",
        "docs_url": "https://docs.codecov.com/reference/repos_coverage_list",
        "columns": {
            "repo": "Repository the measurement belongs to (injected by the import).",
            "timestamp": "Start of the measured interval (one day).",
            "min": "Minimum coverage percentage observed in the interval.",
            "max": "Maximum coverage percentage observed in the interval.",
            "avg": "Average coverage percentage observed in the interval.",
        },
    },
}
