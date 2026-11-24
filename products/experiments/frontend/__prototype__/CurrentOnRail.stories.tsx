import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import DraftMeta from 'scenes/experiments/stories/DraftExperiment.stories'
import MultipleMetricsMeta from 'scenes/experiments/stories/ExperimentWithMultipleMetrics.stories'

/** Scratch: today's experiment page with the today-rail-nav shell on. Not committed. */
const meta: Meta = {
    ...MultipleMetricsMeta,
    title: 'Prototype/Current on rail',
    parameters: { ...MultipleMetricsMeta.parameters, featureFlags: [FEATURE_FLAGS.TODAY_RAIL_NAV] },
    tags: ['test-skip'],
}
export default meta

type Story = StoryObj<{}>

export const Running: Story = {}

export const Draft: Story = {
    parameters: { ...DraftMeta.parameters, featureFlags: [FEATURE_FLAGS.TODAY_RAIL_NAV] },
    decorators: DraftMeta.decorators,
}
