import GUIDELINES from '@shared/guidelines.md'

import { MCP_EXEC_SKILLS_FEATURE_FLAG } from '@/hono/constants'
import { InstructionsBuilder } from '@/hono/instructions'
import type { MCPRequestContext } from '@/hono/mcp-context'
import { MCPClientProfile } from '@/lib/client-detection'
import { getToolsForFeatures } from '@/tools/toolDefinitions'

// Must match CLIENT_INFO, the consumer header and the one-team `scoped_teams` token in products/webmcp/backend/logic/.
const CLIENT_NAME = 'posthog-webmcp'
const CONSUMER = 'webmcp'
const SCOPED_TEAMS = [1]

export const APP_ORIGIN_PLACEHOLDER = '__POSTHOG_APP_ORIGIN__'
export const PROJECT_ID_PLACEHOLDER = '__POSTHOG_PROJECT_ID__'

const APP_PROJECT_URL = /https:\/\/(?:us|eu|app)\.posthog\.com\/project\/\d+/g
const UNHANDLED_APP_REFERENCE = /(?:us|eu|app)\.posthog\.com|\/project\/\d/

export interface WebMcpExecToolDefinition {
    name: string
    description: string
    inputSchema: Record<string, unknown>
}

/** Assumes no flag-gated, AI-consent or business knowledge tools. The skills flag is set
 *  because its rollout covers every user, so change this map if that rollout changes. */
export function renderWebMcpExecTool(): WebMcpExecToolDefinition {
    const toolFeatureFlags = { [MCP_EXEC_SKILLS_FEATURE_FLAG]: true }
    const requestContext: MCPRequestContext = {
        mcpClientName: CLIENT_NAME,
        mcpConsumer: CONSUMER,
        mode: 'cli',
        authMethod: 'oauth',
    }
    const toolNames = getToolsForFeatures({ featureFlags: toolFeatureFlags, scopedTeams: SCOPED_TEAMS })
    const tool = new InstructionsBuilder(GUIDELINES).buildExecToolEntry({
        allTools: toolNames.map((name) => ({ name })),
        renderUiEnabled: false,
        businessKnowledgeContent: undefined,
        clientProfile: new MCPClientProfile({ clientName: CLIENT_NAME, consumer: CONSUMER }),
        requestContext,
        sessionContext: null,
        toolFeatureFlags,
    })

    const serialized = JSON.stringify({
        name: tool.name,
        description: tool.description ?? '',
        inputSchema: tool.inputSchema,
    }).replace(APP_PROJECT_URL, `${APP_ORIGIN_PLACEHOLDER}/project/${PROJECT_ID_PLACEHOLDER}`)
    const unhandled = serialized.match(UNHANDLED_APP_REFERENCE)
    if (unhandled) {
        throw new Error(
            `The WebMCP exec tool names an app URL or project id that the browser cannot fill in: "${unhandled[0]}". ` +
                `Write it as ${APP_ORIGIN_PLACEHOLDER}/project/${PROJECT_ID_PLACEHOLDER} in scripts/lib/render-webmcp-exec-tool.ts.`
        )
    }
    return JSON.parse(serialized) as WebMcpExecToolDefinition
}
