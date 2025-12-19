# =============================================================================
# PostHog Insights Configuration
# =============================================================================
#
# This file demonstrates how to manage PostHog insights using Terraform.
# Insights can be linked to dashboards via dashboard_ids.
#
# For more information, see:
#   https://registry.terraform.io/providers/PostHog/posthog/latest/docs/resources/insight
# =============================================================================

# Terraform configuration for PostHog insight
# Compatible with posthog provider v1.0
# Source insight ID: 5089102
# Short ID: tycwiOT1
import {
  to = posthog_insight.shared_dashboard_stats
  id = "5089102"
}

resource "posthog_insight" "shared_dashboard_stats" {
  name = "Shared Dashboard Stats"
  query_json = jsonencode({
    "kind": "InsightVizNode",
    "source": {
      "kind": "TrendsQuery",
      "series": [
        {
          "kind": "EventsNode",
          "math": "total",
          "event": "viewed dashboard",
          "properties": [
            {
              "key": "is_shared",
              "type": "event",
              "value": "true",
              "operator": "exact"
            }
          ],
          "math_property": null,
          "math_property_type": null,
          "math_group_type_index": null
        },
        {
          "kind": "EventsNode",
          "math": "total",
          "name": "dashboard share toggled",
          "event": "dashboard share toggled",
          "properties": [
            {
              "key": "is_shared",
              "type": "event",
              "value": [
                "true"
              ],
              "operator": "exact"
            }
          ]
        }
      ],
      "version": 2,
      "interval": "day",
      "dateRange": {
        "date_to": null,
        "date_from": "-30d"
      },
      "properties": [],
      "trendsFilter": {
        "display": "ActionsLineGraph",
        "formulas": null,
        "showLegend": false,
        "decimalPlaces": null,
        "yAxisScaleType": "linear",
        "showValuesOnSeries": false,
        "showPercentStackView": false,
        "aggregationAxisFormat": "numeric",
        "aggregationAxisPrefix": null,
        "aggregationAxisPostfix": null
      },
      "compareFilter": null,
      "samplingFactor": null,
      "breakdownFilter": null,
      "filterTestAccounts": true
    },
    "showHeader": true
  })
  tags = ["managed-by:terraform"]
  dashboard_ids = [posthog_dashboard.team_analytics_platform_key_metrics.id]
}

# Terraform configuration for PostHog insight
# Compatible with posthog provider v1.0
# Source insight ID: 5088513
# Short ID: DeafU0xe
import {
  to = posthog_insight.dashboards_created_from_template_unique_users
  id = "5088513"
}

resource "posthog_insight" "dashboards_created_from_template_unique_users" {
  name = "Dashboards created from template (unique users)"
  query_json = jsonencode({
    "kind": "InsightVizNode",
    "source": {
      "kind": "TrendsQuery",
      "series": [
        {
          "kind": "EventsNode",
          "math": "dau",
          "event": "dashboard created",
          "properties": [
            {
              "key": "from_template",
              "type": "event",
              "value": "true",
              "operator": "exact"
            }
          ],
          "custom_name": "Dashboard created from template (unique users)"
        },
        {
          "kind": "EventsNode",
          "math": "dau",
          "event": "dashboard created",
          "custom_name": "Dashboard created (unique users)"
        }
      ],
      "version": 2,
      "interval": "day",
      "dateRange": {
        "date_from": "-30d"
      },
      "properties": [],
      "trendsFilter": {
        "display": "ActionsLineGraph",
        "showLegend": true,
        "formulaNodes": [
          {
            "formula": "(A/B) * 100"
          }
        ],
        "yAxisScaleType": "linear",
        "showValuesOnSeries": false,
        "showPercentStackView": false,
        "aggregationAxisFormat": "percentage"
      },
      "filterTestAccounts": false
    }
  })
  tags = ["managed-by:terraform"]
  dashboard_ids = [posthog_dashboard.team_analytics_platform_key_metrics.id, 778670]
}

# Terraform configuration for PostHog insight
# Compatible with posthog provider v1.0
# Source insight ID: 5089292
# Short ID: lvR7dwxH
import {
  to = posthog_insight.created_subscriptions
  id = "5089292"
}

