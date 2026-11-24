import { Meta, StoryObj } from '@storybook/react'

import { VELOCITY_DOWN, VELOCITY_FLAT, VELOCITY_LOW } from './prototypeListData'
import { SHELL_STATE } from './QuillPrototypeExperimentPageV12'
import { LIST_VIEW, QuillPrototypeExperimentsListV14 } from './QuillPrototypeExperimentsListV14'

/** Scratch stories for the experiment list prototype, round 14: the velocity card. Not committed. */
const meta: Meta<typeof QuillPrototypeExperimentsListV14> = {
    title: 'Prototype/Experiment list v14',
    component: QuillPrototypeExperimentsListV14,
    parameters: { layout: 'fullscreen', mockDate: '2026-11-16', testOptions: { snapshotBrowsers: [] } },
    tags: ['test-skip'],
}
export default meta

type Story = StoryObj<typeof QuillPrototypeExperimentsListV14>

export const LaunchesUp: Story = { args: { shell: SHELL_STATE.sidebarClosed } }

export const LaunchesDown: Story = { args: { shell: SHELL_STATE.sidebarClosed, velocity: VELOCITY_DOWN } }

export const LaunchesFlat: Story = { args: { shell: SHELL_STATE.sidebarClosed, velocity: VELOCITY_FLAT } }

export const FewLaunches: Story = { args: { shell: SHELL_STATE.sidebarClosed, velocity: VELOCITY_LOW } }

export const SidebarOpen: Story = { args: { shell: SHELL_STATE.sidebarOpen } }

export const TimelineSidebarOpen: Story = { args: { shell: SHELL_STATE.sidebarOpen, view: LIST_VIEW.timeline } }
