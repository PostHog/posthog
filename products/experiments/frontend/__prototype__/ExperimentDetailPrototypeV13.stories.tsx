import { Meta, StoryObj } from '@storybook/react'

import { PROTOTYPE_STATUS } from './prototypeData'
import { QuillPrototypeExperimentPageV13, RUN_PROGRESS, SHELL_STATE } from './QuillPrototypeExperimentPageV13'

/** Scratch stories for the experiment detail prototype, round 13: cards the user can hide and add back. Not committed. */
const meta: Meta<typeof QuillPrototypeExperimentPageV13> = {
    title: 'Prototype/Experiment detail v13',
    component: QuillPrototypeExperimentPageV13,
    parameters: { layout: 'fullscreen', testOptions: { snapshotBrowsers: [] } },
    tags: ['test-skip'],
}
export default meta

type Story = StoryObj<typeof QuillPrototypeExperimentPageV13>

export const AllCards: Story = {
    args: { status: PROTOTYPE_STATUS.running, shell: SHELL_STATE.sidebarClosed, progress: RUN_PROGRESS.targetReached },
}

export const TwoHidden: Story = {
    args: { ...AllCards.args, hiddenPanels: ['health', 'hypothesis'] },
}

export const TwoHiddenSidebarOpen: Story = {
    args: { ...TwoHidden.args, shell: SHELL_STATE.sidebarOpen },
}

export const AllHidden: Story = {
    args: { ...AllCards.args, hiddenPanels: ['exposures', 'health', 'hypothesis', 'settings'] },
}
