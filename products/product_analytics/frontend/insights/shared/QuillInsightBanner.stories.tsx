import type { Meta, StoryObj } from '@storybook/react'

import { QuillInsightBanner } from './QuillInsightBanner'

type Story = StoryObj<typeof QuillInsightBanner>
const meta: Meta<typeof QuillInsightBanner> = {
    title: 'Insights/QuillInsightBanner',
    component: QuillInsightBanner,
    parameters: { testOptions: { snapshotBrowsers: [] } },
}
export default meta

export const Info: Story = {
    args: {
        tone: 'info',
        children: "The explanation is hidden because your changes affect the chart's data. Undo them to see it again.",
    },
}

export const WarningWithActionAndClose: Story = {
    args: {
        tone: 'warning',
        children:
            "This insight's date range goes beyond your 1-year data retention, so events older than that aren't included.",
        action: { children: 'Upgrade plan', to: '/organization/billing' },
        onClose: () => {},
    },
}

export const NarrowWithActionAndClose: Story = {
    ...WarningWithActionAndClose,
    decorators: [
        (Story) => (
            <div className="w-80">
                <Story />
            </div>
        ),
    ],
}
