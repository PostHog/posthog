import { useActions } from 'kea'

import * as magnifyingGlassPng from '@posthog/brand/hoggies/png/magnifying-glass'
import { IconExternal } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'
import type { ProductEmptyStateMode } from 'lib/components/ProductEmptyState/types'

import { ProductKey } from '~/queries/schema/schema-general'

const HedgehogSearching = pngHoggie(magnifyingGlassPng)

// The public leaderboard is built from PostHog's own MCP server, the same data this product shows.
const DEMO_URL = 'https://posthog.com/mcp/leaderboard?utm_medium=in-product&utm_campaign=mcp-analytics-empty-state'

/** For visitors who want to see the product before they have a server to instrument. */
export function MCPSetupDemoCard({ mode, preview }: { mode: ProductEmptyStateMode; preview: boolean }): JSX.Element {
    const { reportSetupInteraction } = useActions(productSetupStatusLogic({ productKey: ProductKey.MCP_ANALYTICS }))
    return (
        <div className="@container flex items-center gap-3 rounded border border-primary bg-surface-primary p-3">
            <HedgehogSearching className="hidden w-11 shrink-0 @min-[24rem]:block" loading="eager" />
            <div className="flex min-w-0 flex-1 flex-col gap-0.5 text-sm">
                <span className="font-semibold">Not running an MCP server yet?</span>
                <span className="text-secondary">
                    See how agents use PostHog's own MCP server: the clients and models that call it, the tools they
                    pick, and how often calls fail.
                </span>
            </div>
            <LemonButton
                size="small"
                type="secondary"
                to={DEMO_URL}
                targetBlank
                sideIcon={<IconExternal />}
                onClick={() => reportSetupInteraction('demo clicked', mode, null, preview)}
                data-attr="mcp-analytics-setup-demo"
            >
                See the demo
            </LemonButton>
        </div>
    )
}
