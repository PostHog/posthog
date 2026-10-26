from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

API_DOCS = "https://docs.cloud.google.com/looker/docs/reference/looker-api/latest/methods"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "users": {
        "description": "Looker users, their profile fields, and their group and role IDs. Credentials and sessions are excluded.",
        "docs_url": f"{API_DOCS}/User/all_users",
        "columns": {
            "id": "The unique user ID.",
            "email": "The user's email address.",
            "is_disabled": "Whether the user's account is disabled.",
            "group_ids": "The IDs of the groups that contain the user.",
            "role_ids": "The IDs of the roles assigned to the user.",
        },
    },
    "looks": {
        "description": "Active saved Looks that the API user can access.",
        "docs_url": f"{API_DOCS}/Look/search_looks",
        "columns": {
            "id": "The unique Look ID.",
            "title": "The title of the Look.",
            "created_at": "The time when the Look was created.",
            "query_id": "The ID of the query used by the Look.",
        },
    },
    "dashboards": {
        "description": "Active dashboards created by users. LookML dashboards are excluded from the search endpoint.",
        "docs_url": f"{API_DOCS}/Dashboard/search_dashboards",
        "columns": {
            "id": "The unique dashboard ID.",
            "title": "The title of the dashboard.",
            "created_at": "The time when the dashboard was created.",
            "folder_id": "The ID of the folder that contains the dashboard.",
        },
    },
    "projects": {
        "description": "LookML projects visible to the API user in the production workspace.",
        "docs_url": f"{API_DOCS}/Project/all_projects",
        "columns": {
            "id": "The unique project ID.",
            "name": "The display name of the project.",
            "uses_git": "Whether the project uses a Git repository.",
        },
    },
    "folders": {
        "description": "Folders visible to the API user, including their parent folder and creator IDs.",
        "docs_url": f"{API_DOCS}/Folder/search_folders",
        "columns": {
            "id": "The unique folder ID.",
            "name": "The name of the folder.",
            "parent_id": "The ID of the parent folder.",
            "created_at": "The time when the folder was created.",
        },
    },
    "lookml_models": {
        "description": "LookML models and their Explore metadata visible to the API user.",
        "docs_url": f"{API_DOCS}/LookmlModel/all_lookml_models",
        "columns": {
            "name": "The unique model name.",
            "project_name": "The name of the project that contains the model.",
            "explores": "The Explores exposed by the model.",
        },
    },
}
