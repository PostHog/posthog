import type { Meta, StoryObj } from '@storybook/react'
import { fireEvent, waitFor, within } from '@testing-library/dom'

import { mswDecorator } from '~/mocks/browser'

import { makeReport, mockReviewers } from '../../__mocks__/inboxMocks'
import { mockScoutSuggestionSet } from '../../__mocks__/scoutConfigs'
import { SignalReport, SignalReportStatus } from '../../types'
import { ReportCard } from './ReportCard'
import { ReportContextMenu } from './ReportContextMenu'

// The right-click menu on a report row. It renders only while open, so no scene story shows it.

const readyReport = makeReport({
    id: 'context-menu-ready',
    title: 'fix(invites): Handle incomplete recipient data in team invite form',
    status: SignalReportStatus.READY,
    priority: 'P1',
    actionability: 'immediately_actionable',
    created_at: '2026-06-10T09:00:00Z',
    updated_at: '2026-06-10T09:00:00Z',
})

const dismissedReport = makeReport({
    id: 'context-menu-dismissed',
    title: 'fix(billing): Stop double-charging annual plans on renewal',
    status: SignalReportStatus.SUPPRESSED,
    priority: 'P2',
    created_at: '2026-06-09T09:00:00Z',
    updated_at: '2026-06-10T09:00:00Z',
})

function ReportRowWithMenu({ report }: { report: SignalReport }): JSX.Element {
    return (
        <div className="w-[520px]">
            <ReportContextMenu report={report} sectionKey="needs-decision">
                <ReportCard report={report} />
            </ReportContextMenu>
        </div>
    )
}

const meta: Meta<typeof ReportRowWithMenu> = {
    title: 'Scenes-App/Inbox/ReportContextMenu',
    component: ReportRowWithMenu,
    parameters: {
        mockDate: '2026-06-11',
        testOptions: { snapshotTargetSelector: '.primitive-menu-content', waitForLoadersToDisappear: false },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:id/signals/reports/': { count: 0, next: null, previous: null, results: [] },
                '/api/projects/:id/signals/reports/available_reviewers/': () => [200, mockReviewers],
                '/api/projects/:id/signals/scout/configs/': () => [200, []],
                '/api/projects/:id/signals/scout/suggestions/': () => [200, mockScoutSuggestionSet()],
                '/api/projects/:id/tasks/@me/config/': { ai_run_preferences: {}, resolved_ai_run_defaults: {} },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof ReportRowWithMenu>

async function openMenu(canvasElement: HTMLElement, title: RegExp): Promise<void> {
    fireEvent.contextMenu(await within(canvasElement).findByText(title), { clientX: 240, clientY: 40 })
    await waitFor(() => {
        if (!document.querySelector('.primitive-menu-content')) {
            throw new Error('The context menu is not open yet')
        }
    })
}

export const ReadyReport: Story = {
    args: { report: readyReport },
    play: async ({ canvasElement }) => {
        await openMenu(canvasElement, /incomplete recipient data/)
    },
}

export const DismissedReport: Story = {
    args: { report: dismissedReport },
    play: async ({ canvasElement }) => {
        await openMenu(canvasElement, /double-charging annual plans/)
    },
}
