import { Meta, StoryObj } from '@storybook/react'

import { PROTOTYPE_STATUS } from './prototypeData'
import { QuillPrototypeExperimentPageV5, RUN_PROGRESS, SIDEBAR_STATE } from './QuillPrototypeExperimentPageV5'

/** Scratch stories for the experiment detail prototype, round 5: sticky status line and summary report. Not committed. */
const meta: Meta<typeof QuillPrototypeExperimentPageV5> = {
    title: 'Prototype/Experiment detail v5 sticky',
    component: QuillPrototypeExperimentPageV5,
    parameters: { layout: 'fullscreen', testOptions: { snapshotBrowsers: [] } },
    tags: ['test-skip'],
}
export default meta

type Story = StoryObj<typeof QuillPrototypeExperimentPageV5>

function scrollTo(top: number): Story['play'] {
    return async ({ canvasElement }) => {
        /** The charts set the page height after the first render, so scrolling at once stops short. */
        await new Promise((resolve) => setTimeout(resolve, 1500))
        canvasElement.querySelector<HTMLElement>('[data-attr="prototype-scroll"]')?.scrollTo({ top })
    }
}

export const TargetReached: Story = {
    args: { status: PROTOTYPE_STATUS.running, sidebar: SIDEBAR_STATE.closed, progress: RUN_PROGRESS.targetReached },
}

export const TargetReachedScrolled: Story = {
    ...TargetReached,
    play: scrollTo(620),
}

export const InProgress: Story = {
    args: { status: PROTOTYPE_STATUS.running, sidebar: SIDEBAR_STATE.open, progress: RUN_PROGRESS.inProgress },
}

export const InProgressScrolled: Story = {
    ...InProgress,
    play: scrollTo(900),
}
