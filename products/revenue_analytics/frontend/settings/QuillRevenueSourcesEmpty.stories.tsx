import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { QuillRevenueSourcesEmpty, QuillRevenueSourcesEmptyProps } from './QuillRevenueSourcesEmpty'

function RevenueSourcesEmptyStory(props: QuillRevenueSourcesEmptyProps): JSX.Element {
    return (
        <div data-quill className="w-160 p-4">
            <QuillRevenueSourcesEmpty {...props} />
        </div>
    )
}

const meta: Meta<typeof RevenueSourcesEmptyStory> = {
    title: 'Scenes-App/Data Management/Revenue Analytics/Quill sources empty state',
    component: RevenueSourcesEmptyStory,
    args: { onAddEvent: () => {}, onImportFromDataWarehouse: () => {} },
    parameters: {
        featureFlags: [FEATURE_FLAGS.TODAY_RAIL_NAV],
        testOptions: { snapshotBrowsers: [] },
    },
}
export default meta

type Story = StoryObj<typeof RevenueSourcesEmptyStory>

export const NoSources: Story = {}
