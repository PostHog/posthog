from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "tests": {
        "description": "Network and Application Synthetics tests in the selected account group.",
        "docs_url": "https://docs.thousandeyes.com/product-documentation/getting-started/getting-started-with-the-thousandeyes-api",
        "columns": {
            "testId": "Unique test identifier.",
            "testName": "Test name.",
            "type": "Test type.",
        },
    },
    "agents": {
        "description": "Cloud and Enterprise Agents available to the selected account group.",
        "docs_url": "https://developer.cisco.com/docs/thousandeyes/list-cloud-and-enterprise-agents/",
        "columns": {
            "agentId": "Unique agent identifier.",
            "agentName": "Agent name.",
            "agentType": "Agent type.",
        },
    },
    "alert_rules": {
        "description": "Rules that trigger alerts for Network and Application Synthetics tests and Routing tests.",
        "docs_url": "https://developer.cisco.com/docs/thousandeyes/list-alert-rules/",
        "columns": {
            "ruleId": "Unique rule identifier.",
            "ruleName": "Rule name.",
            "expression": "Conditions that trigger the alert.",
            "severity": "Alert severity.",
        },
    },
    "active_alerts": {
        "description": "Active alerts that started within the last 30 days.",
        "docs_url": "https://developer.cisco.com/docs/thousandeyes/list-alerts/",
        "columns": {
            "id": "Unique identifier for an alert occurrence.",
            "alertType": "Test layer that triggered the alert.",
            "duration": "Time the alert was active, in seconds.",
        },
    },
    "cleared_alerts": {
        "description": "Alerts that cleared within the last 30 days.",
        "docs_url": "https://developer.cisco.com/docs/thousandeyes/list-alerts/",
        "columns": {
            "id": "Unique identifier for an alert occurrence.",
            "alertType": "Test layer that triggered the alert.",
            "duration": "Time the alert was active, in seconds.",
        },
    },
    "http_server_results": {
        "description": "HTTP measurements for each agent and round of live HTTP Server tests. Initial sync covers 30 days.",
        "docs_url": "https://developer.cisco.com/docs/thousandeyes/v7/get-http-server-test-results/",
        "columns": {
            "testId": "Parent test identifier.",
            "agentId": "Identifier of the agent that measured the result.",
            "roundId": "Round start time, in seconds since the Unix epoch.",
            "date": "Measurement date and time in UTC.",
            "responseCode": "HTTP response code.",
            "responseTime": "Time to the first response byte, in milliseconds.",
            "dnsTime": "DNS resolution time, in milliseconds.",
            "waitTime": "Time from the completed request to the first response byte, in milliseconds.",
            "receiveTime": "Time between the first and last response bytes, in milliseconds.",
        },
    },
}
