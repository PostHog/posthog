from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "datasets": {
        "description": "A collection of data such as a table, view, stream, or file, with its schema, ownership, tags, and upstream lineage aspects.",
        "docs_url": "https://docs.datahub.com/docs/generated/metamodel/entities/dataset",
        "columns": {
            "urn": "Unique resource name identifying the dataset across the metadata graph.",
            "datasetProperties": "Display name, description, custom properties, and created/last-modified timestamps of the dataset.",
            "schemaMetadata": "Column-level schema of the dataset: field paths, native and logical types, and field descriptions.",
            "ownership": "Owners of the dataset and their ownership types.",
            "globalTags": "Tags applied to the dataset.",
            "glossaryTerms": "Business glossary terms attached to the dataset.",
            "domains": "Domains the dataset belongs to.",
            "container": "The container (e.g. database or schema) the dataset lives in.",
            "upstreamLineage": "Upstream lineage edges: the datasets this dataset is derived from, with per-column fine-grained lineage where available.",
            "status": "Soft-deletion status of the entity.",
            "subTypes": "More specific type of the dataset, e.g. table, view, or topic.",
        },
    },
    "containers": {
        "description": "A grouping of datasets such as a database, schema, project, or folder on a data platform.",
        "docs_url": "https://docs.datahub.com/docs/generated/metamodel/entities/container",
        "columns": {
            "urn": "Unique resource name identifying the container.",
            "containerProperties": "Display name, description, and custom properties of the container.",
            "container": "The parent container, when nested (e.g. a schema's database).",
            "ownership": "Owners of the container and their ownership types.",
            "subTypes": "More specific type of the container, e.g. database or schema.",
        },
    },
    "dashboards": {
        "description": "A dashboard in a BI tool, with the charts and datasets it is built from.",
        "docs_url": "https://docs.datahub.com/docs/generated/metamodel/entities/dashboard",
        "columns": {
            "urn": "Unique resource name identifying the dashboard.",
            "dashboardInfo": "Title, description, external URL, chart edges, and last-modified audit stamps of the dashboard.",
            "ownership": "Owners of the dashboard and their ownership types.",
            "globalTags": "Tags applied to the dashboard.",
            "domains": "Domains the dashboard belongs to.",
            "status": "Soft-deletion status of the entity.",
        },
    },
    "charts": {
        "description": "A single visualization in a BI tool, with the source datasets it reads from.",
        "docs_url": "https://docs.datahub.com/docs/generated/metamodel/entities/chart",
        "columns": {
            "urn": "Unique resource name identifying the chart.",
            "chartInfo": "Title, description, external URL, chart type, and input dataset edges of the chart.",
            "inputFields": "Schema fields of upstream datasets the chart reads.",
            "ownership": "Owners of the chart and their ownership types.",
            "globalTags": "Tags applied to the chart.",
            "status": "Soft-deletion status of the entity.",
        },
    },
    "data_flows": {
        "description": "An orchestration pipeline (e.g. an Airflow DAG or dbt project) that groups data jobs.",
        "docs_url": "https://docs.datahub.com/docs/generated/metamodel/entities/dataflow",
        "columns": {
            "urn": "Unique resource name identifying the data flow.",
            "dataFlowInfo": "Name, description, project, and external URL of the pipeline.",
            "ownership": "Owners of the pipeline and their ownership types.",
            "globalTags": "Tags applied to the pipeline.",
            "status": "Soft-deletion status of the entity.",
        },
    },
    "data_jobs": {
        "description": "A task within a data flow (e.g. an Airflow task), with the datasets it consumes and produces.",
        "docs_url": "https://docs.datahub.com/docs/generated/metamodel/entities/datajob",
        "columns": {
            "urn": "Unique resource name identifying the data job.",
            "dataJobInfo": "Name, description, type, and external URL of the task.",
            "dataJobInputOutput": "Lineage edges of the task: input and output datasets and upstream jobs.",
            "ownership": "Owners of the task and their ownership types.",
            "globalTags": "Tags applied to the task.",
            "status": "Soft-deletion status of the entity.",
        },
    },
    "data_platforms": {
        "description": "A data system type known to DataHub (e.g. Snowflake, BigQuery, Kafka) that other entities reference.",
        "docs_url": "https://docs.datahub.com/docs/generated/metamodel/entities/dataplatform",
        "columns": {
            "urn": "Unique resource name identifying the platform.",
            "dataPlatformInfo": "Name, display name, type, dataset name delimiter, and logo of the platform.",
        },
    },
    "data_products": {
        "description": "A curated data product grouping related data assets within a domain.",
        "docs_url": "https://docs.datahub.com/docs/generated/metamodel/entities/dataproduct",
        "columns": {
            "urn": "Unique resource name identifying the data product.",
            "dataProductProperties": "Name, description, and the asset edges that make up the data product.",
            "domains": "The domain the data product belongs to.",
            "ownership": "Owners of the data product and their ownership types.",
        },
    },
    "domains": {
        "description": "A top-level business category (e.g. Marketing, Finance) used to organize data assets.",
        "docs_url": "https://docs.datahub.com/docs/generated/metamodel/entities/domain",
        "columns": {
            "urn": "Unique resource name identifying the domain.",
            "domainProperties": "Name, description, and parent domain of the domain.",
            "ownership": "Owners of the domain and their ownership types.",
        },
    },
    "glossary_terms": {
        "description": "A business glossary term that defines shared vocabulary and can be attached to data assets.",
        "docs_url": "https://docs.datahub.com/docs/generated/metamodel/entities/glossaryterm",
        "columns": {
            "urn": "Unique resource name identifying the glossary term.",
            "glossaryTermInfo": "Name, definition, source, and parent node of the term.",
            "glossaryRelatedTerms": "Relationships to other glossary terms (inherits, contains).",
            "ownership": "Owners of the term and their ownership types.",
        },
    },
    "glossary_nodes": {
        "description": "A folder-like grouping node in the business glossary hierarchy.",
        "docs_url": "https://docs.datahub.com/docs/generated/metamodel/entities/glossarynode",
        "columns": {
            "urn": "Unique resource name identifying the glossary node.",
            "glossaryNodeInfo": "Name, definition, and parent node of the glossary node.",
            "ownership": "Owners of the node and their ownership types.",
        },
    },
    "tags": {
        "description": "A label that can be applied to any data asset or schema field for search and governance.",
        "docs_url": "https://docs.datahub.com/docs/generated/metamodel/entities/tag",
        "columns": {
            "urn": "Unique resource name identifying the tag.",
            "tagProperties": "Name, description, and color of the tag.",
            "ownership": "Owners of the tag and their ownership types.",
        },
    },
    "users": {
        "description": "A person (or service account) known to DataHub, referenced as an owner of data assets.",
        "docs_url": "https://docs.datahub.com/docs/generated/metamodel/entities/corpuser",
        "columns": {
            "urn": "Unique resource name identifying the user.",
            "corpUserInfo": "Display name, email, title, and manager of the user as synced from the identity provider.",
            "corpUserEditableInfo": "Profile fields the user edited in DataHub (about, skills, teams).",
            "groupMembership": "Groups the user belongs to.",
            "corpUserStatus": "Whether the user is active or suspended.",
            "status": "Soft-deletion status of the entity.",
        },
    },
    "groups": {
        "description": "A group of users, referenced as an owner of data assets.",
        "docs_url": "https://docs.datahub.com/docs/generated/metamodel/entities/corpgroup",
        "columns": {
            "urn": "Unique resource name identifying the group.",
            "corpGroupInfo": "Display name, description, email, and membership of the group.",
            "ownership": "Owners of the group and their ownership types.",
        },
    },
}
