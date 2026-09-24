# Step reference

Every helper returns a value. `path` places values in order, and the compiler derives the rest: action ids, edges, the trigger node and the exit node. Read this file when you need an option, a cap, or the shape a step emits.

## Ids

- An action id is the slug of the step name: lowercase, with every run of other characters replaced by one underscore. `Wait a day` becomes `wait_a_day`.
- A rename changes the id. In-flight runs are keyed on the id, so pass `id` on a step to keep the id through a rename.
- One step value placed twice gets a numbered id on its second placement in graph order, for example `cool_off_2`. Two different steps with one slug are refused (`duplicate_action_id`).
- `trigger_node` and `exit_node` are reserved. A step name is at most 400 characters and an id at most 200.

## Triggers

| Helper                                                 | Emits                              | Notes                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| ------------------------------------------------------ | ---------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `onEvent({ event, properties?, name?, description? })` | trigger action, `type: 'event'`    | Fires on every occurrence of the event. Each run has a person. `properties` holds conditions from `eventProperty`, `person` or `group`.                                                                                                                                                                                                                                                                                                                           |
| `onSchedule({ name?, description? })`                  | trigger action, `type: 'schedule'` | A run has no person. `{person.properties.x}` resolves to nothing. A branch arm that reads a person or group property never matches, so every run takes the fall-through. The cadence is not part of the file, so PostHog owns it: add the schedule in PostHog after the first push. PostHog accepts schedule changes on a workflow managed by code, and a push leaves the schedule as it is. Until a schedule exists, the workflow does not run, `active` or not. |
| `trigger(config, { name?, description? })`             | trigger action, `config` unchanged | Use when a copied workflow starts from a trigger type that has no typed helper yet. The config is emitted verbatim, so copy the shape from a stored workflow with the Copy code button or with the `workflows-get-code` MCP tool when it is available.                                                                                                                                                                                                            |

## Conditions

`person(key, operator, value?)`, `eventProperty(key, operator, value?)` and `group(groupTypeIndex, key, operator, value?)` each return one condition. All conditions in one `when` list must hold.

- `groupTypeIndex` is the PostHog group type index, for example `0` for the first group type.
- Conditions take one value or a list. Several values match any of them.
- `is_set` and `is_not_set` take no value.
- Operators: `exact`, `is_not`, `icontains`, `not_icontains`, `starts_with`, `not_starts_with`, `ends_with`, `not_ends_with`, `regex`, `not_regex`, `gt`, `gte`, `lt`, `lte`, `is_set`, `is_not_set`, `is_date_exact`, `is_date_before`, `is_date_after`, `between`, `not_between`, `min`, `max`, `in`, `not_in`, `is_cleaned_path_exact`, `flag_evaluates_to`, `semver_eq`, `semver_neq`, `semver_gt`, `semver_gte`, `semver_lt`, `semver_lte`, `semver_tilde`, `semver_caret`, `semver_wildcard`, `icontains_multi`, `not_icontains_multi`.
- `eventProperty` belongs in the trigger only. PostHog refuses an event filter in a branch.

## `delay(duration, { name, id?, description? })`

- `duration` is a number and a unit: `s`, `m`, `h` or `d`. Decimals are allowed: `1.5h`.
- PostHog caps the amount per unit at 60s, 60m, 24h and 30d and clamps silently, so `emit` refuses a wait over the cap (`duration_over_unit_cap`). Write `1.5h`, not `90m`. The longest wait is `30d`; split a longer one across two steps.
- A zero or malformed wait is `invalid_duration`.
- Emits a `delay` action with `delay_duration`.

## `branch({ name, id?, description?, branches })`

- `branches` holds one arm or more: `{ name, when: [condition, ...], then: path(...) }`. PostHog tries the arms in order and takes the first whose conditions all hold.
- A person who matches no arm follows the fall-through, which is the step after the branch, or the exit. Every arm's path rejoins there too.
- `when` needs at least one condition and `then` at least one step. An empty `then` is `empty_path`.
- Emits a `conditional_branch` action. Each arm becomes a `branch` edge with its index, and the fall-through is a `continue` edge.

## `email({ name, id?, description?, from, to, subject, text, html, preheader? })`

- `from.integrationIds` holds one to ten ids of the project's email integrations. Find them in the project under Workflows, Channels. With several ids, PostHog picks one per run.
- `from.email` is optional. A literal must be one address on the verified domain of every sender. Hog templating is passed through. Omit it to send from the integration's own address. `from.name` is the sender name shown beside the address.
- `to` is usually `{person.properties.email}`.
- The content is inline. There is no way to reference a saved library template, because PostHog copies a referenced template into the workflow when it saves, and every later push would then report a change.
- `text` is the plain-text body every client can show. `html` also becomes the design the visual editor opens, as one custom HTML block.
- An email step takes no credential, so a `secret` anywhere in it is `nested_secret`. Other refusals: `invalid_email_sender`, `invalid_sender_address`.
- Emits a `function_email` action on `template-email`.

