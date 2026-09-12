import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import { INBOX_EVENTS } from '../../inboxAnalytics'
import { inboxBulkActionsLogic } from '../../logics/inboxBulkActionsLogic'
import { SignalReport, SignalReportStatus } from '../../types'
import { SELECTION_HOLD_MS } from '../../utils/reportSelection'
import { ReportCard } from './ReportCard'

jest.mock('posthog-js')

function makeReport(id: string, overrides: Partial<SignalReport> = {}): SignalReport {
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
        ...overrides,
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

    /** Properties of the last `Inbox selection mode entered` event, if one was captured. */
    function lastSelectionEntry(): Record<string, unknown> | undefined {
        const calls = (posthog.capture as jest.Mock).mock.calls.filter(
            ([event]) => event === INBOX_EVENTS.SELECTION_MODE_ENTERED
        )
        return calls[calls.length - 1]?.[1]
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

    test.each([
        ['cmd-click', { metaKey: true }],
        ['ctrl-click', { ctrlKey: true }],
        ['cmd-shift-click', { metaKey: true, shiftKey: true }],
        ['ctrl-shift-click', { ctrlKey: true, shiftKey: true }],
    ])('leaves %s to the browser with or without a selection', (_name, modifiers) => {
        expect(fireEvent.click(cardLink(), modifiers)).toBe(true)
        expect(openedReport()).toBe(false)
        expect(logic.values.selectedReportIds).toEqual([])
        expect(lastSelectionEntry()).toBeUndefined()

        act(() => logic.actions.setSelectedReportIds(['r-1']))

        expect(fireEvent.click(cardLink(), modifiers)).toBe(true)
        expect(openedReport()).toBe(false)
        expect(logic.values.selectedReportIds).toEqual(['r-1'])
        expect(lastSelectionEntry()).toBeUndefined()
    })

    it('toggles on a plain click once the list is in selection mode', () => {
        act(() => logic.actions.setSelectedReportIds(['r-1']))
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

    it('records the entry method when a shift-click starts the selection', () => {
        // The rendered order, which a shift-range measures itself against.
        logic.actions.setVisibleReportIds(['r-1'])

        fireEvent.click(cardLink(), { shiftKey: true })

        expect(logic.values.selectedReportIds).toEqual(['r-1'])
        expect(lastSelectionEntry()).toMatchObject({ entry_method: 'shift_click' })
    })

    it('leaves a cmd-click on the nested scout link to the browser', () => {
        // The card rendered for every other test names no scout, so it carries no nested link.
        cleanup()
        render(
            <ReportCard
                report={{
                    ...makeReport('r-2'),
                    source_products: ['signals_scout'],
                    scout_name: 'signals-scout-web-vitals',
                }}
                selectable
            />
        )
        const scoutLink = screen.getByText('Web vitals').closest('a') as HTMLElement

        // `fireEvent` returns false once anything calls `preventDefault`, which is what would
        // cancel the browser's open-in-a-new-tab gesture.
        expect(fireEvent.click(scoutLink, { metaKey: true })).toBe(true)
        expect(logic.values.selectedReportIds).toEqual([])
    })

    it('does not show a checkbox on hover or when selected', () => {
        fireEvent.mouseEnter(cardLink())
        expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()

        act(() => logic.actions.setSelectedReportIds(['r-1']))
        expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()

        expect(logic.values.selectedReportIds).toEqual(['r-1'])
    })

    it('does not offer selection for a resolved report', () => {
        cleanup()
        render(<ReportCard report={makeReport('r-2', { status: SignalReportStatus.RESOLVED })} selectable />)

        fireEvent.click(screen.getByText('Report r-2').closest('a') as HTMLElement, { metaKey: true })

        expect(logic.values.selectedReportIds).toEqual([])
    })

    it('locks the selection while a bulk action is running', () => {
        const setState = jest.spyOn(api.signalReports, 'setState').mockReturnValue(new Promise<never>(() => {}))
        act(() => {
            logic.actions.setSelectedReportIds(['r-1'])
            logic.actions.bulkDismiss({ reason: 'other', note: '', correctedRepository: null })
        })

        expect(fireEvent.click(cardLink(), { metaKey: true })).toBe(true)
        expect(fireEvent.click(cardLink(), { ctrlKey: true })).toBe(true)
        expect(fireEvent.click(cardLink())).toBe(false)
        expect(logic.values.selectedReportIds).toEqual(['r-1'])
        setState.mockRestore()
    })
})
