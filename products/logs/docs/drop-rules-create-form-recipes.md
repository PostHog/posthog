# Drop rules — “New drop rule” form recipes

Use **Logs → Configuration → Drop rules → New drop rule**. Fields appear **top to bottom** as in the UI.

**Priority** is not on this form: new rules get an order from the API; change order from the rules list / reorder API if you need a specific run order.

---

## Fields everyone sees (every recipe)

| Field                                      | What to do                                                                                                             |
| ------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------- |
| **Name**                                   | Use the recipe’s suggested name (or your own).                                                                         |
| **Enabled**                                | On unless you are drafting.                                                                                            |
| **What should this rule do?**              | Pick the recipe’s option (only on **create**).                                                                         |
| **Scope: service name (optional)**         | Recipe says **empty** or a **copy-paste service name** (`service.name` on the log).                                    |
| **Limit rule to matching path (optional)** | Recipe says **empty** or a **regex** on the _automatic path_ (first of `url.path`, `http.path`, `http.route`, `path`). |

Then the form branches on rule type.

---

## Path drop recipes (`What should this rule do?` → **Drop when matched (regex on path or attribute)**)

### 1) Global path drop (any service)

| Field                       | Value                                                       |
| --------------------------- | ----------------------------------------------------------- |
| Name                        | `Drop path /healthz (global)`                               |
| What should this rule do?   | **Drop when matched (regex on path or attribute)**          |
| Scope: service name         | _(empty)_                                                   |
| Limit rule to matching path | _(empty)_                                                   |
| Drop patterns match on      | **Automatic path (http.route, url.path, …)**                |
| Patterns to drop            | `/healthz` _(one regex per line; any line matching → drop)_ |

---

### 2) Same drop, one service only

| Field                       | Value                                   |
| --------------------------- | --------------------------------------- |
| Name                        | `Drop path /healthz (checkout only)`    |
| What should this rule do?   | **Drop when matched …**                 |
| Scope: service name         | `checkout-svc` _(exact `service.name`)_ |
| Limit rule to matching path | _(empty)_                               |
| Drop patterns match on      | **Automatic path**                      |
| Patterns to drop            | `/healthz`                              |

---

### 3) Only under a path prefix (limit + drop)

| Field                       | Value                                                                         |
| --------------------------- | ----------------------------------------------------------------------------- |
| Name                        | `Drop noisy routes under /api/internal/`                                      |
| What should this rule do?   | **Drop when matched …**                                                       |
| Scope: service name         | _(empty)_                                                                     |
| Limit rule to matching path | `^/api/internal/`                                                             |
| Drop patterns match on      | **Automatic path**                                                            |
| Patterns to drop            | `/debug` _(matches as substring on full path, e.g. `/api/internal/v1/debug`)_ |

Logs whose automatic path **does not** match `^/api/internal/` never see this rule.

---

### 4) Drop by one attribute (not URL path)

| Field                       | Value                                       |
| --------------------------- | ------------------------------------------- |
| Name                        | `Drop when env is staging`                  |
| What should this rule do?   | **Drop when matched …**                     |
| Scope: service name         | _(empty or narrow to one service)_          |
| Limit rule to matching path | _(usually empty)_                           |
| Drop patterns match on      | **One log attribute**                       |
| Log attribute key           | `deployment.environment` _(exact OTel key)_ |
| Patterns to drop            | `^staging$`                                 |

---

### 5) OR several patterns (any match drops)

| Field                       | Value                                  |
| --------------------------- | -------------------------------------- |
| Name                        | `Drop health or metrics paths`         |
| What should this rule do?   | **Drop when matched …**                |
| Scope: service name         | _(empty)_                              |
| Limit rule to matching path | _(empty)_                              |
| Drop patterns match on      | **Automatic path**                     |
| Patterns to drop            | _(one per line)_ `/healthz` `/metrics` |

---

## Severity recipes (`What should this rule do?` → **Drop by severity**)

**Per severity level:** for each row (**Debug**, **Info**, **Warn**, **Error**) choose **Keep**, **Drop (not stored)**, or **Sample (keep some)**. If **Sample**, set **Keep fraction** `0`–`1` (e.g. `0.25` ≈ 25% kept).

**Always keep (optional):** only for recipes that need them.

---

### 6) Drop all INFO; keep other levels

