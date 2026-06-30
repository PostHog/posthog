import { z } from 'zod'

// Relative (not `@/`) import: this module is loaded by the tsx schema-generation
// script, and `playbookIds` is pure constants — no `.md` imports to choke on.
import { PLAYBOOK_IDS, PLAYBOOK_URI_PREFIX } from '../tools/agentPlatform/playbookIds'

export const BusinessKnowledgeUrlSourceCreateSchema = z.object({
    name: z
        .string()
        .max(255)
        .describe('Short human label for the source. Shown in the settings list and in agent citations.'),
    url: z.string().url().max(2048).describe('Public HTTP(S) URL to fetch. Private or internal hosts are rejected.'),
    source_type: z.literal('url').default('url').describe('Source type. Always "url" for this tool.'),
    refresh_interval: z
        .enum(['manual', '1h', '6h', '24h', '7d'])
        .optional()
        .default('manual')
        .describe('How often to auto-refresh this source in the background. Defaults to "manual" (no auto-refresh).'),
    always_include: z
        .boolean()
        .optional()
        .default(false)
        .describe(
            "When true, this source's content is injected into every support reply prompt as general context (tone, policies, direction), not just when it matches a query."
        ),
})

export const AgentResolveResourceSchema = z.object({
    resource: z
        .string()
        .describe(
            `Which builder playbook to fetch. Accepts either a bare id (one of: ${PLAYBOOK_IDS.join(', ')}) or its URI form (\`${PLAYBOOK_URI_PREFIX}<id>\`). A playbook is a markdown guide for using the agent-platform authoring tools well; it comes back with the live, scope-aware tool surface for the operation. Fetch the playbook rather than recalling tool names from memory.`
        ),
})

export const ExternalDataJobsAfterSchema = z
    .string()
    .describe('ISO timestamp — only return jobs created after this date (e.g. "2025-01-01T00:00:00Z").')

export const ExternalDataJobsBeforeSchema = z
    .string()
    .describe('ISO timestamp — only return jobs created before this date (e.g. "2025-12-31T23:59:59Z").')

export const ExternalDataJobsSchemasSchema = z
    .array(z.string())
    .describe('Filter jobs by table schema names (e.g. ["users", "orders"]). Only returns jobs for these tables.')

export const ExternalDataSourcePayloadSchema = z
    .record(z.string(), z.unknown())
    .describe(
        'Connection credentials for the source. Keys depend on source_type. For database sources: host, port, database, user, password, schema. For SaaS sources: api_key or OAuth fields. For source_type "Custom" (a user-defined REST API): `manifest_json` (a stringified RESTAPIConfig describing client.base_url, auth, and resources) plus the credential for the auth type declared in the manifest — `auth_token` (bearer), `auth_api_key` (api_key), or `auth_password` (http_basic); keep secrets in these auth_* keys, never inline in manifest_json. Use external-data-sources-wizard (pass source_type) to see required fields per source type. For the advanced external-data-sources-create flow, the per-table \'schemas\' array (built from external-data-sources-db-schema) also goes in here, e.g. {"host": ..., "password": ..., "schemas": [{"name": "orders", "should_sync": true, "sync_type": "incremental", "incremental_field": "updated_at", "incremental_field_type": "datetime"}]}. Do not pass unresolved {"secretRef": ...} objects — resolve secrets to real values first, or use a credential_id from data-warehouse-source-connect-link.'
    )

export const ExternalDataSourceTypeSchema = z
    .string()
    .describe(
        'The source type name (e.g. "Postgres", "MySQL", "Stripe"). Use external-data-sources-wizard to see available types and their required fields.'
    )

const UsageMetricEventsFilterEntrySchema = z.object({
    id: z.string().describe('Event name (e.g. "$pageview").'),
    name: z.string().optional(),
    type: z.literal('events').optional(),
    order: z.number().int().optional(),
    properties: z.array(z.unknown()).optional(),
})

const UsageMetricEventsFiltersSchema = z
    .object({
        events: z.array(UsageMetricEventsFilterEntrySchema).describe('Events to count or sum over.'),
        actions: z.array(z.unknown()).optional(),
        properties: z.array(z.unknown()).optional(),
        filter_test_accounts: z.boolean().optional(),
    })
    .describe('Events-source filter shape (default).')

