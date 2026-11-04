import { z } from 'zod'

import { markExecPayload, type ToolResultPayload } from '@/lib/build-tool-result'
import { withUiApp } from '@/resources/ui-apps'
import { POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY, type Context, type ToolBase, type ZodObjectAny } from '@/tools/types'

import {
    POSTHOG_AGENT_CANCEL_TOOL_NAME,
    POSTHOG_AGENT_REPLY_TOOL_NAME,
    POSTHOG_AGENT_RUN_TOOL_NAME,
    POSTHOG_AGENT_STATUS_TOOL_NAME,
} from './names'
import {
    type AgentOperation,
    agentOperationsPath,
    formatAgentOperationText,
    getAgentOperation,
    STATUS_DEFAULT_WAIT_SECONDS,
    STATUS_MAX_WAIT_SECONDS,
    waitForAgentOperationChange,
} from './operations'

const CLIENT_REQUEST_ID_DESCRIPTION =
    'A new unique identifier for this request, for example a UUID. If the response is lost, send the same call again with the same value. Do not reuse the value for a different request.'
const OPERATION_ID_DESCRIPTION = 'The operation id that posthog-agent-run returned.'
const OPERATION_PROJECT_ID_DESCRIPTION =
    'The project id of the operation, from the `project.id` field of the operation.'

const projectIdSchema = z.coerce.number().int().positive()

export const PostHogAgentRunSchema = z.object({
    goal: z
        .string()
        .trim()
        .min(1)
        .describe(
            'The goal for PostHog Agent, in plain language. Include what the user wants to know or get done, and what a good answer contains.'
        ),
    client_request_id: z.string().trim().min(1).max(200).describe(CLIENT_REQUEST_ID_DESCRIPTION),
    context: z
        .string()
        .optional()
        .describe(
            'Optional background text for the goal, for example relevant code, a local diff summary, or earlier findings. PostHog Agent cannot read local files.'
        ),
    posthog_conversation_id: z
        .string()
        .uuid()
        .optional()
        .describe(
            'Optional PostHog AI conversation id from an earlier operation. Set it to continue in the same conversation. Omit it to start a new conversation.'
        ),
    repository: z
        .string()
        .regex(/^[\w.-]+\/[\w.-]+$/, 'Use the format organization/repository.')
        .optional()
        .describe(
            'Optional GitHub repository in the format organization/repository. Set it when the goal needs the code. The project GitHub integration must have access to it.'
        ),
    ref: z
        .string()
        .min(1)
        .optional()
        .describe(
            'Optional branch, tag, or commit in the repository. The default branch is used when it is omitted. The commit stays fixed for the whole operation.'
        ),
    project_id: projectIdSchema
        .optional()
        .describe('Optional PostHog project id. The active project of this connection is used when it is omitted.'),
})

export const PostHogAgentStatusSchema = z.object({
    operation_id: z.string().trim().min(1).describe(OPERATION_ID_DESCRIPTION),
    project_id: projectIdSchema.describe(OPERATION_PROJECT_ID_DESCRIPTION),
    cursor: z
        .string()
        .optional()
        .describe('The cursor from the last operation response. Omit it on the first status call.'),
    wait_seconds: z
        .number()
        .int()
        .min(0)
        .max(STATUS_MAX_WAIT_SECONDS)
        .default(STATUS_DEFAULT_WAIT_SECONDS)
        .describe(
            `How long this status request waits for a change, from 0 to ${STATUS_MAX_WAIT_SECONDS} seconds. The request returns early when the operation changes. This limit applies to one status request, not to the task.`
        ),
})

export const PostHogAgentReplySchema = z.object({
    operation_id: z.string().trim().min(1).describe(OPERATION_ID_DESCRIPTION),
    project_id: projectIdSchema.describe(OPERATION_PROJECT_ID_DESCRIPTION),
    message: z
        .string()
        .trim()
        .min(1)
        .describe('The answer to the question of the operation, an approval decision, or a correction from the user.'),
    client_request_id: z.string().trim().min(1).max(200).describe(CLIENT_REQUEST_ID_DESCRIPTION),
})

export const PostHogAgentCancelSchema = z.object({
    operation_id: z.string().trim().min(1).describe(OPERATION_ID_DESCRIPTION),
    project_id: projectIdSchema.describe(OPERATION_PROJECT_ID_DESCRIPTION),
})

