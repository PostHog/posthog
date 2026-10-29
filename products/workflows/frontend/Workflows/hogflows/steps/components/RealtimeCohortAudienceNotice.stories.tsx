import { Meta, StoryFn } from '@storybook/react'

import { BlastRadiusApi } from 'products/workflows/frontend/generated/api.schemas'

import { RealtimeCohortAudienceNotice } from './RealtimeCohortAudienceNotice'

const meta: Meta<typeof RealtimeCohortAudienceNotice> = {
    title: 'Products/Workflows/Steps/Realtime cohort audience notice',
    component: RealtimeCohortAudienceNotice,
}
export default meta

const base: BlastRadiusApi = { affected: 3, total: 5, limit: 1000, dedupe_key: null, confirm_token: 'token' }

const Template: StoryFn<{ blastRadius: BlastRadiusApi }> = ({ blastRadius }) => (
    <div className="w-120">
        <RealtimeCohortAudienceNotice blastRadius={blastRadius} />
    </div>
)

export const RealtimeCohortAlone = Template.bind({})
RealtimeCohortAlone.args = {
    blastRadius: {
        ...base,
        realtime_cohort: { id: 2, name: 'Viewed pricing', state: 'ready', percent_complete: null },
    },
}
