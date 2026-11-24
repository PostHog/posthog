import { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { TIMELINE_GROUP, TIMELINE_ZOOM } from './PrototypeExperimentsTimeline'
import { LIST_STATUS } from './prototypeListData'
import { SHELL_STATE } from './QuillPrototypeExperimentPageV12'
import { DEFAULT_FILTERS, LIST_VIEW, QuillPrototypeExperimentsListV12 } from './QuillPrototypeExperimentsListV12'

/** Scratch stories for the experiment list prototype, round 12: quill list and timeline. Not committed. */
const meta: Meta<typeof QuillPrototypeExperimentsListV12> = {
    title: 'Prototype/Experiment list v12',
    component: QuillPrototypeExperimentsListV12,
    parameters: { layout: 'fullscreen', mockDate: '2026-11-16', testOptions: { snapshotBrowsers: [] } },
    tags: ['test-skip'],
}
export default meta

type Story = StoryObj<typeof QuillPrototypeExperimentsListV12>

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