resource "posthog_insight" "created_subscriptions" {
  name = "Created subscriptions"
  query_json = jsonencode({
    "kind": "InsightVizNode",
    "source": {
      "kind": "TrendsQuery",
      "series": [
        {
          "kind": "EventsNode",
          "math": "total",
          "name": "dashboard subscription created",
          "event": "dashboard subscription created"
        },
        {
          "kind": "EventsNode",
          "math": "total",
          "name": "insight subscription created",
          "event": "insight subscription created"
        }
      ],
      "version": 2,
      "trendsFilter": {
        "showLegend": true
      }
    }
  })
  tags = ["managed-by:terraform"]
  dashboard_ids = [posthog_dashboard.team_analytics_platform_key_metrics.id]
}

# Terraform configuration for PostHog insight
# Compatible with posthog provider v1.0
# Source insight ID: 3582517
# Short ID: pgGH5Tf3
import {
  to = posthog_insight.export_successes_and_failures_us
  id = "3582517"
}

resource "posthog_insight" "export_successes_and_failures_us" {
  name = "Export Successes and Failures (US)"
  query_json = jsonencode({
    "kind": "InsightVizNode",
    "source": {
      "kind": "TrendsQuery",
      "series": [
        {
          "id": "postgres.posthog_exportedasset",
          "kind": "DataWarehouseNode",
          "math": "total",
          "name": "postgres.posthog_exportedasset",
          "id_field": "id",
          "table_name": "postgres.posthog_exportedasset",
          "custom_name": "Starts",
          "timestamp_field": "created_at",
          "distinct_id_field": "created_by_id"
        },
        {
          "id": "postgres.posthog_exportedasset",
          "kind": "DataWarehouseNode",
          "math": "total",
          "name": "postgres.posthog_exportedasset",
          "id_field": "id",
          "properties": [
            {
              "key": "export_context is not null or content_location is not null",
              "type": "hogql",
              "value": null
            }
          ],
          "table_name": "postgres.posthog_exportedasset",
          "custom_name": "Success",
          "timestamp_field": "created_at",
          "distinct_id_field": "created_by_id"
        },
        {
          "id": "postgres.posthog_exportedasset",
          "kind": "DataWarehouseNode",
          "math": "total",
          "name": "postgres.posthog_exportedasset",
          "id_field": "id",
          "properties": [
            {
              "key": "exception is not null",
              "type": "hogql",
              "value": null
            }
          ],
          "table_name": "postgres.posthog_exportedasset",
          "custom_name": "Caught Exceptions",
          "timestamp_field": "created_at",
          "distinct_id_field": "created_by_id"
        },
        {
          "id": "postgres.posthog_exportedasset",
          "kind": "DataWarehouseNode",
          "math": "total",
          "name": "postgres.posthog_exportedasset",
          "id_field": "id",
          "properties": [
            {
              "key": "exception is null and export_context is null and content_location is null and timestamp < now() - interval 10 minute",
              "type": "hogql",
              "value": null
            }
          ],
          "table_name": "postgres.posthog_exportedasset",
          "custom_name": "Uncaught Exceptions",
          "timestamp_field": "created_at",
          "distinct_id_field": "created_by_id"
        }
      ],
      "version": 2,
      "properties": [],
      "trendsFilter": {
        "formulaNodes": [
          {
            "formula": "B/A",
            "custom_name": "Success"
          },
          {
            "formula": "C/A",
            "custom_name": "Caught"
          },
          {
            "formula": "D/A",
            "custom_name": "Uncaught"
          }
        ],
        "yAxisScaleType": "log10",
        "showMultipleYAxes": false,
        "showValuesOnSeries": true,
        "aggregationAxisFormat": "percentage_scaled",
        "showAlertThresholdLines": true
      },
      "breakdownFilter": null
    }
  })
  tags = ["managed-by:terraform"]
  dashboard_ids = [posthog_dashboard.team_analytics_platform_key_metrics.id, 633001, 567706]
}

# Terraform configuration for PostHog insight
# Compatible with posthog provider v1.0
# Source insight ID: 5421410
# Short ID: o5s3JBdC
import {
  to = posthog_insight.export_successes_and_failures_eu
  id = "5421410"
}

