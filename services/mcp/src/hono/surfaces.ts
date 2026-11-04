import AGENT_GUIDELINES from '@shared/agent-guidelines.md'
import GUIDELINES from '@shared/guidelines.md'

import { MCP_SERVER_NAME } from '@/lib/constants'
import { POSTHOG_AGENT_RUN_RESOURCE_URI, POSTHOG_AGENT_STATUS_RESOURCE_URI } from '@/resources/ui-apps.generated'
import { POSTHOG_AGENT_TOOL_NAMES } from '@/tools/posthogAgent/names'

/** One MCP endpoint served by the Hono runtime. All surfaces share auth, rate limits, analytics, and the tool catalog. */
export interface McpSurface {
    path: string
    serverName: string
    guidelines: string
    /**
     * Fixed tool roster. When set, the surface serves only these tools, always in tools mode,
     * with `guidelines` as the complete instructions, and no skills, prompts, or context-mill resources.
     */
    fixedTools?: readonly string[]
    /** UI app resources a fixed surface serves. */
    uiAppUris?: readonly string[]
    /** Tools this surface never serves, because another surface owns them. */
    excludedTools: readonly string[]
}

export const MAIN_SURFACE: McpSurface = {
    path: '/mcp',
    serverName: MCP_SERVER_NAME,
    guidelines: GUIDELINES,
    excludedTools: POSTHOG_AGENT_TOOL_NAMES,
}

export const AGENT_SURFACE: McpSurface = {
    path: '/agent',
    serverName: 'posthog-agent',
    guidelines: AGENT_GUIDELINES,
    fixedTools: POSTHOG_AGENT_TOOL_NAMES,
    uiAppUris: [POSTHOG_AGENT_RUN_RESOURCE_URI, POSTHOG_AGENT_STATUS_RESOURCE_URI],
    excludedTools: [],
}