const UsageMetricDataWarehouseFiltersSchema = z
    .object({
        source: z.literal('data_warehouse'),
        table_name: z
            .string()
            .describe(
                'Name of a synced data warehouse table. Use `external-data-schemas-list` to discover available tables.'
            ),
        timestamp_field: z
            .string()
            .describe(
                'Timestamp column or HogQL expression on the row (e.g. "created" or "toDateTime(created_at)"). Use `execute-sql` (`SELECT * FROM <table> LIMIT 1`) to inspect available columns.'
            ),
        key_field: z
            .string()
            .describe(
                'Column on the row whose value matches the entity key. v1 supports group profiles only — the column value is compared to the group_key.'
            ),
    })
    .describe('Data-warehouse-source filter shape.')

export const UsageMetricFiltersSchema = z
    .union([UsageMetricDataWarehouseFiltersSchema, UsageMetricEventsFiltersSchema])
    .describe(
        'Filter definition. Pick exactly one branch: `data_warehouse` (set `source: "data_warehouse"` plus `table_name`/`timestamp_field`/`key_field`) or `events` (HogFunction filter shape with an `events` array).'
    )

const CategoricalScoreOptionSchema = z.object({
    key: z
        .string()
        .min(1)
        .max(128)
        .describe(
            'Stable option key — lowercase letters, numbers, underscores, hyphens. Sent back when this option is selected.'
        ),
    label: z.string().min(1).max(256).describe('Human-readable label shown in the review UI.'),
})

const CategoricalScoreDefinitionConfigSchema = z
    .object({
        options: z
            .array(CategoricalScoreOptionSchema)
            .min(1)
            .refine(
                (options) => new Set(options.map((option) => option.key)).size === options.length,
                'Categorical option keys must be unique.'
            )
            .describe('Ordered categorical options. Must contain at least one option with unique keys.'),
        selection_mode: z
            .enum(['single', 'multiple'])
            .optional()
            .describe('Whether reviewers select one option or many. Defaults to "single".'),
        min_selections: z
            .number()
            .int()
            .min(1)
            .optional()
            .describe('Minimum selections required. Only valid when selection_mode is "multiple".'),
        max_selections: z
            .number()
            .int()
            .min(1)
            .optional()
            .describe('Maximum selections allowed. Only valid when selection_mode is "multiple".'),
    })
    .strict()
    .describe('Config shape used when kind is "categorical".')

const NumericScoreDefinitionConfigSchema = z
    .object({
        min: z.number().optional().describe('Optional inclusive minimum score.'),
        max: z.number().optional().describe('Optional inclusive maximum score (must be ≥ min).'),
        step: z.number().positive().optional().describe('Optional increment step for numeric input, e.g. 1 or 0.5.'),
    })
    .strict()
    .describe('Config shape used when kind is "numeric".')

const BooleanScoreDefinitionConfigSchema = z
    .object({
        true_label: z.string().min(1).optional().describe('Optional label shown for the true branch (e.g. "Yes").'),
        false_label: z.string().min(1).optional().describe('Optional label shown for the false branch (e.g. "No").'),
    })
    .strict()
    .describe('Config shape used when kind is "boolean".')

export const ScoreDefinitionConfigSchema = z
    .union([
        CategoricalScoreDefinitionConfigSchema,
        NumericScoreDefinitionConfigSchema,
        BooleanScoreDefinitionConfigSchema,
    ])
    .describe(
        'Immutable scorer configuration. Pick the shape matching the scorer kind: categorical (options + selection_mode), numeric (min/max/step), or boolean (true_label/false_label). The server validates the shape against the kind on the parent scorer and returns 400 on a mismatch.'
    )

export const PromptListInputSchema = z.object({
    search: z.string().optional().describe('Optional substring filter applied to prompt names and prompt content.'),
    content: z
        .enum(['full', 'preview', 'none'])
        .default('none')
        .describe(
            "Controls how much prompt content is included in list results. 'full' includes the full prompt, 'preview' includes a short prompt_preview, and 'none' omits prompt content entirely."
        ),
})

