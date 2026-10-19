from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "projects": {
        "description": "Localization projects that the API token can access.",
        "docs_url": "https://developers.lokalise.com/reference/list-all-projects",
        "columns": {
            "project_id": "The unique project identifier.",
            "name": "The project name.",
            "team_id": "The identifier of the team that owns the project.",
            "created_at": "The time when the project was created.",
        },
    },
    "keys": {
        "description": "Translation keys and their metadata in each project.",
        "docs_url": "https://developers.lokalise.com/reference/list-all-keys",
        "columns": {
            "project_id": "The identifier of the project that contains the key.",
            "key_id": "The key identifier within the project.",
            "key_name": "The key name for each platform.",
            "created_at": "The time when the key was created.",
        },
    },
    "translations": {
        "description": "Translations for each key and language in a project.",
        "docs_url": "https://developers.lokalise.com/reference/list-all-translations",
        "columns": {
            "project_id": "The identifier of the project that contains the translation.",
            "translation_id": "The translation identifier within the project.",
            "key_id": "The identifier of the translated key.",
            "language_iso": "The language code for the translation.",
            "translation": "The translated text.",
        },
    },
    "languages": {
        "description": "Languages configured in each project.",
        "docs_url": "https://developers.lokalise.com/reference/list-project-languages",
        "columns": {
            "project_id": "The identifier of the project that uses the language.",
            "lang_id": "The language identifier.",
            "lang_iso": "The language code.",
            "lang_name": "The language name.",
        },
    },
    "contributors": {
        "description": "Project contributors and their access permissions.",
        "docs_url": "https://developers.lokalise.com/reference/list-all-contributors",
        "columns": {
            "project_id": "The identifier of the project that the contributor can access.",
            "user_id": "The contributor identifier.",
            "languages": "The contributor's language permissions.",
            "is_admin": "Whether the contributor is a project administrator.",
        },
    },
    "comments": {
        "description": "Comments on translation keys in each project.",
        "docs_url": "https://developers.lokalise.com/reference/list-project-comments",
        "columns": {
            "project_id": "The identifier of the project that contains the comment.",
            "comment_id": "The comment identifier within the project.",
            "key_id": "The identifier of the key that contains the comment.",
            "comment": "The comment text.",
            "added_at": "The time when the comment was added.",
        },
    },
    "screenshots": {
        "description": "Screenshot metadata and links attached to project keys.",
        "docs_url": "https://developers.lokalise.com/reference/list-all-screenshots",
        "columns": {
            "project_id": "The identifier of the project that contains the screenshot.",
            "screenshot_id": "The screenshot identifier within the project.",
            "url": "The location of the screenshot image.",
            "key_ids": "The identifiers of keys attached to the screenshot.",
        },
    },
    "tasks": {
        "description": "Translation tasks and their status in each project.",
        "docs_url": "https://developers.lokalise.com/reference/list-all-tasks",
        "columns": {
            "project_id": "The identifier of the project that contains the task.",
            "task_id": "The task identifier within the project.",
            "status": "The task status.",
            "progress": "The percentage of the task that is complete.",
            "created_at": "The time when the task was created.",
        },
    },
}
