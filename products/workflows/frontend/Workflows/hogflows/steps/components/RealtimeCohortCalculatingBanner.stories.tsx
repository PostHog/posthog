import { Meta, StoryFn } from '@storybook/react'

import { RealtimeCohortStatusApi } from 'products/workflows/frontend/generated/api.schemas'

import { RealtimeCohortCalculatingBanner } from './RealtimeCohortCalculatingBanner'

const meta: Meta<typeof RealtimeCohortCalculatingBanner> = {
    title: 'Products/Workflows/Steps/Realtime cohort calculating banner',
    component: RealtimeCohortCalculatingBanner,
}
export default meta

const Template: StoryFn<{ status: RealtimeCohortStatusApi }> = ({ status }) => (
    <div className="w-120">
        <RealtimeCohortCalculatingBanner status={status} />
    </div>
)

export const Calculating = Template.bind({})
Calculating.args = { status: { id: 2, name: 'Viewed pricing', state: 'building', percent_complete: 40 } }

export const NeedsAttention = Template.bind({})
NeedsAttention.args = { status: { id: 2, name: 'Viewed pricing', state: 'needs_attention', percent_complete: null } }