export const FeedbackSubmitSchema = z.object({
    summary: z
        .string()
        .min(1)
        .describe(
            'A one-sentence headline capturing the feedback (e.g. "session replay scrubber jumps backwards when you click the timeline", "query-trends descriptions made it hard to choose between trends and funnels", or "the new SQL editor autocomplete is excellent").'
        ),
    feedback_type: z
        .enum(['product', 'mcp', 'docs', 'other'])
        .describe(
            'What this feedback is about. "product" = any PostHog product or feature (insights, session replay, feature flags, the data warehouse, web analytics, error tracking, etc.). "mcp" = this MCP server itself — a tool, its input schema, response format, an error, or these instructions. "docs" = PostHog documentation. "other" = anything that doesn\'t fit the above.'
        ),
    sentiment: z
        .enum(['positive', 'neutral', 'negative', 'mixed'])
        .describe(
            'The overall tone. Use "negative" for something broken or blocking, "mixed" for mostly-fine-but-with-a-concrete-problem, "neutral" for a suggestion or feature request with no strong sentiment, and "positive" for praise or something that worked well. All sentiments are welcome — positive feedback is encouraged, not just problems.'
        ),
    product_area: z
        .string()
        .optional()
        .describe(
            'The PostHog product or area this is about, in free text (e.g. "session replay", "insights", "data warehouse", "feature flags", "docs"). Most useful for product feedback; for MCP feedback the tool name belongs in `details`/`friction_points` instead.'
        ),
    category: z
        .enum([
            'tool_correctness',
            'tool_description',
            'tool_input_schema',
            'tool_output_format',
            'missing_tool',
            'instructions_clarity',
            'performance',
            'error_message',
            'other',
        ])
        .optional()
        .describe(
            'For MCP feedback (`feedback_type: "mcp"`) only: the single category that best describes the dominant theme. Pick "missing_tool" if a capability was absent, "tool_description" if the tool docs were unclear, "tool_input_schema" if input args were confusing, "tool_output_format" if the response was hard to consume, "instructions_clarity" if these MCP instructions were unclear, "tool_correctness" if a tool returned wrong data, "error_message" if an error was unhelpful, "performance" if latency was the issue. Omit for product, docs, or other feedback.'
        ),
    task_completed: z
        .boolean()
        .optional()
        .describe(
            'Were you able to complete the user\'s task? Be honest — "false" is just as useful as "true". Most relevant when `feedback_type` is "mcp".'
        ),
    tools_used: z
        .array(z.string())
        .optional()
        .describe(
            'The MCP tool names you called while working on the user\'s task (e.g. ["read-data-schema", "query-trends"]). Helps us correlate feedback to specific tools.'
        ),
    friction_points: z
        .string()
        .optional()
        .describe(
            'Clear, concise bullet points describing the friction — what was confusing, broken, slow, or missing. Quote the exact product surface, tool name, parameter, or error text where you can. Omit for purely positive feedback.'
        ),
    suggested_improvement: z
        .string()
        .optional()
        .describe(
            'The single most impactful, concrete change that would address this feedback, if you can name one (e.g. "add a `filters` example to query-funnel\'s description", or "let the replay scrubber snap to the nearest event"). Optional — praise or an observation doesn\'t need one.'
        ),
    user_request: z
        .string()
        .optional()
        .describe(
            'A short, anonymised paraphrase of what the user originally asked you to do. Do not include PII, customer names, or sensitive query content.'
        ),
    details: z
        .string()
        .optional()
        .describe("Any additional context that doesn't fit the other fields. Keep it to clear, concise bullet points."),
})

const SavedMetricAttachItemSchema = z.object({
    id: z
        .number()
        .int()
        .describe('ID of an existing shared/saved metric. Discover IDs with experiment-saved-metrics-list.'),
    metadata: z
        .object({
            type: z
                .enum(['primary', 'secondary'])
                .describe('Whether this metric is a primary or secondary metric on the experiment.'),
        })
        .optional()
        .describe('Optional per-link metadata. Omit to default this metric to primary.'),
})

export const SavedMetricsAttachSchema = z
    .array(SavedMetricAttachItemSchema)
    .describe(
        "The complete desired set of shared (saved) metrics for the experiment — this REPLACES all existing saved-metric links, it does not append. To add or remove one, first read the experiment's current saved_metrics via experiment-get and resend the full set. Pass an empty array to detach all shared metrics."
    )

