import type { AgentBadge } from './types'

export const POSTHOG_AGENT: AgentBadge = { name: 'PostHog' }

/** Activity entries written through the PostHog MCP server carry this under the sentence. */
export const MCP_VIA = 'via PostHog MCP'