| Field                       | Value                                       |
| --------------------------- | ------------------------------------------- |
| Name                        | `Drop all INFO lines in scope`              |
| What should this rule do?   | **Drop by severity**                        |
| Scope: service name         | _(empty = all services, or one service)_    |
| Limit rule to matching path | _(empty or a prefix regex)_                 |
| Debug                       | **Keep**                                    |
| Info                        | **Drop (not stored)**                       |
| Warn                        | **Keep**                                    |
| Error                       | **Keep**                                    |
| Always keep                 | leave **HTTP status** and **Latency** empty |

---

### 7) Sample INFO at 50% (deterministic per trace when trace id exists)

| Field                     | Value                                        |
| ------------------------- | -------------------------------------------- |
| Name                      | `Sample INFO at 50%`                         |
| What should this rule do? | **Drop by severity**                         |
| Scope / limit path        | as needed                                    |
| Debug                     | **Keep**                                     |
| Info                      | **Sample (keep some)** — Keep fraction `0.5` |
| Warn                      | **Keep**                                     |
| Error                     | **Keep**                                     |
| Always keep               | _(empty)_                                    |

---

### 8) “Sample” but effectively drop all INFO (rate 0)

| Field | Value                                      |
| ----- | ------------------------------------------ |
| Name  | `Drop all INFO via sample rate 0`          |
| Info  | **Sample (keep some)** — Keep fraction `0` |

---

### 9) “Sample” but effectively keep all INFO (rate 1)

| Field | Value                                      |
| ----- | ------------------------------------------ |
| Name  | `Keep all INFO via sample rate 1`          |
| Info  | **Sample (keep some)** — Keep fraction `1` |

---

### 10) Drop INFO except high HTTP status

| Field                     | Value                                 |
| ------------------------- | ------------------------------------- |
| Name                      | `Drop INFO unless HTTP status >= 500` |
| What should this rule do? | **Drop by severity**                  |
| Debug / Warn / Error      | **Keep** (unless you want otherwise)  |
| Info                      | **Drop (not stored)**                 |
| HTTP status >=            | `500`                                 |
| Latency greater than (ms) | _(empty)_                             |

Needs `http.status_code` or `http.response.status_code` on the log for the exception to apply.

---

### 11) Drop INFO except slow requests

| Field                     | Value                               |
| ------------------------- | ----------------------------------- |
| Name                      | `Drop INFO unless duration > 100ms` |
| Info                      | **Drop (not stored)**               |
| HTTP status >=            | _(empty)_                           |
| Latency greater than (ms) | `100`                               |

Uses `http.server.duration_ms` or `duration_ms` when present.

---

## Not on this form (worker / API only today)

- **`scope_attribute_filters`** on the rule — not in the create/edit form; not evaluated in the Node sampling worker as of this writing.
- **`rate_limit`** rule type — reserved; not in the form.

---

## Quick matrix (same ideas as `nodejs/src/logs-ingestion/drop-rules-matrix-probe-curl.sh`)

After saving, use the script’s stderr block for API-shaped JSON and probe rows keyed by `ph.probe.suite = drop_rules_matrix`.

---

## Minimal smoke (4 rules)

Use **`nodejs/src/logs-ingestion/drop-rules-smoke-probe-curl.sh`**. It prints the exact four rules to stderr when you run it.

| #   | Name (suggested)                  | Type              | Service scope           | What to set                                                                                                                            |
| --- | --------------------------------- | ----------------- | ----------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | smoke path drop                   | Drop when matched | `smoke-path`            | Automatic path · patterns: `/__smoke/drop`                                                                                             |
| 2   | smoke attribute drop              | Drop when matched | `smoke-attr`            | Attribute `ph.smoke.tag` · patterns: `bad` (substring; see smoke script header — `^bad$` misses JSON-encoded values from capture-logs) |
| 3   | smoke severity drop all INFO      | Drop by severity  | `smoke-sev-info-drop`   | DEBUG keep, INFO drop, WARN/ERROR keep                                                                                                 |
| 4   | smoke severity sample INFO rate 0 | Drop by severity  | `smoke-sev-info-sample` | DEBUG keep, INFO **sample** rate **`0`**, WARN/ERROR keep (deterministic; proves sample path)                                          |

**Pass:** Logs filter `ph.probe.suite = drop_rules_smoke` and `ph.probe.expect = KEEP` → **4** rows; `ph.probe.expect = DROP` → **0** rows.
