from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Projects": {
        "description": "A CodeScene project: a configured set of Git repositories analyzed together as one codebase.",
        "docs_url": "https://docs.enterprise.codescene.io/latest/integrations/rest-api.html",
        "columns": {
            "id": "Unique identifier for the project.",
            "name": "Name of the project as configured in CodeScene.",
        },
    },
    "Files": {
        "description": "Per-file Code Health, change frequency, defect, and cost-of-change metrics from a project's latest analysis.",
        "docs_url": "https://docs.enterprise.codescene.io/latest/integrations/rest-api.html",
        "columns": {
            "project_id": "Identifier of the CodeScene project this file belongs to.",
            "name": "Repository-relative path of the file.",
            "code_health": "Code Health score for the file (1-10, 10 being the healthiest).",
            "change_frequency": "How often the file has changed, relative to the rest of the codebase.",
            "lines_of_code": "Number of lines of code in the file.",
            "number_of_defects": "Number of defects (bug-fix commits) recorded against the file.",
            "cost": "Estimated cost-of-change score for the file.",
        },
    },
    "Components": {
        "description": "Architectural components (logical groupings of files) and their aggregate system-health metrics from a project's latest analysis.",
        "docs_url": "https://docs.enterprise.codescene.io/latest/integrations/rest-api.html",
        "columns": {
            "project_id": "Identifier of the CodeScene project this component belongs to.",
            "name": "Name of the architectural component.",
            "system_health": "Aggregate Code Health score for the component.",
            "change_frequency": "How often files in the component have changed, relative to the rest of the codebase.",
            "lines_of_code": "Number of lines of code in the component.",
        },
    },
    "Analyses": {
        "description": "The analysis runs recorded for a CodeScene project, newest first.",
        "docs_url": "https://docs.enterprise.codescene.io/latest/integrations/rest-api.html",
        "columns": {
            "project_id": "Identifier of the CodeScene project this analysis ran for.",
            "id": "Unique identifier of the analysis run, usable in place of `latest` on the analysis endpoints.",
            "name": "Display name of the analysis run.",
            "ref": "API path of the analysis resource.",
        },
    },
    "Issues": {
        "description": "Issues from a project's latest analysis, linking ticket data to the code changed while the issue was open.",
        "docs_url": "https://docs.enterprise.codescene.io/latest/integrations/rest-api.html",
        "columns": {
            "project_id": "Identifier of the CodeScene project this issue belongs to.",
            "id": "Issue identifier taken from the commit messages, for example a ticket key.",
            "status": "Status of the issue as reported by the project management integration.",
            "date": "Date the issue was first seen in the commit history.",
            "closed_at": "Date the issue was closed.",
            "cycle_time_hours": "Hours between the first and last commit that reference the issue.",
            "first_commit": "Hash of the first commit that references the issue.",
            "last_commit": "Hash of the last commit that references the issue.",
            "authors": "Number of authors who committed against the issue.",
            "files": "Number of files changed while the issue was open.",
            "loc_added": "Lines of code added across the issue's commits.",
            "loc_deleted": "Lines of code deleted across the issue's commits.",
            "file_changes": "Per-file breakdown of the lines added and deleted for the issue.",
            "href": "Link to the issue in the project management tool.",
        },
    },
    "TechnicalDebt": {
        "description": "Refactoring targets from a project's latest analysis: the hotspots CodeScene recommends paying down first.",
        "docs_url": "https://docs.enterprise.codescene.io/latest/integrations/rest-api.html",
        "columns": {
            "project_id": "Identifier of the CodeScene project this refactoring target belongs to.",
            "file_name": "Repository-relative path of the file recommended for refactoring.",
            "score": "Code Health score of the file (1-10, 10 being the healthiest).",
            "revisions": "Number of times the file changed over the analysis period.",
        },
    },
    "AuthorStatistics": {
        "description": "Per-author contribution statistics from a project's latest analysis.",
        "docs_url": "https://docs.enterprise.codescene.io/latest/integrations/rest-api.html",
        "columns": {
            "project_id": "Identifier of the CodeScene project these statistics cover.",
            "author": "Name of the author, as recorded in the commit history.",
            "commits": "Number of commits the author made over the analysis period.",
            "lines_of_code_added": "Lines of code the author added.",
            "lines_of_code_removed": "Lines of code the author removed.",
            "lines_of_code_net": "Lines added minus lines removed.",
            "first_contribution": "Date of the author's first commit.",
            "last_contribution": "Date of the author's most recent commit.",
            "months_contributing": "Number of months between the author's first and last commit.",
            "primary_file_owner": "Number of files where the author contributed most of the code.",
            "primary_component_owner": "Number of architectural components where the author contributed most of the code.",
            "commit_pattern": "Description of when the author commits, for example working hours or weekends.",
            "former_contributor": "Whether the author is marked as a former contributor in CodeScene.",
        },
    },
}
