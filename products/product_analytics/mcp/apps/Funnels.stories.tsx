import type { Meta, StoryObj } from '@storybook/react'
import type { ReactElement } from 'react'

import { McpThemeDecorator } from '@posthog/mcp-ui/storybook/decorator'
import { BarChart, type ChartTheme, type TooltipContext, TooltipSurface } from '@posthog/quill-charts'

import {
    buildFunnelStepsBarConfig,
    buildFunnelStepsBars,
    type FunnelStepsBarRow,
} from '../../frontend/insights/funnels/shared/funnelStepsBarShared'

// PostHog brand palette — mirrors services/mcp/src/ui-apps/components/charts/theme.ts
const CHART_THEME: ChartTheme = {
    colors: ['#1d4aff', '#621da6', '#00d683', '#f54e00', '#f7a501', '#dc2626'],
    backgroundColor: '#ffffff',
    axisColor: '#9ca3af',
    gridColor: 'rgba(128,128,128,0.2)',
    crosshairColor: 'rgba(128,128,128,0.5)',
    tooltipBackground: '#ffffff',
    tooltipColor: '#111827',
}
const FUNNEL_COLOR = '#1d4aff'

const NOOP = (): void => {}

const CHART_CONFIG = buildFunnelStepsBarConfig({ maxCategoryLabelWidth: 120, tooltipPlacement: 'cursor' })

function renderTooltip(rows: FunnelStepsBarRow[]) {
    return function FunnelTooltip(ctx: TooltipContext): ReactElement | null {
        const row = rows[ctx.dataIndex]
        if (!row) {
            return null
        }
        return (
            <TooltipSurface>
                <div className="font-semibold mb-1">
                    {row.stepIndex + 1}. {row.name}
                </div>
                <div>
                    {row.count.toLocaleString()} ({Math.round(row.fractionOfBasis * 100)}% of first step)
                </div>
            </TooltipSurface>
        )
    }
}

const meta: Meta = {
    title: 'MCP Apps/Funnels',
    decorators: [McpThemeDecorator],
    parameters: {
        testOptions: {
            skipDarkMode: true,
        },
    },
}
export default meta

type Story = StoryObj<{}>

// Fixed pixel size, not width:100% — the chart sizes its canvas off a ResizeObserver, which measures
// 0 for a percentage width at mount in the headless snapshot runner and draws nothing.
function FunnelDemo({ steps }: { steps: { name: string; count: number }[] }): ReactElement {
    const { series, labels, rows } = buildFunnelStepsBars(steps, { color: FUNNEL_COLOR })
    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div style={{ width: 640, height: 320, display: 'flex', flexDirection: 'column' }}>
            <BarChart
                series={series}
                labels={labels}
                theme={CHART_THEME}
                config={CHART_CONFIG}
                tooltip={renderTooltip(rows)}
                onError={NOOP}
            />
        </div>
    )
}

export const ThreeStep: Story = {
    render: () => (
        <FunnelDemo
            steps={[
                { name: 'Pageview', count: 1000 },
                { name: 'Signed up', count: 420 },
                { name: 'Activated', count: 180 },
            ]}
        />
    ),
    name: 'Three-step funnel',
}

export const SteepDropoff: Story = {
    render: () => (
        <FunnelDemo
            steps={[
                { name: 'Visited', count: 5000 },
                { name: 'Added to cart', count: 800 },
                { name: 'Checkout started', count: 240 },
                { name: 'Purchased', count: 96 },
            ]}
        />
    ),
    name: 'Steep drop-off',
}
