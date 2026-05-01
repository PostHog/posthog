# Spec: Claude Managed Agents dispatch for workflows

Status: draft
Owner: team-workflows
Branch: `claude/plan-managed-agents-workflows-VHesG`

## Summary

Add a new dispatch in the workflows product that creates a session against a Claude
[Managed Agent](https://platform.claude.com/docs/en/managed-agents/overview) when a
workflow node fires. Operators select the agent, environment, and (optional) vault
credentials to attach. Backed by a new `anthropic` integration that holds an
Anthropic API key.

## Goals

- Workflow authors can drop a "Run Claude managed agent" node into any workflow.
- Configuration is a 4-field form: integration, agent, environment, vault_ids
  (multi-select), kickoff message.
- The dispatch creates a session and returns the session ID into a workflow variable.
- API keys are stored encrypted alongside other integrations and never leave the
  backend.
- Agents/environments/vaults are read from the customer's Anthropic workspace at
  configuration time — they are not created by PostHog.

## Non-goals (v1)

- Streaming agent output back into the workflow. Sessions are fire-and-forget; the
  workflow records the session ID and ends.
- Creating or updating agents/environments/vaults from PostHog. Those are managed
  upstream (via the `ant` CLI or directly against the Managed Agents API).
- Handling `tool_confirmation` round-trips, custom tools, or interactive sessions.
- Wiring agent output back into PostHog as events or notifications.
- Multi-key support per integration. One API key per `Integration` row.

## User-facing UX

### Connecting the integration

A new "Anthropic" entry in the integrations list. Form fields:

- API key (stored in `sensitive_config.api_key`, encrypted)
- Optional workspace label (display only, stored in `config.workspace_label`)

On submit the backend calls `client.beta.agents.list(limit=1)` to validate the key,
then persists the integration. The `integration_id` is the workspace ID returned by
the API (or a hash of the key if no stable workspace ID is available).

### Configuring a node

In the workflow editor, the "Claude" category contains one node: "Run Claude managed
agent". Selecting it opens a config form with:

| Field           | Type                | Required | Notes                                               |
| --------------- | ------------------- | -------- | --------------------------------------------------- |
| Anthropic       | `integration`       | yes      | Filters to `kind: 'anthropic'`                      |
| Agent           | `integration_field` | yes      | Single-select; populated from `agents.list()`       |
| Environment     | `integration_field` | yes      | Single-select; populated from `environments.list()` |
| Vaults          | `integration_field` | no       | Multi-select; populated from `vaults.list()`        |
| Initial message | `string`            | yes      | Hog template; default uses event properties         |

The form is rendered by the existing `CyclotronJobInputs` component. The three
dynamic dropdowns are rebuilt against the existing `integration_field` pattern (see
the Linear team selector at
`frontend/src/lib/components/CyclotronJob/integrations/CyclotronJobInputIntegrationField.tsx:148`).

### Output

The node sets `output_variable.session = { id, status, environment_id, agent }`,
spread into the workflow variables. Downstream nodes can read `vars.session.id`.

## Architecture

```text
┌──────────────────────────────────────────────────────────────────┐
│ posthog/                                                         │
│  ├─ models/integration.py        +ANTHROPIC kind                 │
│  │                               +AnthropicIntegration class     │
│  └─ api/integration.py           +anthropic_agents endpoint      │
│                                  +anthropic_environments endpoint│
│                                  +anthropic_vaults endpoint      │
└──────────────────────────────────────────────────────────────────┘
                              ▲
                              │ REST (admin/setup time)
                              │
┌─────────────────────────────┴────────────────────────────────────┐
│ frontend/                                                        │
│  └─ CyclotronJobInputIntegrationField.tsx                        │
│        +case 'anthropic_agent'                                   │
│        +case 'anthropic_environment'                             │
│        +case 'anthropic_vaults' (multi-select)                   │
│                                                                  │
│ products/workflows/frontend/.../registry/actions/                │
│  └─ anthropic.ts          register "Claude" category             │
└──────────────────────────────────────────────────────────────────┘
                              ▲
                              │ workflow runtime
                              │
┌─────────────────────────────┴────────────────────────────────────┐
│ nodejs/src/cdp/                                                  │
│  ├─ templates/_destinations/posthog_workflows/                   │
│  │     claude-managed-agent.template.ts                          │
│  └─ async-functions/claude.ts                                    │
│        registerAsyncFunction('claudeCreateSession', …)           │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    POST https://api.anthropic.com/v1/sessions
                    (managed-agents-2026-04-01 beta header)
```

## Data model changes

### `Integration.IntegrationKind`

Add:

```python
ANTHROPIC = "anthropic"
```

(`posthog/models/integration.py:144-178`)

### Migration

Standard Django migration extending the `kind` field's choices. No DDL — `kind` is
a free `CharField(max_length=32, choices=…)`. Migration generated via `manage.py
makemigrations posthog`.

### `AnthropicIntegration` class

New class in `posthog/models/integration.py` (model after `TwilioIntegration` at
line 2861). Responsibilities:

- `__init__`: assert `kind == 'anthropic'`, build a cached `anthropic.Anthropic`
  SDK client from `sensitive_config.api_key`.
- `validate_key()`: call `client.beta.agents.list(limit=1)` — surface 401/403 as
  `ValidationError`.
- `list_agents()` → `[{id, name, version, description}]`
- `list_environments()` → `[{id, name}]`
- `list_vaults()` → `[{id, display_name}]`
- `integration_from_key(api_key, workspace_label)` → factory matching the Twilio
  pattern (`integration.py:2882`).

`config`:

```json
{ "workspace_label": "Acme prod" }
```

`sensitive_config`:

```json
{ "api_key": "sk-ant-…" }
```

`integration_id`: workspace ID from the API, or a SHA256 prefix of the key as a
fallback (so the unique constraint
`(team, kind, integration_id)` still works).

## API changes

### Existing viewset: `posthog/api/integration.py`

Three new `@action` methods on `IntegrationViewSet`, mirroring `linear_teams`
(`integration.py:886`):

```python
@action(methods=["GET"], detail=True, url_path="anthropic_agents")
def anthropic_agents(self, request, *args, **kwargs):
    instance = self.get_object()
    return Response({"agents": AnthropicIntegration(instance).list_agents()})

@action(methods=["GET"], detail=True, url_path="anthropic_environments")
def anthropic_environments(self, request, *args, **kwargs):
    instance = self.get_object()
    return Response({"environments": AnthropicIntegration(instance).list_environments()})

@action(methods=["GET"], detail=True, url_path="anthropic_vaults")
def anthropic_vaults(self, request, *args, **kwargs):
    instance = self.get_object()
    return Response({"vaults": AnthropicIntegration(instance).list_vaults()})
```

All three require auth and route through the existing team-scoping logic.

### Creation endpoint

Extend the integration `create()` serializer (`integration.py` around line 281) to
handle `kind == "anthropic"`: read `api_key` and optional `workspace_label`, build
the integration via `AnthropicIntegration.integration_from_key(...)`.

## Frontend changes

### Integration field renderer

`frontend/src/lib/components/CyclotronJob/integrations/CyclotronJobInputIntegrationField.tsx`
— add three `if` branches following the `linear_team` pattern (line 148):

```ts
if (schema.integration_field === 'anthropic_agent') {
  /* agents endpoint */
}
if (schema.integration_field === 'anthropic_environment') {
  /* envs endpoint */
}
if (schema.integration_field === 'anthropic_vaults') {
  /* vaults; multiple: true */
}
```

The `vaults` case needs `multiple: true`. Verify the existing `IntegrationField`
component supports a multi-select mode; if not, the small extension is part of this
feature.

### Workflows action category

New file `products/workflows/frontend/Workflows/hogflows/registry/actions/anthropic.ts`:

```ts
import { IconClaude } from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'
import { registerActionNodeCategory } from './actionNodeRegistry'

registerActionNodeCategory({
  label: 'Claude',
  featureFlag: FEATURE_FLAGS.WORKFLOWS_CLAUDE_AGENTS,
  nodes: [
    {
      type: 'function',
      name: 'Run Claude managed agent',
      description: 'Dispatch a session to a Claude managed agent.',
      config: { template_id: 'template-claude-managed-agent', inputs: {} },
      output_variable: { key: 'session', result_path: null, spread: false },
    },
  ],
})
```

Register via side-effect import in
`products/workflows/frontend/Workflows/hogflows/registry/actions/index.ts`.

### Feature flag

Add `WORKFLOWS_CLAUDE_AGENTS` to `lib/constants.ts`. Off by default.

## Backend (Node.js CDP) changes

### Hog function template

New file `nodejs/src/cdp/templates/_destinations/posthog_workflows/claude-managed-agent.template.ts`:

```ts
import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
  free: false,
  status: 'hidden', // workflows-only; not in generic destination picker
  type: 'destination',
  id: 'template-claude-managed-agent',
  name: 'Run Claude managed agent',
  description: 'Create a session against a Claude managed agent.',
  icon_url: '/static/services/anthropic.png',
  category: ['Custom'],
  code_language: 'hog',
  code: `
let response := claudeCreateSession({
    'integration_id': inputs.anthropic_workspace.integration_id,
    'agent_id': inputs.agent,
    'environment_id': inputs.environment,
    'vault_ids': inputs.vault_ids,
    'message': inputs.message,
})

if (response.status >= 400) {
    throw Error(f'Claude session create failed: {response.status} {response.body}')
}

return {
    'id': response.body.id,
    'status': response.body.status,
    'environment_id': response.body.environment_id,
    'agent': response.body.agent,
}
`,
  inputs_schema: [
    {
      key: 'anthropic_workspace',
      type: 'integration',
      integration: 'anthropic',
      required: true,
      label: 'Anthropic workspace',
    },
    {
      key: 'agent',
      type: 'integration_field',
      integration_key: 'anthropic_workspace',
      integration_field: 'anthropic_agent',
      required: true,
      label: 'Agent',
    },
    {
      key: 'environment',
      type: 'integration_field',
      integration_key: 'anthropic_workspace',
      integration_field: 'anthropic_environment',
      required: true,
      label: 'Environment',
    },
    {
      key: 'vault_ids',
      type: 'integration_field',
      integration_key: 'anthropic_workspace',
      integration_field: 'anthropic_vaults',
      required: false,
      label: 'Vaults',
    },
    {
      key: 'message',
      type: 'string',
      required: true,
      label: 'Initial message',
      default: 'Process event {event.event} for distinct_id {event.distinct_id}',
    },
  ],
}
```

Register in `nodejs/src/cdp/templates/index.ts` under `HOG_FUNCTION_TEMPLATES_DESTINATIONS`.

### Async function

New file `nodejs/src/cdp/async-functions/claude.ts`:

```ts
import { CyclotronInvocationQueueParametersFetchSchema } from '~/schema/cyclotron'
import { registerAsyncFunction } from '../async-function-registry'

registerAsyncFunction('claudeCreateSession', {
  execute: async (args, context, result) => {
    const [opts] = args as [Record<string, any> | undefined]
    const { integration_id, agent_id, environment_id, vault_ids, message } = opts ?? {}

    // Resolve the integration row (kind='anthropic') and pull the API key.
    const integration = await context.hub.integrationManager.get(context.invocation.teamId, integration_id)
    if (!integration || integration.kind !== 'anthropic') {
      throw new Error(`Anthropic integration ${integration_id} not found`)
    }
    const apiKey = integration.sensitive_config?.api_key
    if (!apiKey) throw new Error('Anthropic integration missing api_key')

    result.invocation.queueParameters = CyclotronInvocationQueueParametersFetchSchema.parse({
      type: 'fetch',
      url: 'https://api.anthropic.com/v1/sessions',
      method: 'POST',
      headers: {
        'x-api-key': apiKey,
        'anthropic-version': '2023-06-01',
        'anthropic-beta': 'managed-agents-2026-04-01',
        'content-type': 'application/json',
      },
      body: JSON.stringify({
        agent: agent_id,
        environment_id,
        vault_ids: vault_ids ?? [],
        title: `workflow:${context.invocation.hogFunction?.id ?? 'unknown'}`,
        resources: [
          // No file/repo resources in v1.
        ],
      }),
    })
  },

  mock: (args) => ({
    status: 201,
    body: {
      id: 'sesn_mock',
      status: 'rescheduling',
      environment_id: args[0]?.environment_id,
      agent: { id: args[0]?.agent_id, version: 'mock' },
    },
  }),
})
```

Register via side-effect import in `nodejs/src/cdp/async-functions/index.ts`.

The fetch goes through the established `queueParameters` pattern, so retries,
timeouts, and audit logging all come for free.

## Security

- API keys live in `Integration.sensitive_config` (encrypted via
  `EncryptedJSONField`). Same posture as Slack tokens, Twilio auth tokens, etc.
- The async function reads the key via `context.hub.integrationManager`, never via
  hog code. The hog template only sees the integration's display fields.
- Vault credentials never enter PostHog — they live entirely in Anthropic's
  Managed Agents vault store. We only pass `vault_ids` references.
- The kickoff message is a Hog template that interpolates event properties.
  Operators are responsible for not putting secrets into event properties — same
  rule as for any other dispatch.
- Rate limits: Managed Agents Create endpoints are 300 RPM per organization
  (`shared/managed-agents-api-reference.md`). Honor the Anthropic SDK's built-in
  retry-after handling on the Node side.

## Risks & open questions

| #   | Risk / question                                 | Mitigation / decision needed                                                                                                                                          |
| --- | ----------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `integration_field` multi-select support        | Verify `IntegrationField.tsx` accepts `multiple: true`; extend if not. Spike before PR 2.                                                                             |
| 2   | Beta header `managed-agents-2026-04-01` may rev | Centralize the header in a single constant in `claude.ts`; document in the integration setup screen.                                                                  |
| 3   | Workspace ID for `integration_id`               | Confirm the Anthropic API exposes a stable workspace identifier. If not, derive from a hash of the API key (with collision check via the existing unique constraint). |
| 4   | Session creation latency                        | `POST /v1/sessions` blocks until resources mount. Acceptable inside the existing fetch queue; document P95 in onboarding.                                             |
| 5   | Output truncation                               | Hog `return` value is JSON-serialized into the workflow variable. Cap fields we copy to `{id, status, environment_id, agent}`.                                        |
| 6   | Deleted/archived agent at runtime               | Surface the 4xx response cleanly via `throw Error(...)`. Workflow `on_error` policy handles the rest.                                                                 |

## Test plan

- **Unit**: `AnthropicIntegration` validation against a stub SDK client
  (success + 401 + 403 paths).
- **Unit**: each of the three `@action` endpoints returns the expected shape.
- **Unit**: hog template `inputs_schema` round-trips through the existing CDP
  validators (`posthog/cdp/validation.py`).
- **Unit (Node)**: `claudeCreateSession` builds the correct `queueParameters`
  payload, including beta header, body, and vault_ids passthrough. Mock matches
  the success shape.
- **Integration (manual)**: connect a real Anthropic test workspace, configure a
  workflow, fire a trigger, observe a session appearing in the Anthropic
  dashboard. Verify the session ID is recorded in workflow variables.

## Rollout

1. PR 1 — backend integration (kind, model class, migration, creation endpoint).
   Behind no flag; the integration is invisible until the frontend ships.
2. PR 2 — three list endpoints + frontend `integration_field` registrations + the
   Anthropic integration entry in the integrations list page.
3. PR 3 — hog template + async function + workflows action category, gated on
   `WORKFLOWS_CLAUDE_AGENTS`.
4. Internal dogfood with the team-workflows Anthropic workspace.
5. Roll the flag out to early-access customers once the dogfood pass is clean.

## Future work

- "Wait for idle" mode — workflow holds and resumes when the session reaches a
  terminal status (would require either a poller or a webhook back into PostHog).
- Stream `agent.message` content back as PostHog events for downstream analytics.
- Custom tool round-trip — let workflow nodes back-fill `user.custom_tool_result`
  events.
- Agent/environment/vault management UI inside PostHog (today, that lives in
  Anthropic's surfaces and the `ant` CLI).
- Multi-key per integration (production vs. dev workspace).
