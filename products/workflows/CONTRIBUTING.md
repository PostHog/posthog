# Contributing to workflows

This product is designed so other teams can add their own workflow trigger types, action nodes, and any backend functionality that those nodes need.

At a high level:

- **Frontend (workflows editor)** uses registries to discover which trigger types and action nodes to show.
- **Backend (CDP Hog templates)** defines what a “function node” actually does via a Hog function template (`template_id`).
- **Backend (async functions)** provides any custom runtime functionality used by Hog code (e.g. HTTP requests, enriched lookups, etc.).

## How the pieces connect

When you add a new “hog function” action node, the wiring is:

1. Frontend action node sets `config.template_id`.
2. Backend template with the same `id` contains the Hog code run for that node.
3. Hog code may call async functions (e.g. `postHogGetTicket(...)`).
4. Async function implementation is registered in the Node service and executed at runtime.

Concrete end-to-end example:

- Frontend action node uses `template_id: 'template-posthog-get-ticket'`:
  - products/workflows/frontend/Workflows/hogflows/registry/actions/conversations.ts
- Backend template defines `id: 'template-posthog-get-ticket'` and calls `postHogGetTicket(...)`:
  - nodejs/src/cdp/templates/\_destinations/posthog_conversations/posthog-get-ticket.template.ts
- Backend async function registers `postHogGetTicket`:
  - nodejs/src/cdp/async-functions/conversations.ts

## Frontend: adding a trigger type

Trigger types extend the trigger selector UI in the workflow editor. A trigger type is responsible for:

- How it appears in the dropdown (label, description, icon)
- How it maps to/owns a config (`matchConfig`)
- How to build an initial config when selected (`buildConfig`)
- Optionally, how to render extra configuration UI (`ConfigComponent`)

### 1) Implement and register the trigger definition

Create a new file under:

- products/workflows/frontend/Workflows/hogflows/registry/triggers/

Then call `registerTriggerType(...)` from:

- products/workflows/frontend/Workflows/hogflows/registry/triggers/triggerTypeRegistry.ts

Example implementation:

- products/workflows/frontend/Workflows/hogflows/registry/triggers/conversations.tsx

Minimal skeleton:

```tsx
import { IconBolt } from '@posthog/icons'

import { registerTriggerType } from 'products/workflows/frontend/Workflows/hogflows/registry/triggers/triggerTypeRegistry'

registerTriggerType({
  value: 'my_product_something_happened',
  label: 'Something happened',
  icon: <IconBolt />,
  description: 'Trigger when something happens',
  // Optional: featureFlag: FEATURE_FLAGS.MY_FLAG,
  matchConfig: (config) => config.type === 'event' && /* detect your event filter config */ false,
  buildConfig: () => ({
    type: 'event',
    filters: {
      events: [{ id: '$my_event', type: 'events', name: 'My event' }],
    },
  }),
  // Optional: ConfigComponent,
})
```

### 2) Ensure it’s imported (registered)

Registration is done via module side effects. Your trigger file must be imported by the workflows frontend bundle.

The workflows registry entrypoint is:

- products/workflows/frontend/Workflows/hogflows/registry/triggers/index.ts

Add an import for your file there (pattern shown by `conversations`).

### 3) (Optional) Add a configuration UI

If your trigger needs extra UI beyond the standard “Event” filters, provide a `ConfigComponent`.

Reference:

- products/workflows/frontend/Workflows/hogflows/registry/triggers/conversations.tsx

Notes:

- `ConfigComponent` receives the workflow node; use `workflowLogic` actions to update `node.data.config`.
- Keep configs serializable and stable: configs are persisted as part of the workflow.

## Frontend: adding an action node

Action nodes shown in the “Build” toolbar come from:

- Built-ins in products/workflows/frontend/Workflows/hogflows/panel/HogFlowEditorPanelBuild.tsx
- Registered categories from products/workflows/frontend/Workflows/hogflows/registry/actions/actionNodeRegistry.ts

Each category contains one or more `CreateActionType` nodes (see type in products/workflows/frontend/Workflows/hogflows/hogFlowEditorLogic.tsx).

### 1) Add an action node category

Create a new file under:

- products/workflows/frontend/Workflows/hogflows/registry/actions/

Then call `registerActionNodeCategory(...)` from:

- products/workflows/frontend/Workflows/hogflows/registry/actions/actionNodeRegistry.ts

