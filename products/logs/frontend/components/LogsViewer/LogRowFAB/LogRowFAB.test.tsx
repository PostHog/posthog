import { render } from '@testing-library/react'

import type { ParsedLogMessage } from 'products/logs/frontend/types'

import { LogRowFAB } from './LogRowFAB'

// The FAB wires several kea logics that pull in the whole viewer/store tree. The behavior under
// test is which pivots render for a log, so the kea hooks are stubbed and the child components
// that mount their own logic are stubbed at the boundary.
jest.mock('kea', () => {
    const actual = jest.requireActual('kea')
    return { ...actual, useValues: () => ({}), useActions: () => ({}) }
})

jest.mock('lib/hooks/useFeatureFlag', () => ({
    useFeatureFlag: () => true,
}))

jest.mock('lib/components/ViewRecordingButton/ViewRecordingButton', () => ({
    __esModule: true,
    default: () => null,
    RecordingPlayerType: { Modal: 'modal' },
}))

jest.mock('products/logs/frontend/components/VirtualizedLogsList/useCellScroll', () => ({
    useCellScrollControls: () => ({ startScrolling: jest.fn(), stopScrolling: jest.fn() }),
}))

// Capture the props the service-metrics pivot receives — the FAB must hand it the log's own
// service (from resource attributes) and a window around the log timestamp.
const capturedMetricsButtonProps: {
    serviceName?: string | null
    dateFrom?: string | null
    dateTo?: string | null
}[] = []
jest.mock('products/metrics/frontend/components/ViewServiceMetricsButton', () => ({
    ViewServiceMetricsButton: (props: {
        serviceName?: string | null
        dateFrom?: string | null
        dateTo?: string | null
    }) => {
        capturedMetricsButtonProps.push(props)
        return null
    },
}))

jest.mock('products/logs/frontend/components/LogsViewer/LogContextSelector/LogContextSelector', () => ({
    LogContextSelector: () => null,
}))
jest.mock('products/logs/frontend/components/LogsViewer/CopyLogButton', () => ({
    CopyLogButton: () => null,
}))

const log = {
    uuid: 'log-1',
    timestamp: '2026-06-11T08:00:00.000Z',
    trace_id: '',
    span_id: '',
    parsedBody: null,
    attributes: {},
    resource_attributes: { 'service.name': 'billing-worker' },
} as unknown as ParsedLogMessage

describe('LogRowFAB', () => {
    beforeEach(() => {
        capturedMetricsButtonProps.length = 0
    })

    it('offers a pivot to the log service metrics around the log timestamp', () => {
        render(<LogRowFAB log={log} pinned={false} isPrettified={false} onTogglePin={jest.fn()} />)

        const button = capturedMetricsButtonProps[capturedMetricsButtonProps.length - 1]
        expect(button).toBeTruthy()
        expect(button.serviceName).toBe('billing-worker')
        expect(button.dateFrom).toBe('2026-06-11T07:00:00.000Z')
        expect(button.dateTo).toBe('2026-06-11T09:00:00.000Z')
    })

    it('hands the metrics pivot no service when the log carries none, so the button hides itself', () => {
        const noServiceLog = { ...log, resource_attributes: {} } as unknown as ParsedLogMessage
        render(<LogRowFAB log={noServiceLog} pinned={false} isPrettified={false} onTogglePin={jest.fn()} />)

        // ViewServiceMetricsButton owns the hide-when-empty gate; the FAB's contract is to pass
        // null rather than an empty-string service that would scope the metrics URL to nothing.
        const button = capturedMetricsButtonProps[capturedMetricsButtonProps.length - 1]
        expect(button.serviceName ?? null).toBeNull()
    })
})
