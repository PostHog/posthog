from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the ConfigCat Public Management API docs
# (https://api.configcat.com/docs). Partial coverage is fine — uncovered columns fall back to LLM
# enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "products": {
        "description": "A ConfigCat product — the top-level container that groups configs, environments, and feature flags.",
        "docs_url": "https://api.configcat.com/docs",
        "columns": {
            "productId": "The unique identifier (GUID) of the product.",
            "name": "The name of the product.",
            "description": "The description of the product.",
            "order": "The display order of the product within the organization.",
            "reasonRequired": "Whether a mandatory reason is required for changes in this product.",
            "organization": "The organization that owns the product (nested object with organizationId and name).",
        },
    },
    "organizations": {
        "description": "A ConfigCat organization — the account-level owner of products and members.",
        "docs_url": "https://api.configcat.com/docs",
        "columns": {
            "organizationId": "The unique identifier (GUID) of the organization.",
            "name": "The name of the organization.",
        },
    },
    "configs": {
        "description": "A ConfigCat config — the container within a product that groups feature flags and settings.",
        "docs_url": "https://api.configcat.com/docs",
        "columns": {
            "configId": "The unique identifier (GUID) of the config.",
            "name": "The name of the config.",
            "description": "The description of the config.",
            "order": "The display order of the config within the product.",
            "migratedConfigId": "The identifier of the config this one was migrated from, when it replaced an older config.",
            "evaluationVersion": "The flag evaluation version the config uses (v1 or v2).",
            "product": "The product that owns the config (nested object with productId and name).",
        },
    },
    "environments": {
        "description": "A ConfigCat environment — a deployment target such as production or staging, which each feature flag holds its own value in.",
        "docs_url": "https://api.configcat.com/docs",
        "columns": {
            "environmentId": "The unique identifier (GUID) of the environment.",
            "name": "The name of the environment.",
            "color": "The color configured for the environment on the ConfigCat dashboard.",
            "description": "The description of the environment.",
            "order": "The display order of the environment within the product.",
            "reasonRequired": "Whether a mandatory reason is required every time a flag is saved in this environment.",
            "approveRequired": "Whether changes must be approved before they apply in this environment.",
            "product": "The product that owns the environment (nested object with productId and name).",
        },
    },
    "settings": {
        "description": "A ConfigCat feature flag or setting — the definition of the flag itself, without its per-environment values.",
        "docs_url": "https://api.configcat.com/docs",
        "columns": {
            "settingId": "The identifier of the feature flag or setting.",
            "key": "The key the SDKs read the feature flag or setting by.",
            "name": "The name of the feature flag or setting.",
            "hint": "The description of the feature flag or setting.",
            "order": "The display order of the feature flag or setting within the config.",
            "settingType": "The value type of the feature flag or setting (boolean, string, int or double).",
            "isJson": "Whether string values are validated as JSON.",
            "configId": "The unique identifier (GUID) of the config the feature flag or setting belongs to.",
            "configName": "The name of the config the feature flag or setting belongs to.",
            "createdAt": "The creation time of the feature flag or setting.",
            "tags": "The tags attached to the feature flag or setting.",
            "predefinedVariations": "The predefined variations of the feature flag or setting.",
        },
    },
    "setting_values": {
        "description": "The value a ConfigCat feature flag or setting evaluates to in one environment, with its targeting rules — one row per flag per environment.",
        "docs_url": "https://api.configcat.com/docs",
        "columns": {
            "configId": "The unique identifier (GUID) of the config the value belongs to.",
            "environmentId": "The unique identifier (GUID) of the environment the value applies to.",
            "settingId": "The identifier of the feature flag or setting the value belongs to.",
            "defaultValue": "The value served when no targeting rule matches.",
            "targetingRules": "The targeting rules of the feature flag or setting in this environment.",
            "setting": "The feature flag or setting the value belongs to (nested object with settingId, key, name and type).",
            "percentageEvaluationAttribute": "The user attribute used for percentage evaluation. Defaults to the Identifier attribute.",
            "updatedAt": "The time the feature flag or setting was last updated in this environment.",
            "lastVersionId": "The version identifier of the last change made in this environment.",
            "lastUpdaterUserEmail": "The email of the user who last updated the feature flag or setting.",
            "lastUpdaterUserFullName": "The name of the user who last updated the feature flag or setting.",
            "integrationLinks": "The integration links attached to the feature flag or setting.",
            "settingTags": "The tags attached to the feature flag or setting.",
            "settingIdsWherePrerequisite": "The feature flags and settings that depend on this one as a prerequisite.",
            "changeRequestCount": "The number of open change requests for the feature flag or setting.",
        },
    },
}
