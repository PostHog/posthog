import type { Meta, StoryObj } from '@storybook/react'

import { scoutRubricReferenceFixture } from './scoutRubricFixtures'
import { ScoutRubricReference } from './ScoutRubricReference'

const meta: Meta<typeof ScoutRubricReference> = {
    title: 'Scenes-App/Inbox/ScoutRubricReference',
    component: ScoutRubricReference,
    args: { reference: scoutRubricReferenceFixture },
}
export default meta

type Story = StoryObj<typeof ScoutRubricReference>

export const CapturedReference: Story = {}

export const TruncatedReference: Story = {
    args: {
        reference: {
            ...scoutRubricReferenceFixture,
            instructions_truncated: true,
            reference_limits: { omitted_files: 1, truncated_files: [] },
        },
    },
}
