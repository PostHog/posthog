Create a threshold-based alert on log streams. The alert periodically counts log entries matching the given filters and fires when the count crosses the threshold. Maximum 20 alerts per project.

# filters field

The `filters` object controls which log entries are counted. It must contain at least one of:

- `serviceNames` — list of service name strings (e.g. `["ingestion-events", "billing"]`)
- `severityLevels` — list of severity strings: `trace`, `debug`, `info`, `warn`, `error`, `fatal`
- `filterGroup` — a `PropertyGroupFilter` object for message-body or attribute matching (see below)

## filterGroup format

`filterGroup` uses a **two-level nested structure** — not a flat array. The outer object is a `PropertyGroupFilter`, whose `values` contains `PropertyGroupFilterValue` objects, each of which holds the actual conditions.

```text
PropertyGroupFilter
  └── type: "AND" | "OR"
  └── values: PropertyGroupFilterValue[]
        └── type: "AND" | "OR"
        └── values: Condition[]
              └── key, type, operator, value
```

### Condition types

Individual conditions use `type: "log_entry"` for log body/message matching:

| type                     | key           | use for                                               |
| ------------------------ | ------------- | ----------------------------------------------------- |
| `log_entry`              | `message`     | log body / message text                               |
| `log_attribute`          | attribute key | log-level attributes (e.g. `http.status_code`)        |
| `log_resource_attribute` | attribute key | resource-level attributes (e.g. `k8s.container.name`) |

**Important:** Use `type: "log_entry"` (not `type: "log"`) for message body filters. Using `type: "log"` will cause a `ValidationError` at alert evaluation time.

### Supported operators

- String: `exact`, `is_not`, `icontains`, `not_icontains`, `regex`, `not_regex`
- Numeric: `exact`, `gt`, `lt`
- Existence: `is_set`, `is_not_set`

# Examples

## Alert on error severity only (no filterGroup needed)

```json
{
  "name": "My service: error spike",
  "filters": {
    "serviceNames": ["my-service"],
    "severityLevels": ["error", "fatal"]
  },
  "threshold_count": 10,
  "threshold_operator": "above",
  "window_minutes": 5
}
```

## Alert on a specific log message pattern

```json
{
  "name": "ingestion-events: kafka produce error",
  "filters": {
    "serviceNames": ["ingestion-events"],
    "filterGroup": {
      "type": "AND",
      "values": [
        {
          "type": "AND",
          "values": [
            {
              "key": "message",
              "type": "log_entry",
              "operator": "icontains",
              "value": "kafka_produce_error"
            }
          ]
        }
      ]
    }
  },
  "threshold_count": 5,
  "threshold_operator": "above",
  "window_minutes": 5
}
```

## Alert combining service, severity, and message filter

```json
{
  "name": "billing: task not found",
  "filters": {
    "serviceNames": ["billing"],
    "severityLevels": ["error"],
    "filterGroup": {
      "type": "AND",
      "values": [
        {
          "type": "AND",
          "values": [
            {
              "key": "message",
              "type": "log_entry",
              "operator": "icontains",
              "value": "task_not_found"
            }
          ]
        }
      ]
    }
  },
  "threshold_count": 3,
  "threshold_operator": "above",
  "window_minutes": 5
}
```

# window_minutes allowed values

Only these values are accepted: `5`, `10`, `15`, `30`, `60`.

# threshold_operator

- `above` — fires when count **exceeds** the threshold (default, use for error rate alerts)
- `below` — fires when count **drops below** the threshold (use for heartbeat / liveness alerts)
