import { Meta, StoryFn } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { SourceDestinationsBanner } from './SourceDestinationsBanner'

const meta: Meta<typeof SourceDestinationsBanner> = {
    title: 'Data Warehouse/SourceDestinationsBanner',
    component: SourceDestinationsBanner,
    parameters: {
        featureFlags: [FEATURE_FLAGS.WAREHOUSE_MULTI_DESTINATION],
    },
    tags: ['autodocs'],
}
export default meta

const Template: StoryFn<typeof SourceDestinationsBanner> = () => <SourceDestinationsBanner />

export const Default = Template.bind({})

// Without the flag the destinations scene is not reachable, so the banner stays out of the way.
export const FlagOff = Template.bind({})
FlagOff.parameters = { featureFlags: [] }
FlagOff.tags = ['test-skip']