type RunResult = AgentOperation & { _posthogUrl: string; [POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]: string }

/** Text for the model and the whole operation as structured content, without a UI app for each call. */
function operationPayload(operation: AgentOperation): ToolResultPayload {
    return markExecPayload({
        content: [{ type: 'text', text: formatAgentOperationText(operation) }],
        structuredContent: { ...operation },
    })
}

export const postHogAgentRunHandler = async (
    context: Context,
    params: z.infer<typeof PostHogAgentRunSchema>
): Promise<RunResult> => {
    const projectId = params.project_id ?? (await context.stateManager.getProjectId())
    const operation = await context.api.request<AgentOperation>({
        method: 'POST',
        path: agentOperationsPath(projectId),
        body: {
            goal: params.goal,
            client_request_id: params.client_request_id,
            ...(params.context ? { context: params.context } : {}),
            ...(params.posthog_conversation_id ? { conversation_id: params.posthog_conversation_id } : {}),
            ...(params.repository ? { repository: params.repository } : {}),
            ...(params.ref ? { ref: params.ref } : {}),
        },
    })
    return {
        ...operation,
        _posthogUrl: operation.posthog_url,
        [POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]: formatAgentOperationText(operation),
    }
}

export const postHogAgentStatusHandler = async (
    context: Context,
    params: z.infer<typeof PostHogAgentStatusSchema>
): Promise<ToolResultPayload> => {
    const operation = await waitForAgentOperationChange(
        (cursor) => getAgentOperation(context, params.project_id, params.operation_id, cursor),
        params.cursor,
        params.wait_seconds
    )
    return operationPayload(operation)
}

export const postHogAgentReplyHandler = async (
    context: Context,
    params: z.infer<typeof PostHogAgentReplySchema>
): Promise<ToolResultPayload> => {
    const operation = await context.api.request<AgentOperation>({
        method: 'POST',
        path: agentOperationsPath(params.project_id, params.operation_id, 'reply'),
        body: { message: params.message, client_request_id: params.client_request_id },
    })
    return operationPayload(operation)
}

export const postHogAgentCancelHandler = async (
    context: Context,
    params: z.infer<typeof PostHogAgentCancelSchema>
): Promise<ToolResultPayload> => {
    const operation = await context.api.request<AgentOperation>({
        method: 'POST',
        path: agentOperationsPath(params.project_id, params.operation_id, 'cancel'),
    })
    return operationPayload(operation)
}

const postHogAgentRun = (): ToolBase<typeof PostHogAgentRunSchema, RunResult> =>
    withUiApp('posthog-agent-run', {
        name: POSTHOG_AGENT_RUN_TOOL_NAME,
        schema: PostHogAgentRunSchema,
        handler: postHogAgentRunHandler,
    })

const postHogAgentStatus = (): ToolBase<typeof PostHogAgentStatusSchema, ToolResultPayload> => ({
    name: POSTHOG_AGENT_STATUS_TOOL_NAME,
    schema: PostHogAgentStatusSchema,
    handler: postHogAgentStatusHandler,
})

const postHogAgentReply = (): ToolBase<typeof PostHogAgentReplySchema, ToolResultPayload> => ({
    name: POSTHOG_AGENT_REPLY_TOOL_NAME,
    schema: PostHogAgentReplySchema,
    handler: postHogAgentReplyHandler,
})

const postHogAgentCancel = (): ToolBase<typeof PostHogAgentCancelSchema, ToolResultPayload> => ({
    name: POSTHOG_AGENT_CANCEL_TOOL_NAME,
    schema: PostHogAgentCancelSchema,
    handler: postHogAgentCancelHandler,
})

export const POSTHOG_AGENT_TOOL_MAP: Record<string, () => ToolBase<ZodObjectAny>> = {
    [POSTHOG_AGENT_RUN_TOOL_NAME]: postHogAgentRun,
    [POSTHOG_AGENT_STATUS_TOOL_NAME]: postHogAgentStatus,
    [POSTHOG_AGENT_REPLY_TOOL_NAME]: postHogAgentReply,
    [POSTHOG_AGENT_CANCEL_TOOL_NAME]: postHogAgentCancel,
}
