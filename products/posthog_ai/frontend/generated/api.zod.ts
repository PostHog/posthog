/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Unified endpoint that handles both conversation creation and streaming.
 *
 * - If message is provided: Start new conversation processing
 * - If no message: Stream from existing conversation
 */
export const conversationsCreateBodyContentMax = 40000

export const conversationsCreateBodyIsSandboxDefault = false

export const ConversationsCreateBody = /* @__PURE__ */ zod
    .object({
        content: zod.string().max(conversationsCreateBodyContentMax).nullable(),
        conversation: zod.uuid(),
        contextual_tools: zod.record(zod.string(), zod.unknown()).optional(),
        ui_context: zod.unknown().optional(),
        billing_context: zod.unknown().optional(),
        trace_id: zod.uuid(),
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
                'research',
                'flags',
                'llm_analytics',
                'sandbox',
                'user_interview',
                'customer_analytics',
            ])
            .optional()
            .describe(
                '\* `product_analytics` - product_analytics\n\* `sql` - sql\n\* `session_replay` - session_replay\n\* `error_tracking` - error_tracking\n\* `plan` - plan\n\* `execution` - execution\n\* `survey` - survey\n\* `research` - research\n\* `flags` - flags\n\* `llm_analytics` - llm_analytics\n\* `sandbox` - sandbox\n\* `user_interview` - user_interview\n\* `customer_analytics` - customer_analytics'
            ),
        is_sandbox: zod.boolean().default(conversationsCreateBodyIsSandboxDefault),
        resume_payload: zod.unknown().optional(),
    })
    .describe('Serializer for appending a message to an existing conversation without triggering AI processing.')

/**
 * Appends a message to an existing conversation without triggering AI processing.
 * This is used for client-side generated messages that need to be persisted
 * (e.g., support ticket confirmation messages).
 */
export const conversationsAppendMessageCreateBodyContentMax = 10000

export const ConversationsAppendMessageCreateBody = /* @__PURE__ */ zod
    .object({
        content: zod.string().max(conversationsAppendMessageCreateBodyContentMax),
    })
    .describe('Serializer for appending a message to an existing conversation without triggering AI processing.')

/**
 * Cancel the conversation's in-progress LangGraph run.
 */
export const ConversationsCancelPartialUpdateBody = /* @__PURE__ */ zod.looseObject({})

/**
 * Create-or-resume a sandbox conversation — the single sandbox session opener. With `content`, processes the turn (first message, in-progress follow-up, or terminal resume); without `content`, warms a sandbox that idles awaiting the first message. Returns the `(task, run)` handle the frontend opens SSE against. The conversation row is created on first use from the URL id.
 */
export const conversationsOpenCreateBodyContentMax = 40000

export const ConversationsOpenCreateBody = /* @__PURE__ */ zod
    .object({
        content: zod
            .string()
            .max(conversationsOpenCreateBodyContentMax)
            .nullish()
            .describe(
                "The user's message text. Omit or null to warm a sandbox (boot + idle) ahead of the first message."
            ),
        trace_id: zod
            .uuid()
            .optional()
            .describe("Client-generated trace id correlated with the resulting Run's SSE stream."),
        attached_context: zod
            .array(
                zod
                    .object({
                        type: zod
                            .enum([
                                'action',
                                'dashboard',
                                'error_tracking_issue',
                                'evaluation',
                                'event',
                                'insight',
                                'notebook',
                                'text',
                            ])
                            .describe(
                                '\* `action` - action\n\* `dashboard` - dashboard\n\* `error_tracking_issue` - error_tracking_issue\n\* `evaluation` - evaluation\n\* `event` - event\n\* `insight` - insight\n\* `notebook` - notebook\n\* `text` - text'
                            )
                            .describe(
                                'Attachment kind. Entity types carry `id` (+ optional `name`); `text` carries `value`.\n\n\* `action` - action\n\* `dashboard` - dashboard\n\* `error_tracking_issue` - error_tracking_issue\n\* `evaluation` - evaluation\n\* `event` - event\n\* `insight` - insight\n\* `notebook` - notebook\n\* `text` - text'
                            ),
                        id: zod
                            .unknown()
                            .optional()
                            .describe(
                                'Entity identifier — integer for `dashboard`\/`action`, string short_id\/UUID otherwise. Absent for `text`.'
                            ),
                        name: zod
                            .string()
                            .optional()
                            .describe('Optional human-readable label rendered in the context block.'),
                        value: zod.string().optional().describe('Free-text content. Only for `text` attachments.'),
                    })
                    .describe(
                        'One typed attachment carried by a sandbox message.\n\nDEPRECATED PATH — do not extend. This structured `attached_context` (and its server-side wrap in\n`context_wrapper.py`) exists only for the legacy Max conversations bridge and is removed with it;\nthe live path wraps context client-side (`products\/posthog_ai\/frontend\/utils\/posthogContextBlock.ts`).'
                    )
            )
            .optional()
            .describe('Typed PostHog entities (and free text) attached to this message.'),
        initial_permission_mode: zod
            .enum(['default', 'acceptEdits', 'plan', 'bypassPermissions', 'auto'])
            .describe(
                '\* `default` - default\n\* `acceptEdits` - acceptEdits\n\* `plan` - plan\n\* `bypassPermissions` - bypassPermissions\n\* `auto` - auto'
            )
            .optional()
            .describe(
                'Initial permission mode for the sandbox agent session. Defaults to `auto`, which allows safe tool use while preserving explicit confirmations.\n\n\* `default` - default\n\* `acceptEdits` - acceptEdits\n\* `plan` - plan\n\* `bypassPermissions` - bypassPermissions\n\* `auto` - auto'
            ),
        task_id: zod
            .uuid()
            .optional()
            .describe(
                "Bind a brand-new sandbox conversation to an existing Task so the first message resumes that Task's run. Honored only when this request creates the conversation row; ignored for an already-existing conversation."
            ),
    })
    .describe(
        'Request body for `POST \/conversations\/{id}\/open\/`. A string `content` processes a turn; a\nnull\/absent `content` warms a sandbox that idles awaiting the first message.'
    )

export const ConversationsQueueCreateBody = /* @__PURE__ */ zod.looseObject({})

export const ConversationsQueuePartialUpdateBody = /* @__PURE__ */ zod.looseObject({})

export const ConversationsQueueClearCreateBody = /* @__PURE__ */ zod.looseObject({})

/**
 * Run a hybrid (semantic + full-text) RAG search over the PostHog documentation via Inkeep. Returns a markdown body with title, URL, and excerpt for each match for the agent to cite back to the user.
 * @summary Search PostHog documentation
 */
export const DocsSearchBody = /* @__PURE__ */ zod.object({
    query: zod
        .string()
        .describe(
            'Natural-language description of what to find in the PostHog documentation. Inkeep performs hybrid (semantic + full-text) RAG, so phrase the query the way a user would ask the question.'
        ),
})
