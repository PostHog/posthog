import { Meta, StoryObj } from '@storybook/react'

import type { MCPIntentClusterApi, MCPIntentClusterToolEntryApi } from '../generated/api.schemas'
import { RoutingBar } from './RoutingBar'

function tools(pairs: [string, number, number?][]): MCPIntentClusterToolEntryApi[] {
    return pairs.map(([tool, pct, errorRatePct = 0]) => ({
        tool,
        count: pct,
        pct,
        errors: Math.round((pct * errorRatePct) / 100),
        error_rate_pct: errorRatePct,
    }))
}

function cluster(tool_distribution: MCPIntentClusterToolEntryApi[]): MCPIntentClusterApi {
    return {
        id: 1,
        label: 'example intent group',
        intent_count: 1,
        session_count: 1,
        call_count: 100,
        error_count: 0,
        error_rate_pct: 0,
        routing_entropy: 0,
        tool_distribution,
        sample_intents: [],
        journey: null,
        switches: [],
        self_retries: [],
    }
}

const meta: Meta<typeof RoutingBar> = {
    title: 'Products/MCP Analytics/RoutingBar',
    component: RoutingBar,
}
export default meta

type Story = StoryObj<typeof RoutingBar>

/** The common case: most real intent groups call exactly one tool. */
export const SingleTool: Story = {
    args: { cluster: cluster(tools([['execute-sql', 100]])) },
}

export const Concentrated: Story = {
    args: {
        cluster: cluster(
            tools([
                ['exec', 88],
                ['skill-get', 12],
            ])
        ),
    },
}

export const Spread: Story = {
    args: {
        cluster: cluster(
            tools([
                ['exec', 34],
                ['execute-sql', 26],
                ['read-data-schema', 22],
                ['query-trends', 10],
                ['insight-query', 8],
            ])
        ),
    },
}

/** Error rates ride in the tooltip, not the fill — the row and detail table carry them. */
export const WithFailingTool: Story = {
    args: {
        cluster: cluster(
            tools([
                ['exec', 60],
                ['cdp-functions-list', 40, 50],
            ])
        ),
    },
}

export const NoToolsRecorded: Story = {
    args: { cluster: cluster([]) },
}
