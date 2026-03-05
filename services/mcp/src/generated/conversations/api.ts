/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 18 ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const ConversationsListParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ConversationsListQueryParams = zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const conversationsListResponseResultsItemUserOneDistinctIdMax = 200

export const conversationsListResponseResultsItemUserOneFirstNameMax = 150

export const conversationsListResponseResultsItemUserOneLastNameMax = 150

export const conversationsListResponseResultsItemUserOneEmailMax = 254

export const ConversationsListResponse = zod.object({
    count: zod.number(),
    next: zod.string().url().nullish(),
    previous: zod.string().url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.string(),
            status: zod
                .enum(['idle', 'in_progress', 'canceling'])
                .describe('* `idle` - Idle\n* `in_progress` - In progress\n* `canceling` - Canceling'),
            title: zod.string().nullable().describe('Title of the conversation.'),
            user: zod.object({
                id: zod.number(),
                uuid: zod.string(),
                distinct_id: zod.string().max(conversationsListResponseResultsItemUserOneDistinctIdMax).nullish(),
                first_name: zod.string().max(conversationsListResponseResultsItemUserOneFirstNameMax).optional(),
                last_name: zod.string().max(conversationsListResponseResultsItemUserOneLastNameMax).optional(),
                email: zod.string().email().max(conversationsListResponseResultsItemUserOneEmailMax),
                is_email_verified: zod.boolean().nullish(),
                hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                role_at_organization: zod
                    .union([
                        zod
                            .enum([
                                'engineering',
                                'data',
                                'product',
                                'founder',
                                'leadership',
                                'marketing',
                                'sales',
                                'other',
                            ])
                            .describe(
                                '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                            ),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .nullish(),
            }),
            created_at: zod.string().datetime({}).nullable(),
            updated_at: zod.string().datetime({}).nullable(),
            type: zod
                .enum(['assistant', 'tool_call', 'deep_research', 'slack'])
                .describe(
                    '* `assistant` - Assistant\n* `tool_call` - Tool call\n* `deep_research` - Deep research\n* `slack` - Slack'
                ),
            is_internal: zod
                .boolean()
                .nullable()
                .describe(
                    'Whether this conversation was created during an impersonated session (e.g., by support agents). Internal conversations are hidden from customers.'
                ),
            slack_thread_key: zod
                .string()
                .nullable()
                .describe("Unique key for Slack thread: '{workspace_id}:{channel}:{thread_ts}'"),
            slack_workspace_domain: zod
                .string()
                .nullable()
                .describe("Slack workspace subdomain (e.g. 'posthog' for posthog.slack.com)"),
            messages: zod.array(zod.record(zod.string(), zod.unknown())),
            has_unsupported_content: zod.boolean(),
            agent_mode: zod.string().nullable(),
            pending_approvals: zod
                .array(zod.record(zod.string(), zod.unknown()))
                .describe(
                    'Return pending approval cards as structured data.\n\nCombines metadata from conversation.approval_decisions with payload from checkpoint\ninterrupts (single source of truth for payload data).'
                ),
        })
    ),
})

/**
 * Unified endpoint that handles both conversation creation and streaming.

- If message is provided: Start new conversation processing
- If no message: Stream from existing conversation
 */
export const ConversationsCreateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const conversationsCreateBodyContentMax = 40000

export const ConversationsCreateBody = zod
    .object({
        content: zod.string().max(conversationsCreateBodyContentMax).nullable(),
        conversation: zod.string(),
        contextual_tools: zod.record(zod.string(), zod.unknown()).optional(),
        ui_context: zod.unknown().optional(),
        billing_context: zod.unknown().optional(),
        trace_id: zod.string(),
        session_id: zod.string().optional(),
        agent_mode: zod
            .enum([
                'product_analytics',
                'sql',
                'session_replay',
                'error_tracking',
                'plan',
                'execution',
                'survey',
                'onboarding',
                'research',
                'flags',
                'llm_analytics',
            ])
            .optional()
            .describe(
                '* `product_analytics` - product_analytics\n* `sql` - sql\n* `session_replay` - session_replay\n* `error_tracking` - error_tracking\n* `plan` - plan\n* `execution` - execution\n* `survey` - survey\n* `onboarding` - onboarding\n* `research` - research\n* `flags` - flags\n* `llm_analytics` - llm_analytics'
            ),
        resume_payload: zod.unknown().nullish(),
    })
    .describe('Serializer for appending a message to an existing conversation without triggering AI processing.')

