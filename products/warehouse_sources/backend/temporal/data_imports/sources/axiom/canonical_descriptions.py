from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "datasets": {
        "description": "Axiom datasets, including their retention settings and edge deployments.",
        "docs_url": "https://axiom.co/docs/restapi/endpoints/getDatasets",
        "columns": {
            "id": "Unique dataset identifier.",
            "name": "Unique dataset name.",
            "created": "Time when the dataset was created.",
            "updatedAt": "Time when the dataset was last updated.",
            "retentionDays": "Number of days that data remains in the dataset.",
            "kind": "Dataset type.",
            "edgeDeployment": "Edge deployment that stores the dataset.",
        },
    },
    "monitors": {
        "description": "Axiom monitor configurations visible to the token through its dataset permissions.",
        "docs_url": "https://axiom.co/docs/restapi/endpoints/getMonitors",
        "columns": {
            "id": "Unique monitor identifier.",
            "name": "Monitor name.",
            "type": "Monitor type: threshold, event match, or anomaly detection.",
            "createdAt": "Time when the monitor was created.",
            "updatedAt": "Time when the monitor was last updated.",
            "disabled": "Whether the monitor is disabled.",
            "intervalMinutes": "Number of minutes between monitor checks.",
            "rangeMinutes": "Number of minutes of data evaluated in each check.",
            "threshold": "Value that triggers an alert when the comparison condition is met.",
            "aplQuery": "APL query evaluated by the monitor.",
        },
    },
    "annotations": {
        "description": "Events marked on Axiom charts, such as deployments.",
        "docs_url": "https://axiom.co/docs/restapi/endpoints/getAnnotations",
        "columns": {
            "id": "Unique annotation identifier.",
            "datasets": "Dataset names whose charts show the annotation.",
            "time": "Time of the event marked on the chart.",
            "endTime": "End time of the annotation.",
            "title": "Short description shown on the chart.",
            "description": "Details of the marked event.",
            "type": "Event type, such as a production deployment.",
            "url": "Link to information about the marked event.",
        },
    },
    "dashboards": {
        "description": "Axiom dashboards visible to the caller. API tokens return shared dashboards only.",
        "docs_url": "https://axiom.co/docs/restapi/endpoints/getDashboards",
        "columns": {
            "id": "Unique dashboard identifier.",
            "uid": "Dashboard UID.",
            "dashboard": "Dashboard configuration, including charts, layout, owner, and time range.",
            "createdAt": "Time when the dashboard was created.",
            "updatedAt": "Time when the dashboard was last updated.",
            "version": "Dashboard version number.",
        },
    },
    "saved_queries": {
        "description": "Queries saved by users in the Axiom team, subject to the token permissions.",
        "docs_url": "https://axiom.co/docs/restapi/endpoints/getStarredQueries",
        "columns": {
            "id": "Unique saved query identifier.",
            "name": "Saved query name.",
            "dataset": "Dataset associated with the saved query.",
            "query": "Saved APL request and its options.",
            "who": "User who saved the query.",
        },
    },
}
