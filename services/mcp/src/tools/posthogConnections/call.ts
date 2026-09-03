import { z } from 'zod'

import { buildForwardedContext, resolveConnectionTarget, seedForwardedContext } from '@/lib/connection-forwarding'
import { ExecCommandError } from '@/lib/errors'
import { getToolDefinition } from '@/tools/toolDefinitions'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const schema = z.object({
    connection_id: z
        .string()
        .describe(
            'Id of the PostHog connection to run through. List them with `integrations-list` filtered by `kind=posthog`.'
        ),
    tool: z
        .string()
        .describe(
            'Name of the PostHog tool to run in the connected project, e.g. `execute-sql` or `insights-list`. The connected project runs the same tools this one does, so inspect the schema locally with `info <tool>` first.'
        ),
    arguments: z
        .looseObject({})
        .optional()
        .describe(
            'Arguments for that tool, exactly as you would pass them locally. Omit any project id — it is filled in from the connection.'
        ),
})

/** Tools that cannot mean anything on the far side of a connection, mapped to what to do instead. */
const UNSUPPORTED_TOOLS: Record<string, string> = {
    'posthog-connection-call': 'A connection cannot be chained through another connection.',
    'posthog-connection-forward': 'A connection cannot be chained through another connection.',
    'switch-project': 'A connection points at one fixed project. Use a different connection to reach a different one.',
    'switch-organization':
        'A connection points at one fixed project. Use a different connection to reach a different one.',
}

/**
 * Refuse a tool that feeds data to an LLM unless the *connected* organization approved AI
 * processing.
 *
 * Locally this gate lives in the tool list, which is filtered per session — but a tool named here is
 * looked up in the registry, and the approval that matters belongs to the other organization anyway.
 * Several of these endpoints gate server-side on a feature flag and scopes only, so nothing further
 * down would catch it. `getAiConsentGiven` resolves through the forwarded context, so it reads the
 * target's setting, and it answers `undefined` for anything it cannot read — which stays refused.
 */
async function assertTargetApprovedAiProcessing(forwarded: Context, toolName: string): Promise<void> {
    let requiresAiConsent: boolean
    try {
        requiresAiConsent = getToolDefinition(toolName).requires_ai_consent === true
    } catch {
        // No catalogued definition, so not one of the AI-consuming tools.
        return
    }
    if (!requiresAiConsent) {
        return
    }

    if ((await forwarded.stateManager.getAiConsentGiven()) !== true) {
        throw new ExecCommandError(
            `\`${toolName}\` sends data to an LLM, and the connected project's organization has not approved AI data processing. Approve it in that organization's settings, or use a tool that does not rely on AI.`,
            'usage'
        )
    }
}

/**
 * Run a PostHog tool against a project reached through a `posthog` connection.
 *
 * The connected project runs the same PostHog build this one does, so its tool catalog is identical
 * and no remote discovery step is needed: an agent inspects `execute-sql` locally, then names it
 * here. `resolveTool` is injected rather than imported so this tool can reach the whole registry
 * without the registry and this file importing each other.
 */
export function createConnectionCallTool(
    resolveTool: (name: string) => ToolBase<ZodObjectAny> | undefined
): ToolBase<typeof schema> {
    return {
        name: 'posthog-connection-call',
        schema,
        handler: async (context: Context, params: z.infer<typeof schema>) => {
            const unsupported = UNSUPPORTED_TOOLS[params.tool]
            if (unsupported) {
                throw new ExecCommandError(
                    `\`${params.tool}\` cannot run through a connection. ${unsupported}`,
                    'usage'
                )
            }

            const target = resolveTool(params.tool)
            if (!target) {
                throw new ExecCommandError(
                    `No PostHog tool named \`${params.tool}\`. Find one with \`search <words>\`, then pass its exact name.`,
                    'unknown_tool'
                )
            }

            // Check the arguments before touching the connection, so a malformed call fails here
            // rather than after a cross-region round trip, as an opaque 400 from the other project.
            const parsedArguments = target.schema.safeParse(params.arguments ?? {})
            if (!parsedArguments.success) {
                throw new ExecCommandError(
                    `Arguments for \`${params.tool}\` are invalid: ${parsedArguments.error.issues
                        .map((issue) => `${issue.path.join('.') || '(root)'}: ${issue.message}`)
                        .join('; ')}`,
                    'usage'
                )
            }

            const localProjectId = await context.stateManager.getProjectId()
            const connectionTarget = await resolveConnectionTarget(context, localProjectId, params.connection_id)
            const forwarded = buildForwardedContext(context, {
                connectionId: params.connection_id,
                localProjectId,
                target: connectionTarget,
            })
            await seedForwardedContext(forwarded, connectionTarget)
            await assertTargetApprovedAiProcessing(forwarded, params.tool)

            const result = await target.handler(forwarded, parsedArguments.data)

            // Name where this ran. Two connections and a local call otherwise return results that
            // look alike, and the whole point of the tool is that they came from somewhere else.
            return {
                ran_in: {
                    project_id: connectionTarget.project_id,
                    project_name: connectionTarget.project_name,
                    organization_name: connectionTarget.organization_name,
                    region: connectionTarget.region,
                },
                tool: params.tool,
                result,
            }
        },
    }
}
