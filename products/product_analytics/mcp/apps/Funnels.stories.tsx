import type { Meta, StoryObj } from '@storybook/react'
import type { ReactElement } from 'react'

import { CHART_THEME, FILLER_COLOR, FUNNEL_COLOR } from '@posthog/mcp-ui'
import { McpThemeDecorator } from '@posthog/mcp-ui/storybook/decorator'

import { SingleStepBar } from '../../frontend/insights/funnels/FunnelBarHorizontalChart/SingleStepBar'
import {
    buildFunnelConversionStep,
    funnelConversionRate,
} from '../../frontend/insights/funnels/shared/funnelBarHorizontalShared'

const NOOP = (): void => {}
const NO_TOOLTIP = (): null => null

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

// Fixed pixel width, not width:100% — the chart sizes its canvas off a ResizeObserver, which measures
// 0 for a percentage width at mount in the headless snapshot runner and draws nothing.
function FunnelDemo({ steps }: { steps: { name: string; count: number }[] }): ReactElement {
    const firstCount = steps[0]?.count ?? 0
    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div style={{ display: 'flex', flexDirection: 'column', width: 640 }}>
            {steps.map((step, stepIndex) => {
                const fractionOfBasis = funnelConversionRate(step.count, firstCount)
                const stepData = buildFunnelConversionStep({
                    stepIndex,
                    label: step.name,
                    fractionOfBasis,
                    color: FUNNEL_COLOR,
                    fillerColor: FILLER_COLOR,
                })
                return (
                    <div key={stepIndex} className="pb-3">
                        <div className="flex items-baseline justify-between text-sm">
                            <span className="font-medium">
                                {stepIndex + 1}. {step.name}
                            </span>
                            <span>{Math.round(fractionOfBasis * 100)}%</span>
                        </div>
                        <SingleStepBar
                            stepData={stepData}
                            theme={CHART_THEME}
                            interactive={false}
                            onSegmentClick={NOOP}
                            renderTooltip={NO_TOOLTIP}
                            onError={NOOP}
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
