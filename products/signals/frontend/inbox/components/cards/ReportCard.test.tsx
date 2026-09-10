import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { router } from 'kea-router'

import { initKeaTests } from '~/test/init'

import { inboxBulkActionsLogic } from '../../logics/inboxBulkActionsLogic'
import { SignalReport, SignalReportStatus } from '../../types'
import { SELECTION_HOLD_MS } from '../../utils/reportSelection'
import { ReportCard } from './ReportCard'

function makeReport(id: string): SignalReport {
    return {
        id,
        title: `Report ${id}`,
        summary: 'summary',
        status: SignalReportStatus.READY,
        total_weight: 0,
        signal_count: 1,
        relevant_user_count: null,
        artefact_count: 0,
        is_suggested_reviewer: false,
        priority: 'P2',
        source_products: ['error_tracking'],
        created_at: '2026-06-11T10:00:00Z',
        updated_at: '2026-06-11T10:00:00Z',
    } satisfies SignalReport
}

describe('ReportCard', () => {
    let logic: ReturnType<typeof inboxBulkActionsLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = inboxBulkActionsLogic()
        logic.mount()
        render(<ReportCard report={makeReport('r-1')} selectable />)
    })

    afterEach(() => {
        cleanup()
        jest.useRealTimers()
        logic.unmount()
    })

    /** True once a click has followed the card's link through to the report detail. */
    function openedReport(): boolean {
        return router.values.location.pathname.includes('r-1')
    }

    /**
     * jsdom has no `PointerEvent`, and `fireEvent.pointerDown` drops the button and the
     * coordinates the hold reads, so dispatch a `MouseEvent` under the pointer event's name.
     */
    function firePointer(type: string, init: MouseEventInit): void {
        fireEvent(cardLink(), new MouseEvent(type, { bubbles: true, ...init }))
    }

    /** The card body, which is the link a plain click follows. */
    function cardLink(): HTMLElement {
        return screen.getByText('Report r-1').closest('a') as HTMLElement
    }

    it('opens the report on a plain click, leaving the selection empty', () => {
        fireEvent.click(cardLink())

        expect(openedReport()).toBe(true)
        expect(logic.values.selectedReportIds).toEqual([])
    })

    it('selects on cmd-click instead of opening the report', () => {
        fireEvent.click(cardLink(), { metaKey: true })

        expect(openedReport()).toBe(false)
        expect(logic.values.selectedReportIds).toEqual(['r-1'])
    })

    it('toggles on a plain click once the list is in selection mode', () => {
        fireEvent.click(cardLink(), { metaKey: true })
        fireEvent.click(cardLink())

        expect(openedReport()).toBe(false)
        expect(logic.values.selectedReportIds).toEqual([])
    })

    it('selects on a press and hold, and swallows the click that ends it', () => {
        jest.useFakeTimers()
        firePointer('pointerdown', { button: 0, clientX: 10, clientY: 10 })
        jest.advanceTimersByTime(SELECTION_HOLD_MS)
        firePointer('pointerup', {})

        expect(logic.values.selectedReportIds).toEqual(['r-1'])

        fireEvent.click(cardLink())
        expect(openedReport()).toBe(false)
    })

    it('cancels the hold when the pointer travels, so a scroll never selects', () => {
        jest.useFakeTimers()
        firePointer('pointerdown', { button: 0, clientX: 10, clientY: 10 })
        firePointer('pointermove', { clientX: 10, clientY: 60 })
        jest.advanceTimersByTime(SELECTION_HOLD_MS)

        expect(logic.values.selectedReportIds).toEqual([])
    })

    it('selects from the gutter checkbox', () => {
        fireEvent.click(screen.getByLabelText('Select this report'))

        expect(logic.values.selectedReportIds).toEqual(['r-1'])
    })
})
