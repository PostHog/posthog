import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { actions, kea, path, reducers } from 'kea'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { initKeaTests } from '~/test/init'
import { SidePanelTab } from '~/types'

import { makeReport } from '../../__mocks__/inboxMocks'
import { inboxSceneLogic } from '../../inboxSceneLogic'
import { REPORT_AI_PANEL, inboxTaskKickoffLogic } from '../../inboxTaskKickoffLogic'
import { ReportAiPanel } from './ReportAiPanel'

// The real scene logic loads the inbox on mount; the panel only reads which report is open.
jest.mock('../../inboxSceneLogic', () => ({
    inboxSceneLogic: kea([
        path(['test', 'inboxSceneLogic']),
        actions({ loadSelectedReportSuccess: (report) => ({ report }) }),
        reducers({ selectedReport: [null, { loadSelectedReportSuccess: (_, { report }) => report }] }),
    ]),
}))

jest.mock('./ReportDiscussionComposer', () => ({
    ReportDiscussionComposer: () => <div data-attr="report-composer" />,
}))
// Mirrors the runner's own fallback: with no composer supplied it renders the generic task composer.
jest.mock('products/posthog_ai/frontend/api/runner', () => ({
    SidePanelRunner: ({ composer }: { composer?: React.ReactNode }) => (
        <div>{composer ?? <div data-attr="generic-task-composer" />}</div>
    ),
}))

describe('ReportAiPanel', () => {
    let logic: ReturnType<typeof inboxTaskKickoffLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = inboxTaskKickoffLogic()
        logic.mount()
    })

    afterEach(() => {
        cleanup()
        logic.unmount()
    })

    it('offers a way back instead of the generic composer when no report is open on the page', () => {
        sidePanelStateLogic.actions.openSidePanel(SidePanelTab.Max, REPORT_AI_PANEL)

        render(<ReportAiPanel panelId="panel" />)

        expect(screen.getByText('No report selected')).toBeInTheDocument()
        expect(screen.queryByTestId('generic-task-composer')).not.toBeInTheDocument()
    })

    it('restores the chat from the report open on the page after a reload', () => {
        // A reload keeps the `inbox-report` panel option in the URL hash but not the in-memory chat context.
        sidePanelStateLogic.actions.openSidePanel(SidePanelTab.Max, REPORT_AI_PANEL)
        const scene = inboxSceneLogic()
        scene.mount()
        scene.actions.loadSelectedReportSuccess(makeReport({ id: 'report-1' }))

        render(<ReportAiPanel panelId="panel" />)

        expect(screen.getByTestId('report-composer')).toBeInTheDocument()
        expect(logic.values.reportChatContext?.report.id).toBe('report-1')
        scene.unmount()
    })

    it('shows the report composer once a report is open', () => {
        logic.actions.openReportDiscussion(makeReport({ id: 'report-1' }), 'https://app/report-1')

        render(<ReportAiPanel panelId="panel" />)

        expect(screen.getByTestId('report-composer')).toBeInTheDocument()
        expect(screen.queryByText('No report selected')).not.toBeInTheDocument()
    })
})
