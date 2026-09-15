import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import type { ReportMetricApi } from 'products/signals/frontend/generated/api.schemas'

import { INBOX_EVENTS } from '../../inboxAnalytics'
import { inboxBulkActionsLogic } from '../../logics/inboxBulkActionsLogic'
import { SignalReport, SignalReportStatus } from '../../types'
import { SELECTION_HOLD_MS } from '../../utils/reportSelection'
import { ReportCard } from './ReportCard'

jest.mock('posthog-js')
jest.mock('lib/components/TZLabel', () => ({
    TZLabel: ({ time }: { time: string }) => <span>{time}</span>,
}))

function makeReport(id: string, overrides: Partial<SignalReport> = {}): SignalReport {
    return {
        id,
        title: `Report ${id}`,
        summary: 'summary',
        status: SignalReportStatus.READY,
        total_weight: 0,
        signal_count: 1,
        artefact_count: 0,
        is_suggested_reviewer: false,
        priority: 'P2',
        source_products: ['error_tracking'],
        created_at: '2026-06-11T10:00:00Z',
        updated_at: '2026-06-11T10:00:00Z',
        ...overrides,
    } satisfies SignalReport
}

function makeMetric(overrides: Partial<ReportMetricApi> = {}): ReportMetricApi {
    return {
        metric_id: 'impact',
        title: 'Users affected',
        kind: 'affected_users',
        role: 'primary',
        value: 42,
        value_at: '2026-08-28T12:00:00Z',
        value_format: 'count',
        unit: 'users',
        caption: null,
        ...overrides,
    }
}

function enableRedesign(enabled = true): void {
    featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.INBOX_REDESIGN, FEATURE_FLAGS.SIGNALS_REPORT_METRICS], {
        [FEATURE_FLAGS.INBOX_REDESIGN]: enabled,
        [FEATURE_FLAGS.SIGNALS_REPORT_METRICS]: enabled,
    })
}

