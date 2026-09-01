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

const CASES: [string, MCPIntentClusterApi][] = [
    // Single tool is the common case — most real intent groups call exactly one.
    ['Single tool', cluster(tools([['execute-sql', 100]]))],
    [
        'Concentrated',
        cluster(
            tools([
                ['exec', 88],
                ['skill-get', 12],
            ])
        ),
    ],
    [
        'Spread across many (remainder aggregated)',
        cluster(
            tools([
                ['exec', 34],
                ['execute-sql', 26],
                ['read-data-schema', 22],
                ['query-trends', 10],
                ['insight-query', 8],
            ])
        ),
    ],
    // Error rates ride in the tooltip, not the fill — the row and detail table carry them.
    [
        'With a failing tool',
        cluster(
            tools([
                ['exec', 60],
                ['cdp-functions-list', 40, 50],
            ])
        ),
    ],
    ['No tools recorded (renders nothing)', cluster([])],
]

const meta: Meta<typeof RoutingBar> = {
    title: 'Products/MCP Analytics/RoutingBar',
    component: RoutingBar,
    parameters: {
        layout: 'centered',
        viewMode: 'story',
        // Chromium-only keeps this consistent with the other MCP analytics stories and
        // avoids cross-browser anti-aliasing noise on the thin coloured fill.
        testOptions: { snapshotBrowsers: ['chromium'] },
    },
    // The app resolves this from the shared series palette; the story pins the same
    // first-series colour so it renders what the list actually shows.
    args: { color: 'var(--data-color-1)' },
}
export default meta

type Story = StoryObj<typeof RoutingBar>

/**
 * Every routing shape in one fixed-width column. A single sized story rather than one per
 * case: it documents the states together, and gives the snapshot runner one stable,
 * non-empty target — a story that renders only `null` (the no-tools case) has no element
 * to screenshot and times the runner out.
 */
export const AllVariants: Story = {
    render: (args) => (
        <div className="flex w-[360px] flex-col gap-3 p-2">
            {CASES.map(([label, c]) => (
                <div key={label} className="flex flex-col gap-1">
                    <span className="text-muted text-xs">{label}</span>
                    <RoutingBar {...args} cluster={c} />
                </div>
            ))}
        </div>
    ),
}
