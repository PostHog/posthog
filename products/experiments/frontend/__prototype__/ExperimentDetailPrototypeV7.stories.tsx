import { Meta, StoryObj } from '@storybook/react'

import { PROTOTYPE_STATUS } from './prototypeData'
import { QuillPrototypeExperimentPageV7, RUN_PROGRESS, SHELL_STATE } from './QuillPrototypeExperimentPageV7'

/** Scratch stories for the experiment detail prototype, round 7. Not committed. */
const meta: Meta<typeof QuillPrototypeExperimentPageV7> = {
    title: 'Prototype/Experiment detail v7',
    component: QuillPrototypeExperimentPageV7,
    parameters: { layout: 'fullscreen', testOptions: { snapshotBrowsers: [] } },
    tags: ['test-skip'],
}
export default meta

type Story = StoryObj<typeof QuillPrototypeExperimentPageV7>

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

export const ScrolledInPrimary: Story = { ...TargetReached, play: scrollTo(560) }

export const ScrolledInSecondary: Story = { ...TargetReached, play: scrollTo(99999) }

export const Phone: Story = {
    args: { status: PROTOTYPE_STATUS.running, shell: SHELL_STATE.phone, progress: RUN_PROGRESS.targetReached },
}

export const PhoneScrolledInPrimary: Story = { ...Phone, play: scrollTo(1250) }

export const PhoneScrolledInSecondary: Story = { ...Phone, play: scrollTo(99999) }

export const PhoneStatusMenuOpen: Story = {
    ...Phone,
    play: async ({ canvasElement }) => {
        await new Promise((resolve) => setTimeout(resolve, 1500))
        canvasElement.querySelector<HTMLElement>('[aria-label="Experiment status"]')?.click()
    },
}