describe('ReportCard', () => {
    let logic: ReturnType<typeof inboxBulkActionsLogic.build>

    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
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

        // React queues its scheduler work in the fake timer queue, and leaving fake timers drops
        // whatever is still queued. No state update in a later test would flush then.
        act(() => {
            jest.runOnlyPendingTimers()
        })
    })

    it('cancels the hold when the pointer travels, so a scroll never selects', () => {
        jest.useFakeTimers()
        firePointer('pointerdown', { button: 0, clientX: 10, clientY: 10 })
        firePointer('pointermove', { clientX: 10, clientY: 60 })
        jest.advanceTimersByTime(SELECTION_HOLD_MS)

        expect(logic.values.selectedReportIds).toEqual([])

        act(() => {
            jest.runOnlyPendingTimers()
        })
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

    it('shows the affected-user snapshot in a redesigned row and prefers it over the primary metric', async () => {
        // The harness renders a card for every test; these assert against their own.
        cleanup()
        enableRedesign()
        const user = userEvent.setup()
        const report = makeReport('r-2', {
            metrics: [
                makeMetric({
                    metric_id: 'conversion',
                    title: 'Conversion rate',
                    kind: 'conversion_rate',
                    value: 34,
                    value_at: null,
                    value_format: 'percentage',
                    unit: null,
                }),
                makeMetric({ metric_id: 'affected-users', role: 'supporting', series: [3, 5, 9] }),
            ],
        })

        const { container } = render(<ReportCard report={report} />)

        expect(screen.getByText('42')).toBeInTheDocument()
        expect(screen.queryByText('Users affected')).not.toBeInTheDocument()
        expect(screen.queryByText('34%')).not.toBeInTheDocument()
        expect(container.querySelectorAll('[data-attr="report-card-impact-sparkline"] > *')).toHaveLength(3)

        await user.hover(screen.getByText('42'))
        expect(await screen.findByText('Users affected')).toBeInTheDocument()
        expect(await screen.findByText('2026-08-28T12:00:00Z')).toBeInTheDocument()
    })

    // The row breaks the figure away from its unit word, and each format splits at a different place.
    const rowPartCases: [string, ReportMetricApi, string, string][] = [
        [
            'a duration in seconds',
            makeMetric({ kind: 'duration', value: 287, value_format: 'duration', unit: 's' }),
            '287',
            'seconds',
        ],
        [
            'a failure rate',
            makeMetric({ kind: 'error_rate', value: 40, value_format: 'percentage', unit: 'failure' }),
            '40%',
            'failure',
        ],
    ]
    it.each(rowPartCases)('prints %s as a figure above its unit word', (_label, metric, figure, unitWord) => {
        // The harness renders a card for every test; these assert against their own.
        cleanup()
        enableRedesign()
        const { container } = render(<ReportCard report={makeReport('r-2', { metrics: [metric] })} />)

        const block = container.querySelector('[data-attr="report-card-impact-metric"]')
        expect(block).not.toBeNull()
        expect(within(block as HTMLElement).getByText(figure)).toBeInTheDocument()
        expect(within(block as HTMLElement).getByText(unitWord)).toBeInTheDocument()
    })

    it('draws a rate strip as a line instead of bars', () => {
        // The harness renders a card for every test; these assert against their own.
        cleanup()
        enableRedesign()
        const { container } = render(
            <ReportCard
                report={makeReport('r-2', {
                    metrics: [
                        makeMetric({
                            kind: 'error_rate',
                            value: 40,
                            value_format: 'percentage',
                            unit: 'failure',
                            series: [35, 42, 38],
                        }),
                    ],
                })}
            />
        )

        const strip = container.querySelector('[data-attr="report-card-impact-sparkline"]')
        expect(strip?.tagName).toBe('svg')
        expect(strip?.querySelector('polyline')).not.toBeNull()
    })

    it('draws no strip for a single-bucket series but keeps the figure', () => {
        // The harness renders a card for every test; these assert against their own.
        cleanup()
        enableRedesign()
        const { container } = render(
            <ReportCard report={makeReport('r-2', { metrics: [makeMetric({ series: [9] })] })} />
        )

        expect(container.querySelector('[data-attr="report-card-impact-sparkline"]')).toBeNull()
        expect(screen.getByText('42')).toBeInTheDocument()
    })

    it('keeps the timestamp on a redesigned row that has no figure', () => {
        // The harness renders a card for every test; these assert against their own.
        cleanup()
        enableRedesign()
        const { container } = render(<ReportCard report={makeReport('r-2', { metrics: [] })} />)

        expect(container.querySelector('[data-attr="report-card-impact-metric"]')).toBeNull()
        expect(screen.getByText('2026-06-11T10:00:00Z')).toBeInTheDocument()
    })

    it('uses the primary snapshot when there is no affected-user snapshot', () => {
        // The harness renders a card for every test; these assert against their own.
        cleanup()
        enableRedesign()
        const report = makeReport('r-2', {
            metrics: [
                makeMetric({
                    metric_id: 'conversion',
                    title: 'Conversion rate',
                    kind: 'conversion_rate',
                    value: 34,
                    value_at: null,
                    value_format: 'percentage',
                    unit: null,
                }),
            ],
        })

        const { container } = render(<ReportCard report={report} />)

        expect(screen.getByText('34%')).toBeInTheDocument()
        expect(screen.queryByText('Conversion rate')).not.toBeInTheDocument()
        expect(container.querySelector('[data-attr="report-card-impact-metric"]')).not.toBeNull()
    })

    it('does not show a list metric without a stored snapshot, under the legacy design, or with the metrics flag off', () => {
        const report = makeReport('r-2', { metrics: [makeMetric({ value: null, value_at: null })] })

        // The harness renders a card for every test; these assert against their own.
        cleanup()
        enableRedesign()
        const { container, rerender } = render(<ReportCard report={report} />)
        expect(container.querySelector('[data-attr="report-card-impact-metric"]')).toBeNull()

        enableRedesign(false)
        rerender(
            <ReportCard
                report={makeReport('r-2', {
                    metrics: [{ ...report.metrics![0], value: 42 }],
                })}
            />
        )
        expect(container.querySelector('[data-attr="report-card-impact-metric"]')).toBeNull()

        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.INBOX_REDESIGN, FEATURE_FLAGS.SIGNALS_REPORT_METRICS], {
            [FEATURE_FLAGS.INBOX_REDESIGN]: true,
            [FEATURE_FLAGS.SIGNALS_REPORT_METRICS]: false,
        })
        rerender(
            <ReportCard
                report={makeReport('r-2', {
                    metrics: [{ ...report.metrics![0], value: 42 }],
                })}
            />
        )
        expect(container.querySelector('[data-attr="report-card-impact-metric"]')).toBeNull()
    })
})