export const ExperimentResultsGetSchema = z.object({
    id: z.number().describe('The ID of the experiment to get comprehensive results for'),
    refresh: z
        .boolean()
        .optional()
        .default(false)
        .describe('Force refresh of results instead of using cached values. Defaults to false.'),
})

export const InsightQueryInputSchema = z.object({
    insightId: z.string().describe('The insight ID or short_id to run.'),
    output_format: z
        .enum(['optimized', 'json'])
        .optional()
        .default('optimized')
        .describe(
            'Output format. "optimized" returns a human-readable summary from server-side formatters (recommended for analysis). "json" returns the raw query results as JSON.'
        ),
    variables_override: z
        .union([z.string(), z.record(z.string(), z.unknown())])
        .optional()
        .describe(
            'Object (or pre-encoded JSON string) to override the insight\'s HogQL variables for this run only (not persisted). Format: {"<variable_id>": {"code_name": "<code_name>", "variableId": "<variable_id>", "value": <new_value>}}. Each entry must include `code_name` — partial entries are silently dropped. The simplest workflow is to call `insight-get` first, copy the matching entry from the response\'s query variables, and mutate `value`. Top-level keys replace; nested values are not deep-merged. Ignored when accessed via a sharing token.'
        ),
    filters_override: z
        .union([z.string(), z.record(z.string(), z.unknown())])
        .optional()
        .describe(
            "Object (or pre-encoded JSON string) to override the insight's filters for this run only (not persisted). Top-level keys replace; nested values are not deep-merged — pass the complete value for any key you override. Accepts the same keys as the dashboard filters schema (e.g., `date_from`, `date_to`, `properties`). Ignored when accessed via a sharing token."
        ),
})

export const AIObservabilityGetCostsSchema = z.object({
    projectId: z.number().int().positive(),
    days: z.number().optional(),
})

export const OrganizationSetActiveSchema = z.object({
    orgId: z.string(),
})

export const ProjectGetAllSchema = z.object({})

export const EventDefinitionUpdateInputSchema = z.object({
    description: z.string().optional().describe('Description explaining when the event is triggered'),
    tags: z
        .array(z.string())
        .optional()
        .describe(
            'Tags to organize events by product area (e.g. "checkout", "onboarding") or user journey stage (e.g. "acquisition", "activation", "monetization", "retention")'
        ),
    verified: z
        .boolean()
        .optional()
        .describe('Mark as verified to indicate the event is properly instrumented and tracking correctly'),
    hidden: z
        .boolean()
        .optional()
        .describe('Mark event as no longer used/captured. Hides it from UI while preserving historical data'),
})

export const EventDefinitionUpdateSchema = z.object({
    eventName: z.string().describe('The name of the event to update (e.g. "$pageview", "user_signed_up")'),
    data: EventDefinitionUpdateInputSchema.describe('The event definition data to update'),
})

export const ProjectSetActiveSchema = z.object({
    projectId: z.number().int().positive(),
})

// Debug MCP UI Apps
export const DebugMcpUiAppsSchema = z.object({
    message: z.string().optional().describe('Optional message to include in the debug data'),
})

// PostHog AI tools
export const ExecuteSQLSchema = z.object({
    query: z.string().min(1).describe('The final SQL query to be executed.'),
    truncate: z
        .boolean()
        .optional()
        .default(true)
        .describe(
            'Whether to truncate large blob/JSON values in results. Defaults to true. Set to false when you need full untruncated results (e.g., for dumping to a file).'
        ),
    connectionId: z
        .string()
        .optional()
        .describe(
            'Optional id of an external data source (e.g. a Postgres, DuckDB, or MySQL direct-query connection). When set, runs the query against that source instead of the ClickHouse catalog. Use external-data-sources-list to discover available connection ids.'
        ),
})

export const ReadDataWarehouseSchemaSchema = z
    .object({})
    .describe('No input required. Returns core data warehouse schemas.')

const ReadEventsQuerySchema = z.object({
    kind: z.literal('events'),
    limit: z.number().int().min(1).max(500).default(500).optional().describe('Number of events to return per page.'),
    offset: z.number().int().min(0).default(0).optional().describe('Number of events to skip for pagination.'),
})

