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

locals {
  export_insight_regions = {
    us = {
      table_name         = "postgres.posthog_exportedasset"
      dashboard_ids      = [posthog_dashboard.team_analytics_platform_key_metrics.id, 633001, 567706]
      unknown_result_sql = "https://metabase.prod-us.posthog.dev/question/1838-analyse-unknown-exportedasset-exceptions"
    }
    eu = {
      table_name         = "eu_posthog_exportedasset"
      dashboard_ids      = [posthog_dashboard.team_analytics_platform_key_metrics.id]
      unknown_result_sql = "https://metabase.prod-eu.posthog.dev/question/565-analyse-unknown-exportedasset-exceptions"
    }
  }

  # Base query with placeholder - replace() substitutes the table name per region
  export_insight_base_query = jsonencode({
    "kind": "InsightVizNode",
    "source": {
      "kind": "TrendsQuery",
      "series": [
        {
          "id": "{{TABLE_NAME}}",
          "kind": "DataWarehouseNode",
          "math": "total",
          "name": "{{TABLE_NAME}}",
          "id_field": "id",
          "table_name": "{{TABLE_NAME}}",
          "custom_name": "Starts",
          "timestamp_field": "created_at",
          "distinct_id_field": "created_by_id"
        },
        {
          "id": "{{TABLE_NAME}}",
          "kind": "DataWarehouseNode",
          "math": "total",
          "name": "{{TABLE_NAME}}",
          "id_field": "id",
          "properties": [
            {
              "key": "export_context is not null or content_location is not null",
              "type": "hogql",
              "value": null
            }
          ],
          "table_name": "{{TABLE_NAME}}",
          "custom_name": "Success",
          "timestamp_field": "created_at",
          "distinct_id_field": "created_by_id"
        },
        {
          "id": "{{TABLE_NAME}}",
          "kind": "DataWarehouseNode",
          "math": "total",
          "name": "{{TABLE_NAME}}",
          "id_field": "id",
          "properties": [
            {
              "key": "exception is not null",
              "type": "hogql",
              "value": null
            }
          ],
          "table_name": "{{TABLE_NAME}}",
          "custom_name": "Caught Exceptions",
          "timestamp_field": "created_at",
          "distinct_id_field": "created_by_id"
        },
        {
          "id": "{{TABLE_NAME}}",
          "kind": "DataWarehouseNode",
          "math": "total",
          "name": "{{TABLE_NAME}}",
          "id_field": "id",
          "properties": [
            {
              "key": "failure_type = 'user'",
              "type": "hogql",
              "value": null
            }
          ],
          "table_name": "{{TABLE_NAME}}",
          "custom_name": "User failures",
          "timestamp_field": "created_at",
          "distinct_id_field": "created_by_id"
        },
        {
          "id": "{{TABLE_NAME}}",
          "kind": "DataWarehouseNode",
          "math": "total",
          "name": "{{TABLE_NAME}}",
          "id_field": "id",
          "properties": [
            {
              "key": "failure_type = 'system'",
              "type": "hogql",
              "value": null
            }
          ],
          "table_name": "{{TABLE_NAME}}",
          "custom_name": "System failures",
          "timestamp_field": "created_at",
          "distinct_id_field": "created_by_id"
        },
        {
          "id": "{{TABLE_NAME}}",
          "kind": "DataWarehouseNode",
          "math": "total",
          "name": "{{TABLE_NAME}}",
          "id_field": "id",
          "properties": [
            {
              "key": "failure_type = 'timeout_generation'",
              "type": "hogql",
              "value": null
            }
          ],
          "table_name": "{{TABLE_NAME}}",
          "custom_name": "Timeout failures",
          "timestamp_field": "created_at",
          "distinct_id_field": "created_by_id"
        },
        {
          "id": "{{TABLE_NAME}}",
          "kind": "DataWarehouseNode",
          "math": "total",
          "name": "{{TABLE_NAME}}",
          "id_field": "id",
          "properties": [
            {
              "key": "failure_type = 'unknown'",
              "type": "hogql",
              "value": null
            }
          ],
          "table_name": "{{TABLE_NAME}}",
          "custom_name": "Unknown failures",
          "timestamp_field": "created_at",
          "distinct_id_field": "created_by_id"
        },
        {
          "id": "{{TABLE_NAME}}",
          "kind": "DataWarehouseNode",
          "math": "total",
          "name": "{{TABLE_NAME}}",
          "id_field": "id",
          "properties": [
            {
              "key": "exception is null and export_context is null and content_location is null and timestamp < now() - interval 10 minute",
              "type": "hogql",
              "value": null
            }
          ],
          "table_name": "{{TABLE_NAME}}",
          "custom_name": "Uncaught Exceptions",
          "timestamp_field": "created_at",
          "distinct_id_field": "created_by_id"
        }
      ],
      "version": 2,
      "properties": [],
      "trendsFilter": {
        "display": "ActionsLineGraph",
        "formulaNodes": [
          { "formula": "B/A", "custom_name": "Success" },
          { "formula": "C/A", "custom_name": "Caught" },
          { "formula": "H/A", "custom_name": "Uncaught" },
          { "formula": "D/A", "custom_name": "User Errors" },
          { "formula": "E/A", "custom_name": "System Errors" },
          { "formula": "F/A", "custom_name": "Timeout Errors" },
          { "formula": "G/A", "custom_name": "Unknown Errors" }
        ],
        "decimalPlaces": 4,
        "yAxisScaleType": "log10",
        "showMultipleYAxes": false,
        "showValuesOnSeries": true,
        "aggregationAxisFormat": "percentage_scaled",
        "showAlertThresholdLines": true
      },
      "breakdownFilter": null
    }
  })
}

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

