import { Meta, StoryObj } from '@storybook/react'

import { PROTOTYPE_STATUS } from './prototypeData'
import { PrototypeExperimentPage } from './PrototypeExperimentPage'

/** Scratch stories for the experiment detail prototype. Not committed. */
const meta: Meta<typeof PrototypeExperimentPage> = {
    title: 'Prototype/Experiment detail v1',
    component: PrototypeExperimentPage,
    parameters: { layout: 'fullscreen', testOptions: { snapshotBrowsers: [] } },
    tags: ['test-skip'],
}
export default meta

type Story = StoryObj<typeof PrototypeExperimentPage>

export const Running: Story = { args: { status: PROTOTYPE_STATUS.running } }

export const RunningScrolled: Story = {
    args: { status: PROTOTYPE_STATUS.running },
    play: async ({ canvasElement }) => {
        const scroller = canvasElement.querySelector<HTMLElement>('[data-attr="prototype-scroll"]')
        scroller?.scrollTo({ top: 420 })
    },
}

export const Paused: Story = { args: { status: PROTOTYPE_STATUS.paused } }

export const Draft: Story = { args: { status: PROTOTYPE_STATUS.draft } }

export const Complete: Story = { args: { status: PROTOTYPE_STATUS.complete } }
