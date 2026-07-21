import * as roboHogPng from '@posthog/brand/hoggies/png/robo-hog'
import { IconMCP } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import type { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'
import { FEATURE_FLAGS } from 'lib/constants'

import { ProductKey } from '~/queries/schema/schema-general'

import { mcpAnalyticsOnboardingLogic } from '../mcpAnalyticsOnboardingLogic'
import { MCP_ANALYTICS_DOCS_URL, MCPListeningIndicator } from '../onboarding/MCPAnalyticsInstall'
import { MCPToolCallPreview } from './MCPToolCallPreview'

const HedgehogRoboHog = pngHoggie(roboHogPng)

export const mcpAnalyticsEmptyState: SceneProductEmptyState = {
    statusLogic: mcpAnalyticsOnboardingLogic,
    // The whole product is behind this flag; its scene-level preview gate handles the flag-off case.
    featureFlag: FEATURE_FLAGS.MCP_ANALYTICS,
    config: {
        productKey: ProductKey.MCP_ANALYTICS,
        productName: 'MCP analytics',
        icon: <IconMCP />,
        accentColor: 'var(--color-product-mcp-analytics-light)',
        accentColorDark: 'var(--color-product-mcp-analytics-dark)',
        hedgehog: HedgehogRoboHog,
        text: {
            'needs-setup': {
                headline: 'Know how agents actually use your tools',
                lead: 'Capture every MCP tool call, argument and result, so you can see which tools agents reach for, where they fail, and how long each call takes.',
                hint: 'Point the wizard at your MCP server. LLM inference is on us, no API key needed:',
            },
            'waiting-for-data': {
                headline: "You're connected. Now make a tool call",
                lead: "We've seen your MCP server connect, but it hasn't handled a tool call yet. Trigger a tool from your agent and this page fills in on its own.",
                hint: 'Instrumenting another server? Re-run setup:',
            },
        },
        wizard: { slug: 'mcp-analytics', pinProjectId: true },
        docsUrl: MCP_ANALYTICS_DOCS_URL,
        manualSetupUrl: 'https://posthog.com/docs/mcp-analytics/installation',
        previewLabel: 'Tool calls, once connected',
        Preview: MCPToolCallPreview,
        statusIndicator: <MCPListeningIndicator />,
    },
}
