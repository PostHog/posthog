import { Meta, StoryObj } from '@storybook/react'

import { PROTOTYPE_STATUS } from './prototypeData'
import { QuillPrototypeExperimentPageV11, RUN_PROGRESS, SHELL_STATE } from './QuillPrototypeExperimentPageV11'

/** Scratch stories for the experiment detail prototype, round 11: reorderable panels. Not committed. */
const meta: Meta<typeof QuillPrototypeExperimentPageV11> = {
    title: 'Prototype/Experiment detail v11',
    component: QuillPrototypeExperimentPageV11,
    parameters: { layout: 'fullscreen', testOptions: { snapshotBrowsers: [] } },
    tags: ['test-skip'],
}
export default meta

type Story = StoryObj<typeof QuillPrototypeExperimentPageV11>

export const TargetReached: Story = {
    args: { status: PROTOTYPE_STATUS.running, shell: SHELL_STATE.sidebarClosed, progress: RUN_PROGRESS.targetReached },
}

export const SidebarOpen: Story = {
    args: { status: PROTOTYPE_STATUS.running, shell: SHELL_STATE.sidebarOpen, progress: RUN_PROGRESS.targetReached },
}

export const Reordered: Story = {
    args: { ...TargetReached.args, panelOrder: ['settings', 'health', 'exposures', 'hypothesis'] },
}

export const ReorderedSidebarOpen: Story = {
    args: { ...SidebarOpen.args, panelOrder: ['settings', 'health', 'exposures', 'hypothesis'] },
}

export const InProgress: Story = {
    args: { status: PROTOTYPE_STATUS.running, shell: SHELL_STATE.sidebarClosed, progress: RUN_PROGRESS.inProgress },
}
