import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { InsightVizStory } from 'scenes/insights/__mocks__/createInsightVizStory'

import __trendsProgress from '~/mocks/fixtures/api/projects/team_id/insights/trendsProgress.json'

import { TrendsProgress } from './TrendsProgress'

type Story = StoryObj<{}>

const meta: Meta = {
    title: 'Insights/TrendsProgress',
    component: TrendsProgress,
    parameters: {
        layout: 'centered',
        mockDate: '2022-08-09',
        featureFlags: [FEATURE_FLAGS.PROGRESS_INSIGHT],
        testOptions: {
            snapshotBrowsers: ['chromium'],
            waitForSelector: '[data-attr="progress-value"]',
        },
    },
}
export default meta

const progressInsight = __trendsProgress as any

/** The target is the first goal line, so each variant just swaps the goal lines out. */
const withGoalLines = (goalLines: { label: string; value: number }[]): any => ({
    ...progressInsight,
    query: {
        ...progressInsight.query,
        source: {
            ...progressInsight.query.source,
            trendsFilter: { ...progressInsight.query.source.trendsFilter, goalLines },
        },
    },
})

export const Default: Story = {
    render: () => <InsightVizStory insight={progressInsight} />,
}

export const TargetBeaten: Story = {
    render: () => <InsightVizStory insight={withGoalLines([{ label: 'Q3 plan', value: 2500 }])} />,
}

export const NoTarget: Story = {
    render: () => <InsightVizStory insight={withGoalLines([])} />,
    parameters: { testOptions: { waitForSelector: '[data-attr="insight-empty-state"]' } },
}
