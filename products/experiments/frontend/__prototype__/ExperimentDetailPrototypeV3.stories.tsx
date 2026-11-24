import { Meta, StoryObj } from '@storybook/react'

import { PROTOTYPE_STATUS } from './prototypeData'
import { DETAILS_STATE, QuillPrototypeExperimentPage } from './QuillPrototypeExperimentPage'

/** Scratch stories for the experiment detail prototype, round 3 on Quill. Not committed. */
const meta: Meta<typeof QuillPrototypeExperimentPage> = {
    title: 'Prototype/Experiment detail v3 quill',
    component: QuillPrototypeExperimentPage,
    parameters: { layout: 'fullscreen', testOptions: { snapshotBrowsers: [] } },
    tags: ['test-skip'],
}
export default meta

type Story = StoryObj<typeof QuillPrototypeExperimentPage>

export const Running: Story = { args: { status: PROTOTYPE_STATUS.running, detailsState: DETAILS_STATE.closed } }

export const RunningDetailsOpen: Story = {
    args: { status: PROTOTYPE_STATUS.running, detailsState: DETAILS_STATE.open },
}

export const Draft: Story = { args: { status: PROTOTYPE_STATUS.draft, detailsState: DETAILS_STATE.closed } }

export const Complete: Story = { args: { status: PROTOTYPE_STATUS.complete, detailsState: DETAILS_STATE.closed } }
