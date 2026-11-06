import { useActions } from 'kea'

import * as basketballCoachPng from '@posthog/brand/hoggies/png/basketball-coach'

import { pngHoggie } from 'lib/brand/hoggies'
import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'
import type { ProductEmptyStateMode } from 'lib/components/ProductEmptyState/types'

import { ProductKey } from '~/queries/schema/schema-general'

import { HedgehogTipCard } from '../components/HedgehogTipCard'

const HedgehogCoach = pngHoggie(basketballCoachPng)

// The public leaderboard is built from PostHog's own MCP server, the same data this product shows.
const DEMO_URL = 'https://posthog.com/mcp/leaderboard?utm_medium=in-product&utm_campaign=mcp-analytics-empty-state'

/** For visitors who want to see the product before they have a server to instrument. */
export function MCPSetupDemoCard({ mode, preview }: { mode: ProductEmptyStateMode; preview: boolean }): JSX.Element {
    const { reportSetupInteraction } = useActions(productSetupStatusLogic({ productKey: ProductKey.MCP_ANALYTICS }))
    return (
        <HedgehogTipCard
            Hedgehog={HedgehogCoach}
            title="Not running an MCP server yet?"
            body="See how agents use PostHog's own MCP server in our demo (yes, we had to rank the robots in a leaderboard)."
            link={{
                label: 'MCP Leaderboard',
                to: DEMO_URL,
                dataAttr: 'mcp-analytics-setup-demo',
                onClick: () => reportSetupInteraction('demo clicked', mode, null, preview),
            }}
        />
    )
}