export const ConversationsRetrieveParams = zod.object({
    conversation: zod.string().describe('A UUID string identifying this conversation.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const conversationsRetrieveResponseUserOneDistinctIdMax = 200

export const conversationsRetrieveResponseUserOneFirstNameMax = 150

export const conversationsRetrieveResponseUserOneLastNameMax = 150

export const conversationsRetrieveResponseUserOneEmailMax = 254

export const ConversationsRetrieveResponse = zod.object({
    id: zod.string(),
    status: zod
        .enum(['idle', 'in_progress', 'canceling'])
        .describe('* `idle` - Idle\n* `in_progress` - In progress\n* `canceling` - Canceling'),
    title: zod.string().nullable().describe('Title of the conversation.'),
    user: zod.object({
        id: zod.number(),
        uuid: zod.string(),
        distinct_id: zod.string().max(conversationsRetrieveResponseUserOneDistinctIdMax).nullish(),
        first_name: zod.string().max(conversationsRetrieveResponseUserOneFirstNameMax).optional(),
        last_name: zod.string().max(conversationsRetrieveResponseUserOneLastNameMax).optional(),
        email: zod.string().email().max(conversationsRetrieveResponseUserOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    created_at: zod.string().datetime({}).nullable(),
    updated_at: zod.string().datetime({}).nullable(),
    type: zod
        .enum(['assistant', 'tool_call', 'deep_research', 'slack'])
        .describe(
            '* `assistant` - Assistant\n* `tool_call` - Tool call\n* `deep_research` - Deep research\n* `slack` - Slack'
        ),
    is_internal: zod
        .boolean()
        .nullable()
        .describe(
            'Whether this conversation was created during an impersonated session (e.g., by support agents). Internal conversations are hidden from customers.'
        ),
    slack_thread_key: zod
        .string()
        .nullable()
        .describe("Unique key for Slack thread: '{workspace_id}:{channel}:{thread_ts}'"),
    slack_workspace_domain: zod
        .string()
        .nullable()
        .describe("Slack workspace subdomain (e.g. 'posthog' for posthog.slack.com)"),
    messages: zod.array(zod.record(zod.string(), zod.unknown())),
    has_unsupported_content: zod.boolean(),
    agent_mode: zod.string().nullable(),
    pending_approvals: zod
        .array(zod.record(zod.string(), zod.unknown()))
        .describe(
            'Return pending approval cards as structured data.\n\nCombines metadata from conversation.approval_decisions with payload from checkpoint\ninterrupts (single source of truth for payload data).'
        ),
})

/**
 * Appends a message to an existing conversation without triggering AI processing.
This is used for client-side generated messages that need to be persisted
(e.g., support ticket confirmation messages).
 */
export const ConversationsAppendMessageCreateParams = zod.object({
    conversation: zod.string().describe('A UUID string identifying this conversation.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const conversationsAppendMessageCreateBodyContentMax = 10000

export const ConversationsAppendMessageCreateBody = zod
    .object({
        content: zod.string().max(conversationsAppendMessageCreateBodyContentMax),
    })
    .describe('Serializer for appending a message to an existing conversation without triggering AI processing.')

export const conversationsAppendMessageCreateResponseContentMax = 10000

export const ConversationsAppendMessageCreateResponse = zod
    .object({
        content: zod.string().max(conversationsAppendMessageCreateResponseContentMax),
    })
    .describe('Serializer for appending a message to an existing conversation without triggering AI processing.')

export const ConversationsCancelPartialUpdateParams = zod.object({
    conversation: zod.string().describe('A UUID string identifying this conversation.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ConversationsCancelPartialUpdateBody = zod.object({})

export const conversationsCancelPartialUpdateResponseUserOneDistinctIdMax = 200

export const conversationsCancelPartialUpdateResponseUserOneFirstNameMax = 150

export const conversationsCancelPartialUpdateResponseUserOneLastNameMax = 150

export const conversationsCancelPartialUpdateResponseUserOneEmailMax = 254

export const ConversationsCancelPartialUpdateResponse = zod.object({
    id: zod.string(),
    status: zod
        .enum(['idle', 'in_progress', 'canceling'])
        .describe('* `idle` - Idle\n* `in_progress` - In progress\n* `canceling` - Canceling'),
    title: zod.string().nullable().describe('Title of the conversation.'),
    user: zod.object({
        id: zod.number(),
        uuid: zod.string(),
        distinct_id: zod.string().max(conversationsCancelPartialUpdateResponseUserOneDistinctIdMax).nullish(),
        first_name: zod.string().max(conversationsCancelPartialUpdateResponseUserOneFirstNameMax).optional(),
        last_name: zod.string().max(conversationsCancelPartialUpdateResponseUserOneLastNameMax).optional(),
        email: zod.string().email().max(conversationsCancelPartialUpdateResponseUserOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    created_at: zod.string().datetime({}).nullable(),
    updated_at: zod.string().datetime({}).nullable(),
    type: zod
        .enum(['assistant', 'tool_call', 'deep_research', 'slack'])
        .describe(
            '* `assistant` - Assistant\n* `tool_call` - Tool call\n* `deep_research` - Deep research\n* `slack` - Slack'
        ),
    is_internal: zod
        .boolean()
        .nullable()
        .describe(
            'Whether this conversation was created during an impersonated session (e.g., by support agents). Internal conversations are hidden from customers.'
        ),
    slack_thread_key: zod
        .string()
        .nullable()
        .describe("Unique key for Slack thread: '{workspace_id}:{channel}:{thread_ts}'"),
    slack_workspace_domain: zod
        .string()
        .nullable()
        .describe("Slack workspace subdomain (e.g. 'posthog' for posthog.slack.com)"),
    messages: zod.array(zod.record(zod.string(), zod.unknown())),
    has_unsupported_content: zod.boolean(),
    agent_mode: zod.string().nullable(),
    pending_approvals: zod
        .array(zod.record(zod.string(), zod.unknown()))
        .describe(
            'Return pending approval cards as structured data.\n\nCombines metadata from conversation.approval_decisions with payload from checkpoint\ninterrupts (single source of truth for payload data).'
        ),
})

export const ConversationsQueueRetrieveParams = zod.object({
    conversation: zod.string().describe('A UUID string identifying this conversation.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const conversationsQueueRetrieveResponseUserOneDistinctIdMax = 200

export const conversationsQueueRetrieveResponseUserOneFirstNameMax = 150

export const conversationsQueueRetrieveResponseUserOneLastNameMax = 150

export const conversationsQueueRetrieveResponseUserOneEmailMax = 254

export const ConversationsQueueRetrieveResponse = zod.object({
    id: zod.string(),
    status: zod
        .enum(['idle', 'in_progress', 'canceling'])
        .describe('* `idle` - Idle\n* `in_progress` - In progress\n* `canceling` - Canceling'),
    title: zod.string().nullable().describe('Title of the conversation.'),
    user: zod.object({
        id: zod.number(),
        uuid: zod.string(),
        distinct_id: zod.string().max(conversationsQueueRetrieveResponseUserOneDistinctIdMax).nullish(),
        first_name: zod.string().max(conversationsQueueRetrieveResponseUserOneFirstNameMax).optional(),
        last_name: zod.string().max(conversationsQueueRetrieveResponseUserOneLastNameMax).optional(),
        email: zod.string().email().max(conversationsQueueRetrieveResponseUserOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    created_at: zod.string().datetime({}).nullable(),
    updated_at: zod.string().datetime({}).nullable(),
    type: zod
        .enum(['assistant', 'tool_call', 'deep_research', 'slack'])
        .describe(
            '* `assistant` - Assistant\n* `tool_call` - Tool call\n* `deep_research` - Deep research\n* `slack` - Slack'
        ),
    is_internal: zod
        .boolean()
        .nullable()
        .describe(
            'Whether this conversation was created during an impersonated session (e.g., by support agents). Internal conversations are hidden from customers.'
        ),
    slack_thread_key: zod
        .string()
        .nullable()
        .describe("Unique key for Slack thread: '{workspace_id}:{channel}:{thread_ts}'"),
    slack_workspace_domain: zod
        .string()
        .nullable()
        .describe("Slack workspace subdomain (e.g. 'posthog' for posthog.slack.com)"),
    messages: zod.array(zod.record(zod.string(), zod.unknown())),
    has_unsupported_content: zod.boolean(),
    agent_mode: zod.string().nullable(),
    pending_approvals: zod
        .array(zod.record(zod.string(), zod.unknown()))
        .describe(
            'Return pending approval cards as structured data.\n\nCombines metadata from conversation.approval_decisions with payload from checkpoint\ninterrupts (single source of truth for payload data).'
        ),
})

export const ConversationsQueueCreateParams = zod.object({
    conversation: zod.string().describe('A UUID string identifying this conversation.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ConversationsQueueCreateBody = zod.object({})

export const conversationsQueueCreateResponseUserOneDistinctIdMax = 200

export const conversationsQueueCreateResponseUserOneFirstNameMax = 150

export const conversationsQueueCreateResponseUserOneLastNameMax = 150

export const conversationsQueueCreateResponseUserOneEmailMax = 254

export const ConversationsQueueCreateResponse = zod.object({
    id: zod.string(),
    status: zod
        .enum(['idle', 'in_progress', 'canceling'])
        .describe('* `idle` - Idle\n* `in_progress` - In progress\n* `canceling` - Canceling'),
    title: zod.string().nullable().describe('Title of the conversation.'),
    user: zod.object({
        id: zod.number(),
        uuid: zod.string(),
        distinct_id: zod.string().max(conversationsQueueCreateResponseUserOneDistinctIdMax).nullish(),
        first_name: zod.string().max(conversationsQueueCreateResponseUserOneFirstNameMax).optional(),
        last_name: zod.string().max(conversationsQueueCreateResponseUserOneLastNameMax).optional(),
        email: zod.string().email().max(conversationsQueueCreateResponseUserOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    created_at: zod.string().datetime({}).nullable(),
    updated_at: zod.string().datetime({}).nullable(),
    type: zod
        .enum(['assistant', 'tool_call', 'deep_research', 'slack'])
        .describe(
            '* `assistant` - Assistant\n* `tool_call` - Tool call\n* `deep_research` - Deep research\n* `slack` - Slack'
        ),
    is_internal: zod
        .boolean()
        .nullable()
        .describe(
            'Whether this conversation was created during an impersonated session (e.g., by support agents). Internal conversations are hidden from customers.'
        ),
    slack_thread_key: zod
        .string()
        .nullable()
        .describe("Unique key for Slack thread: '{workspace_id}:{channel}:{thread_ts}'"),
    slack_workspace_domain: zod
        .string()
        .nullable()
        .describe("Slack workspace subdomain (e.g. 'posthog' for posthog.slack.com)"),
    messages: zod.array(zod.record(zod.string(), zod.unknown())),
    has_unsupported_content: zod.boolean(),
    agent_mode: zod.string().nullable(),
    pending_approvals: zod
        .array(zod.record(zod.string(), zod.unknown()))
        .describe(
            'Return pending approval cards as structured data.\n\nCombines metadata from conversation.approval_decisions with payload from checkpoint\ninterrupts (single source of truth for payload data).'
        ),
})

export const ConversationsQueuePartialUpdateParams = zod.object({
    conversation: zod.string().describe('A UUID string identifying this conversation.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    queue_id: zod.string(),
})

export const ConversationsQueuePartialUpdateBody = zod.object({})

export const conversationsQueuePartialUpdateResponseUserOneDistinctIdMax = 200

export const conversationsQueuePartialUpdateResponseUserOneFirstNameMax = 150

export const conversationsQueuePartialUpdateResponseUserOneLastNameMax = 150

export const conversationsQueuePartialUpdateResponseUserOneEmailMax = 254

export const ConversationsQueuePartialUpdateResponse = zod.object({
    id: zod.string(),
    status: zod
        .enum(['idle', 'in_progress', 'canceling'])
        .describe('* `idle` - Idle\n* `in_progress` - In progress\n* `canceling` - Canceling'),
    title: zod.string().nullable().describe('Title of the conversation.'),
    user: zod.object({
        id: zod.number(),
        uuid: zod.string(),
        distinct_id: zod.string().max(conversationsQueuePartialUpdateResponseUserOneDistinctIdMax).nullish(),
        first_name: zod.string().max(conversationsQueuePartialUpdateResponseUserOneFirstNameMax).optional(),
        last_name: zod.string().max(conversationsQueuePartialUpdateResponseUserOneLastNameMax).optional(),
        email: zod.string().email().max(conversationsQueuePartialUpdateResponseUserOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    created_at: zod.string().datetime({}).nullable(),
    updated_at: zod.string().datetime({}).nullable(),
    type: zod
        .enum(['assistant', 'tool_call', 'deep_research', 'slack'])
        .describe(
            '* `assistant` - Assistant\n* `tool_call` - Tool call\n* `deep_research` - Deep research\n* `slack` - Slack'
        ),
    is_internal: zod
        .boolean()
        .nullable()
        .describe(
            'Whether this conversation was created during an impersonated session (e.g., by support agents). Internal conversations are hidden from customers.'
        ),
    slack_thread_key: zod
        .string()
        .nullable()
        .describe("Unique key for Slack thread: '{workspace_id}:{channel}:{thread_ts}'"),
    slack_workspace_domain: zod
        .string()
        .nullable()
        .describe("Slack workspace subdomain (e.g. 'posthog' for posthog.slack.com)"),
    messages: zod.array(zod.record(zod.string(), zod.unknown())),
    has_unsupported_content: zod.boolean(),
    agent_mode: zod.string().nullable(),
    pending_approvals: zod
        .array(zod.record(zod.string(), zod.unknown()))
        .describe(
            'Return pending approval cards as structured data.\n\nCombines metadata from conversation.approval_decisions with payload from checkpoint\ninterrupts (single source of truth for payload data).'
        ),
})

export const ConversationsQueueDestroyParams = zod.object({
    conversation: zod.string().describe('A UUID string identifying this conversation.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    queue_id: zod.string(),
})

export const ConversationsQueueClearCreateParams = zod.object({
    conversation: zod.string().describe('A UUID string identifying this conversation.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ConversationsQueueClearCreateBody = zod.object({})

export const conversationsQueueClearCreateResponseUserOneDistinctIdMax = 200

export const conversationsQueueClearCreateResponseUserOneFirstNameMax = 150

export const conversationsQueueClearCreateResponseUserOneLastNameMax = 150

export const conversationsQueueClearCreateResponseUserOneEmailMax = 254

export const ConversationsQueueClearCreateResponse = zod.object({
    id: zod.string(),
    status: zod
        .enum(['idle', 'in_progress', 'canceling'])
        .describe('* `idle` - Idle\n* `in_progress` - In progress\n* `canceling` - Canceling'),
    title: zod.string().nullable().describe('Title of the conversation.'),
    user: zod.object({
        id: zod.number(),
        uuid: zod.string(),
        distinct_id: zod.string().max(conversationsQueueClearCreateResponseUserOneDistinctIdMax).nullish(),
        first_name: zod.string().max(conversationsQueueClearCreateResponseUserOneFirstNameMax).optional(),
        last_name: zod.string().max(conversationsQueueClearCreateResponseUserOneLastNameMax).optional(),
        email: zod.string().email().max(conversationsQueueClearCreateResponseUserOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    created_at: zod.string().datetime({}).nullable(),
    updated_at: zod.string().datetime({}).nullable(),
    type: zod
        .enum(['assistant', 'tool_call', 'deep_research', 'slack'])
        .describe(
            '* `assistant` - Assistant\n* `tool_call` - Tool call\n* `deep_research` - Deep research\n* `slack` - Slack'
        ),
    is_internal: zod
        .boolean()
        .nullable()
        .describe(
            'Whether this conversation was created during an impersonated session (e.g., by support agents). Internal conversations are hidden from customers.'
        ),
    slack_thread_key: zod
        .string()
        .nullable()
        .describe("Unique key for Slack thread: '{workspace_id}:{channel}:{thread_ts}'"),
    slack_workspace_domain: zod
        .string()
        .nullable()
        .describe("Slack workspace subdomain (e.g. 'posthog' for posthog.slack.com)"),
    messages: zod.array(zod.record(zod.string(), zod.unknown())),
    has_unsupported_content: zod.boolean(),
    agent_mode: zod.string().nullable(),
    pending_approvals: zod
        .array(zod.record(zod.string(), zod.unknown()))
        .describe(
            'Return pending approval cards as structured data.\n\nCombines metadata from conversation.approval_decisions with payload from checkpoint\ninterrupts (single source of truth for payload data).'
        ),
})

/**
 * List tickets with person data attached.
 */
export const ConversationsTicketsListParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ConversationsTicketsListQueryParams = zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const ConversationsTicketsListResponse = zod.object({
    count: zod.number(),
    next: zod.string().url().nullish(),
    previous: zod.string().url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.string(),
            ticket_number: zod.number(),
            channel_source: zod
                .enum(['widget', 'email', 'slack'])
                .describe('* `widget` - Widget\n* `email` - Email\n* `slack` - Slack'),
            distinct_id: zod.string(),
            status: zod
                .enum(['new', 'open', 'pending', 'on_hold', 'resolved'])
                .optional()
                .describe(
                    '* `new` - New\n* `open` - Open\n* `pending` - Pending\n* `on_hold` - On hold\n* `resolved` - Resolved'
                ),
            priority: zod
                .union([
                    zod.enum(['low', 'medium', 'high']).describe('* `low` - Low\n* `medium` - Medium\n* `high` - High'),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
            assignee: zod
                .object({
                    id: zod.string(),
                    type: zod.string(),
                })
                .describe('Serializer for ticket assignment (user or role).'),
            anonymous_traits: zod.unknown().optional(),
            ai_resolved: zod.boolean().optional(),
            escalation_reason: zod.string().nullish(),
            created_at: zod.string().datetime({}),
            updated_at: zod.string().datetime({}),
            message_count: zod.number(),
            last_message_at: zod.string().datetime({}).nullable(),
            last_message_text: zod.string().nullable(),
            unread_team_count: zod.number(),
            unread_customer_count: zod.number(),
            session_id: zod.string().nullable(),
            session_context: zod.unknown(),
            sla_due_at: zod.string().datetime({}).nullish(),
            slack_channel_id: zod.string().nullable(),
            slack_thread_ts: zod.string().nullable(),
            slack_team_id: zod.string().nullable(),
            person: zod
                .object({
                    id: zod.string(),
                    name: zod.string(),
                    distinct_ids: zod.array(zod.string()),
                    properties: zod.record(zod.string(), zod.unknown()),
                    created_at: zod.string().datetime({}),
                    is_identified: zod.boolean(),
                })
                .describe('Minimal person serializer for embedding in ticket responses.')
                .nullable(),
        })
    ),
})

export const ConversationsTicketsCreateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ConversationsTicketsCreateBody = zod.object({
    status: zod
        .enum(['new', 'open', 'pending', 'on_hold', 'resolved'])
        .optional()
        .describe(
            '* `new` - New\n* `open` - Open\n* `pending` - Pending\n* `on_hold` - On hold\n* `resolved` - Resolved'
        ),
    priority: zod
        .union([
            zod.enum(['low', 'medium', 'high']).describe('* `low` - Low\n* `medium` - Medium\n* `high` - High'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    anonymous_traits: zod.unknown().optional(),
    ai_resolved: zod.boolean().optional(),
    escalation_reason: zod.string().nullish(),
    sla_due_at: zod.string().datetime({}).nullish(),
})

/**
 * Get single ticket and mark as read by team.
 */
export const ConversationsTicketsRetrieveParams = zod.object({
    id: zod.string().describe('A UUID string identifying this ticket.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ConversationsTicketsRetrieveResponse = zod.object({
    id: zod.string(),
    ticket_number: zod.number(),
    channel_source: zod
        .enum(['widget', 'email', 'slack'])
        .describe('* `widget` - Widget\n* `email` - Email\n* `slack` - Slack'),
    distinct_id: zod.string(),
    status: zod
        .enum(['new', 'open', 'pending', 'on_hold', 'resolved'])
        .optional()
        .describe(
            '* `new` - New\n* `open` - Open\n* `pending` - Pending\n* `on_hold` - On hold\n* `resolved` - Resolved'
        ),
    priority: zod
        .union([
            zod.enum(['low', 'medium', 'high']).describe('* `low` - Low\n* `medium` - Medium\n* `high` - High'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    assignee: zod
        .object({
            id: zod.string(),
            type: zod.string(),
        })
        .describe('Serializer for ticket assignment (user or role).'),
    anonymous_traits: zod.unknown().optional(),
    ai_resolved: zod.boolean().optional(),
    escalation_reason: zod.string().nullish(),
    created_at: zod.string().datetime({}),
    updated_at: zod.string().datetime({}),
    message_count: zod.number(),
    last_message_at: zod.string().datetime({}).nullable(),
    last_message_text: zod.string().nullable(),
    unread_team_count: zod.number(),
    unread_customer_count: zod.number(),
    session_id: zod.string().nullable(),
    session_context: zod.unknown(),
    sla_due_at: zod.string().datetime({}).nullish(),
    slack_channel_id: zod.string().nullable(),
    slack_thread_ts: zod.string().nullable(),
    slack_team_id: zod.string().nullable(),
    person: zod
        .object({
            id: zod.string(),
            name: zod.string(),
            distinct_ids: zod.array(zod.string()),
            properties: zod.record(zod.string(), zod.unknown()),
            created_at: zod.string().datetime({}),
            is_identified: zod.boolean(),
        })
        .describe('Minimal person serializer for embedding in ticket responses.')
        .nullable(),
})

/**
 * Handle ticket updates including assignee changes.
 */
export const ConversationsTicketsUpdateParams = zod.object({
    id: zod.string().describe('A UUID string identifying this ticket.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ConversationsTicketsUpdateBody = zod.object({
    status: zod
        .enum(['new', 'open', 'pending', 'on_hold', 'resolved'])
        .optional()
        .describe(
            '* `new` - New\n* `open` - Open\n* `pending` - Pending\n* `on_hold` - On hold\n* `resolved` - Resolved'
        ),
    priority: zod
        .union([
            zod.enum(['low', 'medium', 'high']).describe('* `low` - Low\n* `medium` - Medium\n* `high` - High'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    anonymous_traits: zod.unknown().optional(),
    ai_resolved: zod.boolean().optional(),
    escalation_reason: zod.string().nullish(),
    sla_due_at: zod.string().datetime({}).nullish(),
})

export const ConversationsTicketsUpdateResponse = zod.object({
    id: zod.string(),
    ticket_number: zod.number(),
    channel_source: zod
        .enum(['widget', 'email', 'slack'])
        .describe('* `widget` - Widget\n* `email` - Email\n* `slack` - Slack'),
    distinct_id: zod.string(),
    status: zod
        .enum(['new', 'open', 'pending', 'on_hold', 'resolved'])
        .optional()
        .describe(
            '* `new` - New\n* `open` - Open\n* `pending` - Pending\n* `on_hold` - On hold\n* `resolved` - Resolved'
        ),
    priority: zod
        .union([
            zod.enum(['low', 'medium', 'high']).describe('* `low` - Low\n* `medium` - Medium\n* `high` - High'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    assignee: zod
        .object({
            id: zod.string(),
            type: zod.string(),
        })
        .describe('Serializer for ticket assignment (user or role).'),
    anonymous_traits: zod.unknown().optional(),
    ai_resolved: zod.boolean().optional(),
    escalation_reason: zod.string().nullish(),
    created_at: zod.string().datetime({}),
    updated_at: zod.string().datetime({}),
    message_count: zod.number(),
    last_message_at: zod.string().datetime({}).nullable(),
    last_message_text: zod.string().nullable(),
    unread_team_count: zod.number(),
    unread_customer_count: zod.number(),
    session_id: zod.string().nullable(),
    session_context: zod.unknown(),
    sla_due_at: zod.string().datetime({}).nullish(),
    slack_channel_id: zod.string().nullable(),
    slack_thread_ts: zod.string().nullable(),
    slack_team_id: zod.string().nullable(),
    person: zod
        .object({
            id: zod.string(),
            name: zod.string(),
            distinct_ids: zod.array(zod.string()),
            properties: zod.record(zod.string(), zod.unknown()),
            created_at: zod.string().datetime({}),
            is_identified: zod.boolean(),
        })
        .describe('Minimal person serializer for embedding in ticket responses.')
        .nullable(),
})

export const ConversationsTicketsPartialUpdateParams = zod.object({
    id: zod.string().describe('A UUID string identifying this ticket.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ConversationsTicketsPartialUpdateBody = zod.object({
    status: zod
        .enum(['new', 'open', 'pending', 'on_hold', 'resolved'])
        .optional()
        .describe(
            '* `new` - New\n* `open` - Open\n* `pending` - Pending\n* `on_hold` - On hold\n* `resolved` - Resolved'
        ),
    priority: zod
        .union([
            zod.enum(['low', 'medium', 'high']).describe('* `low` - Low\n* `medium` - Medium\n* `high` - High'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    anonymous_traits: zod.unknown().optional(),
    ai_resolved: zod.boolean().optional(),
    escalation_reason: zod.string().nullish(),
    sla_due_at: zod.string().datetime({}).nullish(),
})

export const ConversationsTicketsPartialUpdateResponse = zod.object({
    id: zod.string(),
    ticket_number: zod.number(),
    channel_source: zod
        .enum(['widget', 'email', 'slack'])
        .describe('* `widget` - Widget\n* `email` - Email\n* `slack` - Slack'),
    distinct_id: zod.string(),
    status: zod
        .enum(['new', 'open', 'pending', 'on_hold', 'resolved'])
        .optional()
        .describe(
            '* `new` - New\n* `open` - Open\n* `pending` - Pending\n* `on_hold` - On hold\n* `resolved` - Resolved'
        ),
    priority: zod
        .union([
            zod.enum(['low', 'medium', 'high']).describe('* `low` - Low\n* `medium` - Medium\n* `high` - High'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    assignee: zod
        .object({
            id: zod.string(),
            type: zod.string(),
        })
        .describe('Serializer for ticket assignment (user or role).'),
    anonymous_traits: zod.unknown().optional(),
    ai_resolved: zod.boolean().optional(),
    escalation_reason: zod.string().nullish(),
    created_at: zod.string().datetime({}),
    updated_at: zod.string().datetime({}),
    message_count: zod.number(),
    last_message_at: zod.string().datetime({}).nullable(),
    last_message_text: zod.string().nullable(),
    unread_team_count: zod.number(),
    unread_customer_count: zod.number(),
    session_id: zod.string().nullable(),
    session_context: zod.unknown(),
    sla_due_at: zod.string().datetime({}).nullish(),
    slack_channel_id: zod.string().nullable(),
    slack_thread_ts: zod.string().nullable(),
    slack_team_id: zod.string().nullable(),
    person: zod
        .object({
            id: zod.string(),
            name: zod.string(),
            distinct_ids: zod.array(zod.string()),
            properties: zod.record(zod.string(), zod.unknown()),
            created_at: zod.string().datetime({}),
            is_identified: zod.boolean(),
        })
        .describe('Minimal person serializer for embedding in ticket responses.')
        .nullable(),
})

export const ConversationsTicketsDestroyParams = zod.object({
    id: zod.string().describe('A UUID string identifying this ticket.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ConversationsTicketsSuggestReplyCreateParams = zod.object({
    id: zod.string().describe('A UUID string identifying this ticket.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ConversationsTicketsSuggestReplyCreateResponse = zod.object({
    suggestion: zod.string(),
})

/**
 * Get total unread ticket count for the team.

Returns the sum of unread_team_count for all non-resolved tickets.
Cached in Redis for 30 seconds, invalidated on changes.
 */
export const ConversationsTicketsUnreadCountRetrieveParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ConversationsTicketsUnreadCountRetrieveResponse = zod.object({
    id: zod.string(),
    ticket_number: zod.number(),
    channel_source: zod
        .enum(['widget', 'email', 'slack'])
        .describe('* `widget` - Widget\n* `email` - Email\n* `slack` - Slack'),
    distinct_id: zod.string(),
    status: zod
        .enum(['new', 'open', 'pending', 'on_hold', 'resolved'])
        .optional()
        .describe(
            '* `new` - New\n* `open` - Open\n* `pending` - Pending\n* `on_hold` - On hold\n* `resolved` - Resolved'
        ),
    priority: zod
        .union([
            zod.enum(['low', 'medium', 'high']).describe('* `low` - Low\n* `medium` - Medium\n* `high` - High'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    assignee: zod
        .object({
            id: zod.string(),
            type: zod.string(),
        })
        .describe('Serializer for ticket assignment (user or role).'),
    anonymous_traits: zod.unknown().optional(),
    ai_resolved: zod.boolean().optional(),
    escalation_reason: zod.string().nullish(),
    created_at: zod.string().datetime({}),
    updated_at: zod.string().datetime({}),
    message_count: zod.number(),
    last_message_at: zod.string().datetime({}).nullable(),
    last_message_text: zod.string().nullable(),
    unread_team_count: zod.number(),
    unread_customer_count: zod.number(),
    session_id: zod.string().nullable(),
    session_context: zod.unknown(),
    sla_due_at: zod.string().datetime({}).nullish(),
    slack_channel_id: zod.string().nullable(),
    slack_thread_ts: zod.string().nullable(),
    slack_team_id: zod.string().nullable(),
    person: zod
        .object({
            id: zod.string(),
            name: zod.string(),
            distinct_ids: zod.array(zod.string()),
            properties: zod.record(zod.string(), zod.unknown()),
            created_at: zod.string().datetime({}),
            is_identified: zod.boolean(),
        })
        .describe('Minimal person serializer for embedding in ticket responses.')
        .nullable(),
})
