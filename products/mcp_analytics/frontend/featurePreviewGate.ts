import { FEATURE_FLAGS } from 'lib/constants'

import { FeaturePreviewGateConfig } from '~/types'

export const mcpAnalyticsFeaturePreviewGate: FeaturePreviewGateConfig = {
    flag: FEATURE_FLAGS.MCP_ANALYTICS,
    title: 'Try MCP analytics',
    description:
        'Capture user intent and behaviour patterns to understand what AI agents need from your MCP tools. See tool quality, sessions, and intent clustering.',
    docsURL: 'https://posthog.com/docs/mcp-analytics',
}