Example category:

- products/workflows/frontend/Workflows/hogflows/registry/actions/conversations.ts

Minimal skeleton:

```ts
import { registerActionNodeCategory } from 'products/workflows/frontend/Workflows/hogflows/registry/actions/actionNodeRegistry'

registerActionNodeCategory({
  label: 'My product',
  // Optional: featureFlag: FEATURE_FLAGS.MY_FLAG,
  nodes: [
    {
      type: 'function',
      name: 'Do a thing',
      description: 'Does a thing and stores the result.',
      config: { template_id: 'template-my-product-do-thing', inputs: {} },
      // Optional: output_variable: { key: 'thing', result_path: null, spread: true },
    },
  ],
})
```

### 2) Ensure it’s imported (registered)

As with triggers, registration is done via side-effect imports.

Add your file to:

- products/workflows/frontend/Workflows/hogflows/registry/actions/index.ts

The editor imports the registry entrypoint here:

- products/workflows/frontend/Workflows/hogflows/panel/HogFlowEditorPanelBuild.tsx

## Backend: adding a Hog function template (`template_id`)

Workflow “function” nodes run Hog code via Hog function templates. For a new action node, you typically add a new destination template and reference it by `template_id`.

### 1) Create the template file

Create a new template under:

- nodejs/src/cdp/templates/\_destinations/

Workflows-specific templates live under:

- nodejs/src/cdp/templates/\_destinations/posthog_workflows/

Conversations examples that are used by workflows live under:

- nodejs/src/cdp/templates/\_destinations/posthog_conversations/

Examples:

- nodejs/src/cdp/templates/\_destinations/posthog_conversations/posthog-get-ticket.template.ts
- nodejs/src/cdp/templates/\_destinations/posthog_conversations/posthog-update-ticket.template.ts

Guidelines:

- Choose a stable, unique `id` (this is what the frontend uses as `template_id`).
- For workflow-only templates, prefer `status: 'hidden'` so they don’t show up in generic template pickers.
- Keep `inputs_schema` accurate: it drives UI and validation.

### 2) Register it in the templates index

Templates are exported from a central list. Add an import and include it in `HOG_FUNCTION_TEMPLATES_DESTINATIONS`:

- nodejs/src/cdp/templates/index.ts

Reference for how existing workflows templates are added:

- Imports: `posthogGetTicketTemplate`, `posthogUpdateTicketTemplate`, `posthogSetHogflowVariableTemplate`
- List: `HOG_FUNCTION_TEMPLATES_DESTINATIONS`

## Backend: adding an async function

Async functions are Node-side functions callable from Hog code.

Example of a simple pattern and required `mock` implementation:

- nodejs/src/cdp/async-functions/example.ts

Example used by workflows templates:

- nodejs/src/cdp/async-functions/conversations.ts

### 1) Implement the async function

Add a new file under:

- nodejs/src/cdp/async-functions/

Then register it:

```ts
import { registerAsyncFunction } from '../async-function-registry'

registerAsyncFunction('myAsyncFn', {
  execute: async (args, context, result) => {
    // Validate args
    // Use context.hub services as needed
    // Write to result.invocation / result.logs / result.error
  },
  mock: (args, logs) => {
    // Used in the workflows “Test” tooling when real requests are disabled
    return { status: 200, body: {} }
  },
})
```

Notes:

- Always validate/guard your arguments. Throwing errors will surface in invocation logs.
- `mock` is product-facing in test tooling; keep its shape consistent with the real implementation.
- If you need a fetch request, follow the established `queueParameters` pattern used in:
  - nodejs/src/cdp/async-functions/conversations.ts

### 2) Import it so it actually registers

Async functions are registered via side-effect imports. Add your file to:

- nodejs/src/cdp/async-functions/index.ts

If you skip this step, your async function will never be available to Hog code.

## Common pitfalls

- **Forgot the side-effect import**: triggers/actions must be imported by their `index.ts`, and async functions must be imported by nodejs/src/cdp/async-functions/index.ts.
- **Template id mismatch**: `config.template_id` in the frontend must exactly match `template.id` in the backend.
- **Mocks don’t match real behavior**: workflows test tooling relies on `mock` returning realistic structures.
- **Feature flag gating**: if you add `featureFlag` to triggers or categories, make sure you’re using an existing flag from `lib/constants`.