## `webhook({ name, id?, description?, url, method?, body?, headers?, signingSecret? })`

- `method` defaults to `POST`. `body` defaults to `{}` and its values may hold hog templating. `headers` adds request headers.
- `signingSecret` takes `secret('NAME')` and becomes the `signing_secret` input. Omit it only when the endpoint needs no proof the call came from PostHog.
- Emits a `function` action on `template-webhook`.

## `fn({ name, id?, description?, templateId, inputs })`

- Runs any PostHog destination template by id, for example `template-slack`. This is the route to every template the typed helpers do not cover.
- The compiler does not know a template's input schema, so PostHog validates the inputs when the push lands (`http_400` names the step). Find a template id and its inputs with the `cdp-function-templates-list` and `cdp-function-templates-retrieve` endpoints rather than guessing.
- Each input is wrapped as `{ value: ... }` in the definition, which is what makes hog templating resolve at run time.
- Pass a `secret` as the value of a whole input.

## `step({ type, name, id?, description?, config, filters?, on_error?, output_variable?, branches? })`

- Emits a pass-through action with the `type` and `config` you give it. Use it when a copied workflow uses an action type that has no typed helper yet, such as `function_sms`, `function_push`, `wait_until_condition`, `wait_until_time_window` or `random_cohort_branch`.
- Prefer a typed helper when one exists. A pass-through `config` is emitted unchanged, so you must know the stored shape. Copy an existing workflow with the Copy code button or use the `workflows-get-code` MCP tool when it is available.
- `type` cannot be `trigger` or `exit` (`reserved_action_type`). Use the workflow `on` field and `exit` field instead.
- `filters`, `on_error` and `output_variable` are stored on the action when set.
- `branches` emits one branch edge to each path in order, plus the fall-through `continue` edge to the next step. Use it only for action types whose branch edges are part of the graph.
- A `secret` passed as a whole entry of `config.inputs` resolves the same way it does for `fn`. When `config.inputs` is absent, this helper does not resolve secrets. A nested secret is `nested_secret`.

## `secret(envName)`

- Names an environment variable. The name travels in the file, the value never does.
- `emit` reads the variable and sends the value on every push. A rotation reaches PostHog on the next push. When nothing else changed, that push needs `--force`, because the comparison skips secret inputs.
- `push` refuses an unset or empty variable (`missing_secret`). `check` substitutes the placeholder `(resolved at push)` so the file can emit, but it compares a secret input only when the real environment variable is set.
- A secret inside a larger value is `nested_secret`: only the variable name would reach PostHog.
- `isSecretRef(value)` reports whether a value came from `secret`, for example to list the variables a file needs.

## Hog templating

Values in `to`, `body`, `inputs` and email fields may hold templating that PostHog resolves at run time: `{person.properties.email}`, `{person.properties.plan}`, `{event.distinct_id}`. A value that holds a brace is passed through unchecked.

## Workflow options

| Option          | Default            | Rule                                                                                                                                                                                                                                                                                                                                                                   |
| --------------- | ------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `key`           | required           | Unique in the project. Letters, digits, hyphens and underscores only. The key must be 400 characters or fewer. Fixed once pushed: a renamed key orphans the old workflow and creates a new one. A key that starts with `replace-me` is refused.                                                                                                                        |
| `name`          | required           | Free to change. The identity is the key.                                                                                                                                                                                                                                                                                                                               |
| `description`   | `''`               | Free text.                                                                                                                                                                                                                                                                                                                                                             |
| `status`        | omitted            | `init` writes `'draft'` into the starter. While the field is set, every push that writes sets the status to it, even after someone turns the workflow on in PostHog. Omit it so PostHog owns the status: a new workflow starts as a draft, and a push never changes status when the file omits it. Set it only when code must control `draft`, `active` or `archived`. |
| `exitCondition` | `exit_only_at_end` | Or `exit_on_trigger_not_matched`.                                                                                                                                                                                                                                                                                                                                      |
| `variables`     | `[]`               | `{ key, type: string, number or boolean, default, label? }`. Every default is a string, also for a number or a boolean. Keys are unique. The list is capped at 5120 bytes.                                                                                                                                                                                             |
| `on`            | required           | `onEvent(...)`, `onSchedule(...)` or `trigger(...)`.                                                                                                                                                                                                                                                                                                                   |
| `steps`         | required           | `path(...)` with at least one step.                                                                                                                                                                                                                                                                                                                                    |
| `exit`          | required           | `{ reason, name?, description? }`. `reason` is the label PostHog records when a run finishes.                                                                                                                                                                                                                                                                          |

`workflow(...)` returns `{ key, emit }`. `emit({ env? })` resolves every secret, checks every rule and returns `{ definition, secretInputs }`. An `env` passed in replaces `process.env`. Call it to see exactly what a push sends.

## The definition

`actions` holds the trigger first, one action per placement, then the exit. `edges` holds `continue` edges and `branch` edges with an index. The file never writes `bytecode`, `trigger`, `version`, `billable_action_types` or a `source` object: PostHog computes those or the CLI supplies source fields during push.