const ReadEventPropertiesQuerySchema = z.object({
    kind: z.literal('event_properties'),
    event_name: z.string().describe('The name of the event that you want to retrieve properties for.'),
})

const ReadEntityPropertiesQuerySchema = z.object({
    kind: z.literal('entity_properties'),
    entity: z.string().describe('The type of the entity that you want to retrieve properties for.'),
})

const ReadActionPropertiesQuerySchema = z.object({
    kind: z.literal('action_properties'),
    action_id: z.number().int().describe('The ID of the action that you want to retrieve properties for.'),
})

const ReadEntitySamplePropertyValuesQuerySchema = z.object({
    kind: z.literal('entity_property_values'),
    entity: z.string().describe('The type of the entity that you want to retrieve properties for.'),
    property_name: z.string().describe('Verified property name of an entity.'),
})

const ReadEventSamplePropertyValuesQuerySchema = z.object({
    kind: z.literal('event_property_values'),
    event_name: z.string().describe('Verified event name'),
    property_name: z.string().describe('Verified property name of an event.'),
})

const ReadActionSamplePropertyValuesQuerySchema = z.object({
    kind: z.literal('action_property_values'),
    action_id: z.number().int().describe('Verified action ID'),
    property_name: z.string().describe('Verified property name of an action.'),
})

export const ReadDataSchemaSchema = z.object({
    query: z
        .discriminatedUnion('kind', [
            ReadEventsQuerySchema,
            ReadEventPropertiesQuerySchema,
            ReadEntityPropertiesQuerySchema,
            ReadActionPropertiesQuerySchema,
            ReadEntitySamplePropertyValuesQuerySchema,
            ReadEventSamplePropertyValuesQuerySchema,
            ReadActionSamplePropertyValuesQuerySchema,
        ])
        .describe('The data schema query to execute.'),
})

// Mirrors the Django serializer's `validate` rule so the MCP layer fails fast
// instead of forwarding an empty/ambiguous body and waiting for a 400.
export function validateDistinctIdPersonIdExclusive(
    data: { distinct_id?: string | undefined; person_id?: string | undefined },
    ctx: z.RefinementCtx
): void {
    const hasDistinctId = typeof data.distinct_id === 'string' && data.distinct_id.length > 0
    const hasPersonId = typeof data.person_id === 'string' && data.person_id.length > 0
    if (!hasDistinctId && !hasPersonId) {
        ctx.addIssue({
            code: 'custom',
            message: 'Either distinct_id or person_id must be provided',
        })
    }
    if (hasDistinctId && hasPersonId) {
        ctx.addIssue({
            code: 'custom',
            message: 'Cannot provide both distinct_id and person_id (they are mutually exclusive)',
        })
    }
}

const WorkflowGraphEdgeSchema = z.object({
    from: z.string().describe('Source action id.'),
    to: z.string().describe('Target action id.'),
    type: z
        .enum(['continue', 'branch'])
        .describe(
            "'continue' = fall-through (sequential or no-match path); 'branch' = a condition/cohort branch (needs index)."
        ),
    index: z
        .number()
        .int()
        .optional()
        .describe('Required for type=branch: which condition/cohort slot this branch matches (0-based).'),
})

const WorkflowGraphOperationSchema = z.discriminatedUnion('op', [
    z.object({
        op: z.literal('update_action'),
        id: z.string().describe('Id of the action to update.'),
        patch: z
            .record(z.string(), z.unknown())
            .describe(
                'Partial action fields, deep-merged into the existing action; a null leaf deletes that key. ' +
                    'e.g. {config: {inputs: {subject: {value: "Hi"}}}} changes only that one input.'
            ),
    }),
    z.object({
        op: z.literal('add_action'),
        action: z
            .record(z.string(), z.unknown())
            .describe(
                'A full action node {id, name, type, config, ...}; same shape as entries in the workflow actions array.'
            ),
    }),
    z.object({
        op: z.literal('remove_action'),
        id: z.string().describe('Id of the action to remove. Its incoming edges reconnect to its first outgoer.'),
    }),
    z.object({
        op: z.literal('add_edge'),
        edge: WorkflowGraphEdgeSchema.describe('The edge to add.'),
    }),
    z.object({
        op: z.literal('remove_edge'),
        edge: WorkflowGraphEdgeSchema.describe('The edge to remove (matched on from/to/type/index).'),
    }),
    z.object({
        op: z.literal('replace_action_edges'),
        id: z.string().describe('Action id whose outgoing edges are being replaced.'),
        edges: z
            .array(WorkflowGraphEdgeSchema)
            .describe("The complete set of the action's outgoing edges; incoming edges are preserved."),
    }),
])

