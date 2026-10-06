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

// Keep a sized story root so visual tests can verify the banner stays absent without the flag.
export const FlagOff: StoryFn<typeof SourceDestinationsBanner> = () => (
    <div className="h-px">
        <SourceDestinationsBanner />
    </div>
)
FlagOff.parameters = { featureFlags: [] }