resource "posthog_insight" "export_successes_and_failures_eu" {
  name = "Export Successes and Failures (EU)"
  query_json = jsonencode({
    "kind": "InsightVizNode",
    "source": {
      "kind": "TrendsQuery",
      "series": [
        {
          "id": "eu_posthog_exportedasset",
          "kind": "DataWarehouseNode",
          "math": "total",
          "name": "eu_posthog_exportedasset",
          "id_field": "id",
          "table_name": "eu_posthog_exportedasset",
          "custom_name": "Starts",
          "timestamp_field": "created_at",
          "distinct_id_field": "created_by_id"
        },
        {
          "id": "eu_posthog_exportedasset",
          "kind": "DataWarehouseNode",
          "math": "total",
          "name": "eu_posthog_exportedasset",
          "id_field": "id",
          "properties": [
            {
              "key": "export_context is not null or content_location is not null",
              "type": "hogql",
              "value": null
            }
          ],
          "table_name": "eu_posthog_exportedasset",
          "custom_name": "Success",
          "timestamp_field": "created_at",
          "distinct_id_field": "created_by_id"
        },
        {
          "id": "eu_posthog_exportedasset",
          "kind": "DataWarehouseNode",
          "math": "total",
          "name": "eu_posthog_exportedasset",
          "id_field": "id",
          "properties": [
            {
              "key": "exception is not null",
              "type": "hogql",
              "value": null
            }
          ],
          "table_name": "eu_posthog_exportedasset",
          "custom_name": "Caught Exceptions",
          "timestamp_field": "created_at",
          "distinct_id_field": "created_by_id"
        },
        {
          "id": "eu_posthog_exportedasset",
          "kind": "DataWarehouseNode",
          "math": "total",
          "name": "eu_posthog_exportedasset",
          "id_field": "id",
          "properties": [
            {
              "key": "exception is null and export_context is null and content_location is null and timestamp < now() - interval 10 minute",
              "type": "hogql",
              "value": null
            }
          ],
          "table_name": "eu_posthog_exportedasset",
          "custom_name": "Uncaught Exceptions",
          "timestamp_field": "created_at",
          "distinct_id_field": "created_by_id"
        }
      ],
      "version": 2,
      "properties": [],
      "trendsFilter": {
        "formulaNodes": [
          {
            "formula": "B/A",
            "custom_name": "Success"
          },
          {
            "formula": "C/A",
            "custom_name": "Caught"
          },
          {
            "formula": "D/A",
            "custom_name": "Uncaught"
          }
        ],
        "yAxisScaleType": "log10",
        "showMultipleYAxes": false,
        "showValuesOnSeries": true,
        "aggregationAxisFormat": "percentage_scaled",
        "showAlertThresholdLines": true
      },
      "breakdownFilter": null
    }
  })
  tags = ["managed-by:terraform"]
  dashboard_ids = [posthog_dashboard.team_analytics_platform_key_metrics.id]
}

# Terraform configuration for PostHog insight
# Compatible with posthog provider v1.0
# Source insight ID: 3901616
# Short ID: KUvN6RsQ
import {
  to = posthog_insight.usage_by_role
  id = "3901616"
}

resource "posthog_insight" "usage_by_role" {
  name = "Usage by role"
  query_json = jsonencode({
    "kind": "InsightVizNode",
    "source": {
      "kind": "TrendsQuery",
      "series": [
        {
          "id": "214129",
          "kind": "ActionsNode",
          "math": "total",
          "name": "[team-analytics-platform] Clicked New action in data management"
        }
      ],
      "version": 2,
      "interval": "week",
      "dateRange": {
        "date_to": null,
        "date_from": "-90d",
        "explicitDate": false
      },
      "trendsFilter": {
        "display": "ActionsAreaGraph"
      },
      "breakdownFilter": {
        "breakdowns": [
          {
            "type": "person",
            "property": "role_at_organization"
          }
        ]
      },
      "filterTestAccounts": true
    }
  })
  tags = ["managed-by:terraform"]
  dashboard_ids = [posthog_dashboard.team_analytics_platform_key_metrics.id]
}

