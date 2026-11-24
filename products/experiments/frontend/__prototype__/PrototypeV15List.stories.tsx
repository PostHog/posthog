import { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { TIMELINE_GROUP, TIMELINE_ZOOM } from './PrototypeExperimentsTimeline'
import { LIST_STATUS, VELOCITY_DOWN } from './prototypeListData'
import { SHELL_STATE } from './QuillPrototypeExperimentPageV12'
import { DEFAULT_FILTERS, LIST_VIEW, QuillPrototypeExperimentsListV14 } from './QuillPrototypeExperimentsListV14'

/** Scratch stories for prototype round 15, experiment list. The list has no change since v14. Not committed. */
const meta: Meta<typeof QuillPrototypeExperimentsListV14> = {
    title: 'Prototype/v15/Experiment list',
    component: QuillPrototypeExperimentsListV14,
    parameters: { layout: 'fullscreen', mockDate: '2026-11-16', testOptions: { snapshotBrowsers: [] } },
    tags: ['test-skip'],
}
export default meta

type Story = StoryObj<typeof QuillPrototypeExperimentsListV14>

export const List: Story = { args: { shell: SHELL_STATE.sidebarClosed } }

export const ListSidebarOpen: Story = { args: { shell: SHELL_STATE.sidebarOpen } }

export const ListFiltered: Story = {
    args: {
        shell: SHELL_STATE.sidebarClosed,
        filters: { ...DEFAULT_FILTERS, status: LIST_STATUS.complete, excludedTags: ['ui'] },
    },
}

export const ListSelected: Story = {
    args: { shell: SHELL_STATE.sidebarClosed },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        const boxes = await canvas.findAllByRole('checkbox')
        await userEvent.click(boxes[1])
        await userEvent.click(boxes[2])
        await userEvent.click(boxes[4])
    },
}

export const ListLaunchesDown: Story = { args: { shell: SHELL_STATE.sidebarClosed, velocity: VELOCITY_DOWN } }

export const Timeline: Story = { args: { shell: SHELL_STATE.sidebarClosed, view: LIST_VIEW.timeline } }

export const TimelineSidebarOpen: Story = { args: { shell: SHELL_STATE.sidebarOpen, view: LIST_VIEW.timeline } }

export const TimelineByCreator: Story = {
    args: { shell: SHELL_STATE.sidebarClosed, view: LIST_VIEW.timeline, group: TIMELINE_GROUP.owner },
}

export const TimelineSixWeeks: Story = {
    args: { shell: SHELL_STATE.sidebarClosed, view: LIST_VIEW.timeline, zoom: TIMELINE_ZOOM.month },
}

export const TimelineSevenMonths: Story = {
    args: {
        shell: SHELL_STATE.sidebarClosed,
        view: LIST_VIEW.timeline,
        zoom: TIMELINE_ZOOM.half,
        group: TIMELINE_GROUP.none,
    },
}
