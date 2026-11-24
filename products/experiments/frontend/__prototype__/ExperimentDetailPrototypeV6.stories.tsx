import { Meta, StoryObj } from '@storybook/react'

import { PROTOTYPE_STATUS } from './prototypeData'
import { QuillPrototypeExperimentPageV6, RUN_PROGRESS, SHELL_STATE } from './QuillPrototypeExperimentPageV6'

/** Scratch stories for the experiment detail prototype, round 6. Not committed. */
const meta: Meta<typeof QuillPrototypeExperimentPageV6> = {
    title: 'Prototype/Experiment detail v6',
    component: QuillPrototypeExperimentPageV6,
    parameters: { layout: 'fullscreen', testOptions: { snapshotBrowsers: [] } },
    tags: ['test-skip'],
}
export default meta

type Story = StoryObj<typeof QuillPrototypeExperimentPageV6>

function scrollTo(top: number): Story['play'] {
    return async ({ canvasElement }) => {
        /** The charts set the page height after the first render, so scrolling at once stops short. */
        await new Promise((resolve) => setTimeout(resolve, 1500))
        canvasElement.querySelector<HTMLElement>('[data-attr="prototype-scroll"]')?.scrollTo({ top })
    }
}

export const TargetReached: Story = {
    args: { status: PROTOTYPE_STATUS.running, shell: SHELL_STATE.sidebarClosed, progress: RUN_PROGRESS.targetReached },
}

export const TargetReachedScrolled: Story = { ...TargetReached, play: scrollTo(620) }

export const InProgressSidebarOpen: Story = {
    args: { status: PROTOTYPE_STATUS.running, shell: SHELL_STATE.sidebarOpen, progress: RUN_PROGRESS.inProgress },
}

export const PhoneTargetReached: Story = {
    args: { status: PROTOTYPE_STATUS.running, shell: SHELL_STATE.phone, progress: RUN_PROGRESS.targetReached },
}

export const PhoneTargetReachedScrolled: Story = { ...PhoneTargetReached, play: scrollTo(1400) }

export const PhoneDraft: Story = {
    args: { status: PROTOTYPE_STATUS.draft, shell: SHELL_STATE.phone, progress: RUN_PROGRESS.inProgress },
}

export const PhoneMetricMenuOpen: Story = {
    ...PhoneTargetReached,
    play: async ({ canvasElement }) => {
        await new Promise((resolve) => setTimeout(resolve, 1500))
        canvasElement.querySelector<HTMLElement>('[data-attr="prototype-scroll"]')?.scrollTo({ top: 1100 })
        await new Promise((resolve) => setTimeout(resolve, 300))
        const trigger = [...canvasElement.querySelectorAll<HTMLElement>('[aria-label="Metric actions"]')].find(
            (element) => element.offsetParent !== null
        )
        trigger?.click()
    },
}
