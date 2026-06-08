import type { Meta, StoryObj } from '@storybook/react'
import type { ReactElement } from 'react'

import { McpThemeDecorator } from '@posthog/mcp-ui/storybook/decorator'
import type { ChartTheme } from '@posthog/quill-charts'

import { SingleStepBar } from '../../frontend/insights/funnels/FunnelBarHorizontalChart/SingleStepBar'
import { buildFunnelConversionStep } from '../../frontend/insights/funnels/shared/funnelBarHorizontalShared'

// PostHog brand palette — mirrors services/mcp/src/ui-apps/components/charts/theme.ts
const CHART_COLORS = ['#1d4aff', '#621da6', '#00d683', '#f54e00', '#f7a501', '#dc2626']

const CHART_THEME: ChartTheme = {
    colors: CHART_COLORS,
    backgroundColor: '#ffffff',
    axisColor: '#9ca3af',
    gridColor: 'rgba(128,128,128,0.2)',
    crosshairColor: 'rgba(128,128,128,0.5)',
    tooltipBackground: '#ffffff',
    tooltipColor: '#111827',
}

const FUNNEL_COLOR = '#1d4aff'
const FILLER_COLOR = 'rgba(0, 0, 0, 0.08)'

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

// Renders the chart the same way the MCP app does: one single-band quill bar per step, each showing
// the step's conversion as a fraction of the first step. Fixed pixel width, not width:100% — the
// chart sizes its canvas off a ResizeObserver, which measures 0 for a percentage width at mount in
// the headless snapshot runner and draws nothing.
function FunnelDemo({ steps }: { steps: { name: string; count: number }[] }): ReactElement {
    const firstCount = steps[0]?.count || 1
    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div style={{ display: 'flex', flexDirection: 'column', width: 640 }}>
            {steps.map((step, stepIndex) => {
                const stepData = buildFunnelConversionStep({
                    stepIndex,
                    label: step.name,
                    fractionOfBasis: step.count / firstCount,
                    color: FUNNEL_COLOR,
                    fillerColor: FILLER_COLOR,
                })
                return (
                    <div key={stepIndex} className="pb-3">
                        <div className="flex items-baseline justify-between text-sm">
                            <span className="font-medium">
                                {stepIndex + 1}. {step.name}
                            </span>
                            <span>{Math.round((step.count / firstCount) * 100)}%</span>
                        </div>
                        <SingleStepBar
                            stepData={stepData}
                            theme={CHART_THEME}
                            interactive={false}
                            onSegmentClick={() => {}}
                            renderTooltip={() => null}
                            onError={() => {}}
                        />
                    </div>
                )
            })}
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
