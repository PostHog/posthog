import { Meta, StoryObj } from '@storybook/react'

import { PROTOTYPE_STATUS } from './prototypeData'
import { QuillPrototypeExperimentPageV4, SIDEBAR_STATE } from './QuillPrototypeExperimentPageV4'

/** Scratch stories for the experiment detail prototype, round 4: responsive Quill. Not committed. */
const meta: Meta<typeof QuillPrototypeExperimentPageV4> = {
    title: 'Prototype/Experiment detail v4 responsive',
    component: QuillPrototypeExperimentPageV4,
    parameters: { layout: 'fullscreen', testOptions: { snapshotBrowsers: [] } },
    tags: ['test-skip'],
}
export default meta

type Story = StoryObj<typeof QuillPrototypeExperimentPageV4>

export const RunningSidebarClosed: Story = {
    args: { status: PROTOTYPE_STATUS.running, sidebar: SIDEBAR_STATE.closed },
}

export const RunningSidebarOpen: Story = {
    args: { status: PROTOTYPE_STATUS.running, sidebar: SIDEBAR_STATE.open },
}

export const DraftSidebarOpen: Story = {
    args: { status: PROTOTYPE_STATUS.draft, sidebar: SIDEBAR_STATE.open },
}

export const DraftSidebarClosed: Story = {
    args: { status: PROTOTYPE_STATUS.draft, sidebar: SIDEBAR_STATE.closed },
}

export const CompleteSidebarClosed: Story = {
    args: { status: PROTOTYPE_STATUS.complete, sidebar: SIDEBAR_STATE.closed },
}
