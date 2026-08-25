"""Canonical, documentation-sourced descriptions for Cortex endpoints and columns.

Sourced from the official Cortex API reference (https://docs.cortex.io/api). Keyed by the
resource names in `settings.py` `ENDPOINTS`, which match the `ExternalDataSchema.name` of a
synced Cortex table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "entities": {
        "description": "A catalog entity (service, resource, or domain) tracked in Cortex.",
        "docs_url": "https://docs.cortex.io/api/readme/catalog-entities",
        "columns": {
            "id": "18-character unique identifier (CID) for the entity.",
            "tag": "Human-readable unique identifier (x-cortex-tag) for the entity.",
            "name": "Display name of the entity.",
            "type": "Entity type: service, resource, or domain (or a custom entity type).",
            "description": "Optional markdown description of the entity.",
            "isArchived": "Whether the entity has been archived.",
            "lastUpdated": "Timestamp the entity was last updated in Cortex.",
            "groups": "List of x-cortex-groups values assigned to the entity.",
            "hierarchy": "Parent and child entities in the ownership hierarchy.",
            "links": "Links attached to the entity (documentation, dashboards, etc.).",
            "slackChannels": "Slack channels associated with the entity.",
            "owners": "Individuals and teams that own the entity.",
            "git": "Linked git repository details, when configured.",
            "metadata": "Custom metadata key/value pairs defined on the entity.",
        },
    },
    "scorecards": {
        "description": "A Cortex scorecard: a set of rules used to grade catalog entities against a standard.",
        "docs_url": "https://docs.cortex.io/api/readme/scorecards",
        "columns": {
            "tag": "Unique identifier (tag) for the scorecard.",
            "name": "Display name of the scorecard.",
            "description": "Description of what the scorecard measures.",
            "dateCreated": "Timestamp the scorecard was created.",
            "lastUpdated": "Timestamp the scorecard was last updated.",
            "isDraft": "Whether the scorecard is still a draft (not yet evaluating entities).",
            "rules": "The rule expressions the scorecard evaluates.",
            "levels": "Ladder levels an entity can achieve based on its rule scores.",
            "notifications": "Notification settings for the scorecard.",
            "exemptions": "Rule exemption settings for the scorecard.",
            "evaluation": "Evaluation settings, such as the scoring window.",
        },
    },
    "scorecard_scores": {
        "description": "A single entity's score against a scorecard, one row per scorecard/entity pair.",
        "docs_url": "https://docs.cortex.io/api/readme/scorecards",
        "columns": {
            "scorecard_tag": "Tag of the scorecard this score belongs to.",
            "service": "The scored entity's identifying fields (tag, id, name, groups, owners).",
            "service_tag": "Tag of the scored entity.",
            "service_id": "CID of the scored entity.",
            "service_name": "Display name of the scored entity.",
            "score": "The score summary, rule-by-rule breakdown, and ladder level achieved.",
            "lastEvaluated": "Timestamp the score was last evaluated.",
            "ruleExemptions": "Rule exemptions requested or granted for this entity on this scorecard.",
        },
    },
    "entity_types": {
        "description": "A custom entity type (definition) available in the Cortex catalog, beyond the built-in service/domain/team types.",
        "docs_url": "https://docs.cortex.io/api/readme/entity-types",
        "columns": {
            "type": "Unique identifier for the entity type.",
            "name": "Display name of the entity type.",
            "description": "Description of the entity type.",
            "schema": "JSON schema describing the entity type's custom fields.",
            "source": "Whether the type is a built-in Cortex type or a custom one.",
            "iconTag": "Icon tag shown for entities of this type in the Cortex UI.",
        },
    },
    "teams": {
        "description": "A team in Cortex, either managed directly in Cortex or backed by an identity provider group.",
        "docs_url": "https://docs.cortex.io/api/readme/teams",
        "columns": {
            "id": "Unique identifier for the team.",
            "teamTag": "Human-readable unique identifier for the team.",
            "catalogEntityTag": "Tag of the catalog entity (of type team) associated with this team.",
            "type": "Whether the team is Cortex-managed (CORTEX) or identity-provider-backed (IDP).",
            "isArchived": "Whether the team has been archived.",
            "metadata": "Team name, description, and summary.",
            "links": "Links attached to the team.",
            "slackChannels": "Slack channels associated with the team.",
            "cortexTeam": "Member list, present for Cortex-managed teams.",
            "idpGroup": "Backing identity-provider group and its members, present for IDP-backed teams.",
        },
    },
    "relationship_types": {
        "description": "A type of relationship (e.g. 'depends-on') that can connect two catalog entities.",
        "docs_url": "https://docs.cortex.io/api/readme/entity-relationship-types",
        "columns": {
            "tag": "Unique identifier for the relationship type.",
            "name": "Display name of the relationship type.",
            "description": "Description of what the relationship type represents.",
            "allowCycles": "Whether cyclical relationships of this type are allowed.",
            "definitionLocation": "Whether the relationship can be defined from the source, destination, or both.",
            "isSingleSource": "Whether a destination entity can have only one source of this type.",
            "isSingleDestination": "Whether a source entity can have only one destination of this type.",
            "isCortexManaged": "Whether this is a built-in Cortex-managed relationship type.",
            "sourcesFilter": "Restrictions on which entity types/providers can be a source of this relationship.",
            "destinationsFilter": "Restrictions on which entity types/providers can be a destination of this relationship.",
            "sourceLabelSingular": "Singular display label for a source entity of this relationship.",
            "sourceLabelPlural": "Plural display label for source entities of this relationship.",
            "destinationLabelSingular": "Singular display label for a destination entity of this relationship.",
            "destinationLabelPlural": "Plural display label for destination entities of this relationship.",
        },
    },
    "relationships": {
        "description": "A single edge between two catalog entities for a given relationship type.",
        "docs_url": "https://docs.cortex.io/api/readme/entity-relationships",
        "columns": {
            "relationship_type_tag": "Tag of the relationship type this edge belongs to.",
            "relationshipTypeTag": "Tag of the relationship type this edge belongs to, as echoed by the API.",
            "sourceEntity": "Identifying fields of the source entity in the relationship.",
            "source_entity_tag": "Tag of the source entity in the relationship.",
            "source_entity_id": "CID of the source entity in the relationship.",
            "destinationEntity": "Identifying fields of the destination entity in the relationship.",
            "destination_entity_tag": "Tag of the destination entity in the relationship.",
            "destination_entity_id": "CID of the destination entity in the relationship.",
            "providerType": "Provider that supplied the relationship, when it was created via an integration.",
        },
    },
}
