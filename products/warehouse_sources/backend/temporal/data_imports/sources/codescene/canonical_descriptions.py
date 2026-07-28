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
}
