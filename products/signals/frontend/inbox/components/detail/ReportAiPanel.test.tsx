import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { makeReport } from '../../__mocks__/inboxMocks'
import { inboxTaskKickoffLogic } from '../../inboxTaskKickoffLogic'
import { ReportAiPanel } from './ReportAiPanel'

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

    it('offers a way back instead of the generic composer when the report is gone', () => {
        // A reload keeps the `inbox-report` panel option in the URL but not the report it was about.
        render(<ReportAiPanel panelId="panel" />)

        expect(screen.getByText('No report selected')).toBeInTheDocument()
        expect(screen.queryByTestId('generic-task-composer')).not.toBeInTheDocument()
    })

    it('shows the report composer once a report is open', () => {
        logic.actions.openReportDiscussion(makeReport({ id: 'report-1' }), 'https://app/report-1')

        render(<ReportAiPanel panelId="panel" />)

        expect(screen.getByTestId('report-composer')).toBeInTheDocument()
        expect(screen.queryByText('No report selected')).not.toBeInTheDocument()
    })
})