resource "posthog_insight" "export_successes_and_failures" {
  for_each = local.export_insight_regions

  name          = "Export Successes and Failures (${upper(each.key)})"
  query_json    = replace(local.export_insight_base_query, "{{TABLE_NAME}}", each.value.table_name)
  tags          = ["managed-by:terraform"]
  dashboard_ids = each.value.dashboard_ids
  description   = "More details about the unknown errors can be found here: ${each.value.unknown_result_sql}"
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

# Terraform configuration for PostHog insight
# Compatible with posthog provider v1.0.6
# Source insight ID: 7067184
# Short ID: a5XEngMW

import {
  to = posthog_insight.dashboard_created_unique_users_by_event_s_source
  id = "2/7067184"
}

resource "posthog_insight" "dashboard_created_unique_users_by_event_s_source" {
  derived_name = "dashboard created unique users by event's source"
  query_json = jsonencode({
    "kind": "InsightVizNode",
    "source": {
      "kind": "TrendsQuery",
      "series": [
        {
          "kind": "EventsNode",
          "math": "dau",
          "name": "dashboard created",
          "event": "dashboard created"
        }
      ],
      "version": 2,
      "trendsFilter": {
        "display": "ActionsAreaGraph"
      },
      "breakdownFilter": {
        "breakdowns": [
          {
            "type": "event",
            "property": "source"
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
# Compatible with posthog provider v1.0.6
# Source insight ID: 6984945
# Short ID: US61ntVv

import {
  to = posthog_insight.alert_failures_by_exception_type_aggregated
  id = "2/6984945"
}

resource "posthog_insight" "alert_failures_by_exception_type_aggregated" {
  name = "Alert failures by exception type (aggregated)"
  description = "Failures grouped by exception type with alert IDs normalized, showing the core issues affecting alerts"
  query_json = jsonencode({
    "kind": "DataTableNode",
    "source": {
      "kind": "HogQLQuery",
      "query": "SELECT \n  CASE \n    WHEN properties.traceback LIKE '%RuntimeError: No results found for insight with alert id =%' \n      THEN 'RuntimeError: No results found for insight'\n    WHEN properties.traceback LIKE '%ValueError: Relative alerts not supported for non time series trends%' \n      THEN 'ValueError: Relative alerts not supported for non time series trends'\n    WHEN properties.traceback LIKE '%UnboundLocalError: cannot access local variable%config%' \n      THEN 'UnboundLocalError: cannot access local variable config'\n    WHEN properties.traceback LIKE '%pydantic_core._pydantic_core.ValidationError%AlertCondition%type%Field required%' \n      THEN 'ValidationError: AlertCondition missing required field \"type\"'\n    WHEN properties.traceback LIKE '%QueryTimeoutError%' OR properties.traceback LIKE '%timeout%'\n      THEN 'Query timeout error'\n    WHEN properties.traceback LIKE '%PermissionError%' OR properties.traceback LIKE '%permission%'\n      THEN 'Permission error'\n    WHEN properties.traceback LIKE '%KeyError%' \n      THEN 'KeyError: Missing expected key'\n    WHEN properties.traceback LIKE '%AttributeError%' \n      THEN 'AttributeError: Missing attribute'\n    WHEN properties.traceback LIKE '%IndexError%' \n      THEN 'IndexError: List index out of range'\n    WHEN properties.traceback LIKE '%TypeError%' \n      THEN 'TypeError: Type mismatch'\n    WHEN properties.traceback IS NULL OR properties.traceback = ''\n      THEN 'Unknown (no traceback)'\n    ELSE 'Other exception type'\n  END AS exception_type,\n  count() AS failure_count,\n  count() * 100.0 / sum(count()) OVER () AS percentage_of_failures,\n  uniq(properties.alert_id) AS unique_alerts_affected,\n  uniq(properties.team_id) AS unique_teams_affected,\n  min(timestamp) AS first_occurrence,\n  max(timestamp) AS last_occurrence\nFROM events\nWHERE event = 'alert check failed'\n  AND timestamp >= now() - INTERVAL 30 DAY\n  AND timestamp < now()\nGROUP BY exception_type\nORDER BY failure_count DESC\nLIMIT 100"
    }
  })
  tags = ["managed-by:terraform"]
  dashboard_ids = [1142938, 821321, posthog_dashboard.team_analytics_platform_key_metrics.id, 1294240]
}