# Terraform configuration for PostHog insight
# Compatible with posthog provider v1.0
# Source insight ID: 5088924
# Short ID: GhRIGhBU
import {
  to = posthog_insight.alert_creation
  id = "5088924"
}

resource "posthog_insight" "alert_creation" {
  name = "Alert creation"
  query_json = jsonencode({
    "kind": "InsightVizNode",
    "source": {
      "kind": "TrendsQuery",
      "series": [
        {
          "id": "postgres.posthog_alertconfiguration",
          "kind": "DataWarehouseNode",
          "math": "dau",
          "name": "postgres.posthog_alertconfiguration",
          "id_field": "id",
          "table_name": "postgres.posthog_alertconfiguration",
          "custom_name": "Unique users",
          "timestamp_field": "created_at",
          "distinct_id_field": "created_by_id"
        },
        {
          "id": "postgres.posthog_alertconfiguration",
          "kind": "DataWarehouseNode",
          "math": "total",
          "name": "postgres.posthog_alertconfiguration",
          "id_field": "id",
          "table_name": "postgres.posthog_alertconfiguration",
          "custom_name": "Total count",
          "timestamp_field": "created_at",
          "distinct_id_field": "created_by_id"
        }
      ],
      "version": 2,
      "interval": "day",
      "dateRange": {
        "date_to": null,
        "date_from": "-30d",
        "explicitDate": false
      },
      "properties": [],
      "trendsFilter": {
        "showLegend": true
      },
      "breakdownFilter": null
    }
  })
  tags = ["managed-by:terraform"]
  dashboard_ids = [posthog_dashboard.team_analytics_platform_key_metrics.id]
}

# Terraform configuration for PostHog insight
# Compatible with posthog provider v1.0
# Source insight ID: 5512297
# Short ID: pfwTATaa
import {
  to = posthog_insight.api_calls_originating_from_our_terraform_provider
  id = "5512297"
}

resource "posthog_insight" "api_calls_originating_from_our_terraform_provider" {
  name = "API calls originating from our Terraform Provider"
  query_json = jsonencode({
    "kind": "DataVisualizationNode",
    "source": {
      "kind": "HogQLQuery",
      "query": "SELECT \n    extract(properties.$user_agent, 'version: ([0-9\\\\.\\\\-a-zA-Z]+)') as version,\n    person.properties.email as email,\n    person.properties.org__name as organization,\n    count() as api_calls,\n    min(timestamp) as first_call,\n    max(timestamp) as last_call\nFROM events\nWHERE \n    properties.$user_agent LIKE '%terraform-provider%'\n    AND timestamp >= now() - INTERVAL 7 DAY\nGROUP BY version, email, organization\nORDER BY api_calls DESC"
    },
    "display": "ActionsTable",
    "chartSettings": {
      "xAxis": {
        "column": "first_call"
      },
      "yAxis": [
        {
          "column": "api_calls",
          "settings": {
            "formatting": {
              "prefix": "",
              "suffix": ""
            }
          }
        }
      ]
    },
    "tableSettings": {
      "columns": [
        {
          "column": "version",
          "settings": {
            "formatting": {
              "prefix": "",
              "suffix": ""
            }
          }
        },
        {
          "column": "email",
          "settings": {
            "formatting": {
              "prefix": "",
              "suffix": ""
            }
          }
        },
        {
          "column": "organization",
          "settings": {
            "formatting": {
              "prefix": "",
              "suffix": ""
            }
          }
        },
        {
          "column": "api_calls",
          "settings": {
            "formatting": {
              "prefix": "",
              "suffix": ""
            }
          }
        },
        {
          "column": "first_call",
          "settings": {
            "formatting": {
              "prefix": "",
              "suffix": ""
            }
          }
        },
        {
          "column": "last_call",
          "settings": {
            "formatting": {
              "prefix": "",
              "suffix": ""
            }
          }
        }
      ]
    }
  })
  tags = ["managed-by:terraform"]
  dashboard_ids = [posthog_dashboard.team_analytics_platform_key_metrics.id, 821321]
}
