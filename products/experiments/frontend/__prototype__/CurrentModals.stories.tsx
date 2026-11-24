import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import MultipleMetricsMeta from 'scenes/experiments/stories/ExperimentWithMultipleMetrics.stories'

/** Scratch: today's experiment page on the rail shell; a script opens the End experiment modal. Not committed. */
const meta: Meta = {
    ...MultipleMetricsMeta,
    title: 'Prototype/Current modals',
    parameters: { ...MultipleMetricsMeta.parameters, featureFlags: [FEATURE_FLAGS.TODAY_RAIL_NAV] },
    tags: ['test-skip'],
}
export default meta

type Story = StoryObj<{}>

export const EndExperiment: Story = {}
