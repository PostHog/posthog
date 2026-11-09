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
                chip={{
                    id: 'feature_flag:new-checkout-flow',
                    type: 'feature_flag',
                    key: 'new-checkout-flow',
                    pageId: 12,
                    label: 'new-checkout-flow',
                }}
                onRemove={() => {}}
            />
            <QuillAttachedContextChip
                chip={{ id: 'experiment:17', type: 'experiment', key: 17, label: 'Checkout button color' }}
                onRemove={() => {}}
            />
            <QuillAttachedContextChip chip={{ id: 'text:note', type: 'text', label: 'Only count paid plans' }} />
        </div>
    ),
}
export default meta

type Story = StoryObj<typeof QuillAttachedContextChip>

export const LinkCurrentPageAndPlain: Story = {}
