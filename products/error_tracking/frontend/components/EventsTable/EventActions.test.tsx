import '@testing-library/jest-dom'

import { render } from '@testing-library/react'

import type { ErrorEventType } from 'lib/components/Errors/types'

import { EventActions } from './EventActions'

jest.mock('lib/components/ViewRecordingButton/ViewRecordingButton', () => ({
    useRecordingButton: () => ({ onClick: jest.fn(), disabledReason: undefined, warningReason: undefined }),
}))
jest.mock('products/logs/frontend/components/ViewLogsButton', () => ({
    useViewLogsButton: () => ({ enabled: false, onClick: undefined, disabledReason: undefined }),
}))

const capturedMetricsArgs: { serviceName: string | null; dateFrom?: string | null; dateTo?: string | null }[] = []
jest.mock('products/metrics/frontend/components/ViewServiceMetricsButton', () => ({
    useViewServiceMetricsButton: (args: {
        serviceName: string | null
        dateFrom?: string | null
        dateTo?: string | null
    }) => {
        capturedMetricsArgs.push(args)
        return { enabled: true, to: args.serviceName ? '/metrics?x=1' : undefined, disabledReason: undefined }
    },
}))

const event = {
    event: '$exception',
    uuid: 'event-1',
    timestamp: '2026-06-11T08:00:00.000Z',
    distinct_id: 'person-1',
    properties: {
        $exception_types: ['TypeError'],
        'service.name': 'billing-worker',
    },
} as unknown as ErrorEventType

describe('EventActions', () => {
    beforeEach(() => {
        capturedMetricsArgs.length = 0
    })

    it('scopes the service-metrics action to the event service and a window around its timestamp', () => {
        render(<EventActions record={event} />)

        const args = capturedMetricsArgs[capturedMetricsArgs.length - 1]
        expect(args.serviceName).toBe('billing-worker')
        expect(args.dateFrom).toBe('2026-06-11T07:00:00.000Z')
        expect(args.dateTo).toBe('2026-06-11T09:00:00.000Z')
    })

    it('passes a null service for an event with no service name, so the action disables itself', () => {
        const noServiceEvent = {
            ...event,
            properties: { $exception_types: ['TypeError'] },
        } as unknown as ErrorEventType
        render(<EventActions record={noServiceEvent} />)

        const args = capturedMetricsArgs[capturedMetricsArgs.length - 1]
        expect(args.serviceName).toBeNull()
    })
})