export const WorkflowGraphPatchSchema = z.object({
    id: z.string().describe('The workflow (HogFlow) id to edit. Draft only — active workflows are read-only via MCP.'),
    operations: z
        .array(WorkflowGraphOperationSchema)
        .min(1)
        .describe(
            'Ordered graph edits applied atomically: the stored graph is read, ops are applied in order, the result ' +
                'is fully validated, and it is saved only if valid — otherwise the workflow is left unchanged. Reference ' +
                'nodes/edges by id so you never resend the whole graph. The full updated workflow is returned.'
        ),
})

// Surgical edits to an email template's Unlayer design — one discriminated op per change, addressed by
// the stable block id. Mirrors DesignOperationSerializer; kept as a hand-authored discriminated union so
// the LLM sees exactly which fields each op needs (the auto-generated PATCH schema flattens them all to
// optional). `patch`/`content`/`row` are freeform Unlayer JSON.
const EmailDesignFreeformObject = z.record(z.string(), z.unknown())

const EmailDesignPatchOperationSchema = z.discriminatedUnion('op', [
    z.object({
        op: z.literal('update_content'),
        id: z.string().describe('Id of the content block to update.'),
        patch: EmailDesignFreeformObject.describe(
            'Partial content-block fields, deep-merged into the existing block; a null leaf deletes that key. ' +
                "e.g. {values: {text: '<p>Hi</p>'}} changes only the block's text."
        ),
    }),
    z.object({
        op: z.literal('update_column'),
        id: z.string().describe('Id of the column to update.'),
        patch: EmailDesignFreeformObject.describe('Partial column fields, deep-merged; a null leaf deletes that key.'),
    }),
    z.object({
        op: z.literal('update_row'),
        id: z.string().describe('Id of the row to update.'),
        patch: EmailDesignFreeformObject.describe('Partial row fields, deep-merged; a null leaf deletes that key.'),
    }),
    z.object({
        op: z.literal('update_body'),
        patch: EmailDesignFreeformObject.describe(
            "Partial body fields, deep-merged. e.g. {values: {backgroundColor: '#ffffff'}}."
        ),
    }),
    z.object({
        op: z.literal('add_content'),
        column_id: z.string().describe('Id of the column to insert the block into.'),
        content: EmailDesignFreeformObject.describe(
            'A content block {type, values: {...}}; omit id and values._meta — they are assigned server-side. ' +
                'type is one of text, heading, button, image, divider, html, etc.'
        ),
        index: z.number().int().optional().describe('0-based insert position; omit to append to the end.'),
    }),
    z.object({
        op: z.literal('remove_content'),
        id: z.string().describe('Id of the content block to remove.'),
    }),
    z.object({
        op: z.literal('move_content'),
        id: z.string().describe('Id of the content block to move.'),
        column_id: z.string().describe('Id of the destination column.'),
        index: z.number().int().optional().describe('0-based position in the destination column; omit to append.'),
    }),
    z.object({
        op: z.literal('add_row'),
        row: EmailDesignFreeformObject.describe(
            'A full row {cells, columns: [{contents: [...], values}], values}; ids and Unlayer numbering are ' +
                'assigned server-side for the row and everything nested in it.'
        ),
        index: z.number().int().optional().describe('0-based insert position; omit to append to the end.'),
    }),
    z.object({
        op: z.literal('remove_row'),
        id: z.string().describe('Id of the row to remove.'),
    }),
])

export const EmailTemplateDesignPatchSchema = z.object({
    id: z.string().describe('The email template id to edit.'),
    operations: z
        .array(EmailDesignPatchOperationSchema)
        .min(1)
        .describe(
            "Ordered edits applied atomically to the template's Unlayer design: the stored design is read, the ops " +
                'are applied in order, the result is validated and re-rendered to HTML, and saved only if valid — ' +
                'otherwise the template is left unchanged. Reference blocks by id so you never resend the whole design.'
        ),
})
