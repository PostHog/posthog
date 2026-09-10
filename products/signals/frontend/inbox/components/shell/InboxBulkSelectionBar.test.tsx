import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { inboxBulkActionsLogic } from '../../logics/inboxBulkActionsLogic'
import { InboxBulkSelectionBar } from './InboxBulkSelectionBar'

describe('InboxBulkSelectionBar', () => {
    let logic: ReturnType<typeof inboxBulkActionsLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = inboxBulkActionsLogic()
        logic.mount()
    })

    afterEach(() => {
        cleanup()
        logic.unmount()
    })

    // The bar holds a count and no titles, so its dialogs have to count reports at every size. The
    // single-report copy would print the "Untitled report" placeholder over a report that has a title.
    it.each([
        { button: 'Dismiss', reportIds: ['a'], heading: 'Dismiss 1 report?' },
        { button: 'Dismiss', reportIds: ['a', 'b'], heading: 'Dismiss 2 reports?' },
        { button: 'Resolve', reportIds: ['a'], heading: 'Resolve 1 report?' },
        { button: 'Resolve', reportIds: ['a', 'b'], heading: 'Resolve 2 reports?' },
    ])(
        '$button counts the selection in its dialog at $reportIds.length selected',
        async ({ button, reportIds, heading }) => {
            logic.actions.setSelectedReportIds(reportIds)
            render(<InboxBulkSelectionBar />)

            fireEvent.click(screen.getByText(button))

            expect(await screen.findByText(heading)).toBeInTheDocument()
        }
    )
})
