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

// LemonBanner is a CSS container, so it collapses to its content's minimum width without an
// explicitly sized parent - `#storybook-root` is `display: inline-block` and gives it none.
const Template: StoryFn<typeof SourceDestinationsBanner> = () => (
    <div className="w-200">
        <SourceDestinationsBanner />
    </div>
)

export const Default = Template.bind({})

// Keep a sized story root so visual tests can verify the banner stays absent without the flag.
// `#storybook-root` is `display: inline-block`, so it needs an explicit width as well as height -
// a height-only box still collapses to zero width and the screenshot target stays invisible.
export const FlagOff: StoryFn<typeof SourceDestinationsBanner> = () => (
    <div className="h-px w-px">
        <SourceDestinationsBanner />
    </div>
)
FlagOff.parameters = { featureFlags: [] }
