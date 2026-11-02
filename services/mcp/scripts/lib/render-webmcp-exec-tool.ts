import type { Tool as McpTool } from '@modelcontextprotocol/sdk/types.js'
import GUIDELINES from '@shared/guidelines.md'

import { MCP_EXEC_SKILLS_FEATURE_FLAG } from '@/hono/constants'
import { InstructionsBuilder } from '@/hono/instructions'
import type { MCPRequestContext } from '@/hono/mcp-context'
import { MCPClientProfile } from '@/lib/client-detection'
import { getToolsForFeatures } from '@/tools/toolDefinitions'

// Must match CLIENT_INFO and the x-posthog-mcp-consumer header in products/webmcp/backend/logic/mcp_server.py.
const CLIENT_NAME = 'posthog-webmcp'
const CONSUMER = 'webmcp'

/** Renders the `exec` tool that `tools/list` advertises to WebMCP for a team with
 *  no flag-gated tools, no AI-consent tools and no business knowledge sources.
 *  The skills flag is set because its rollout covers every user. Change this map
 *  if that rollout changes. */
export function renderWebMcpExecTool(): McpTool {
    const toolFeatureFlags = { [MCP_EXEC_SKILLS_FEATURE_FLAG]: true }
    const requestContext: MCPRequestContext = {
        mcpClientName: CLIENT_NAME,
        mcpConsumer: CONSUMER,
        mode: 'cli',
        authMethod: 'oauth',
    }
    return new InstructionsBuilder(GUIDELINES).buildExecToolEntry({
        allTools: getToolsForFeatures({ featureFlags: toolFeatureFlags }).map((name) => ({ name })),
        renderUiEnabled: false,
        businessKnowledgeContent: undefined,
        clientProfile: new MCPClientProfile({ clientName: CLIENT_NAME, consumer: CONSUMER }),
        requestContext,
        sessionContext: null,
        toolFeatureFlags,
    })
}
