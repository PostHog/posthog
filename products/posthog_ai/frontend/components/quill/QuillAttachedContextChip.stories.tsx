import type { Meta, StoryObj } from '@storybook/react'

import { urls } from 'scenes/urls'

import { QuillAttachedContextChip } from './QuillAttachedContextChip'

const meta: Meta<typeof QuillAttachedContextChip> = {
    title: 'Products/PostHog AI/Quill context chip',
    component: QuillAttachedContextChip,
    parameters: {
        pageUrl: urls.experiment(17),
        testOptions: { snapshotBrowsers: [] },
    },
    render: () => (
        <div data-quill className="flex flex-wrap items-center gap-1 p-4">
            <QuillAttachedContextChip
                item={{ type: 'feature_flag', key: 12, label: 'new-checkout-flow' }}
                label="new-checkout-flow"
                onRemove={() => {}}
            />
            <QuillAttachedContextChip
                item={{ type: 'experiment', key: 17, label: 'Checkout button color' }}
                label="Checkout button color"
                onRemove={() => {}}
            />
            <QuillAttachedContextChip
                item={{ type: 'text', value: 'Only count paid plans' }}
                label="Only count paid plans"
            />
        </div>
    ),
}
export default meta

type Story = StoryObj<typeof QuillAttachedContextChip>

export const LinkCurrentPageAndPlain: Story = {}
