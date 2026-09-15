import '@testing-library/jest-dom'

import { render } from '@testing-library/react'

import { LogsViewerProps } from 'products/logs/frontend/components/LogsViewer/LogsViewer'

import { SurroundingLogsPanel } from './SurroundingLogsPanel'

const viewerProps: LogsViewerProps[] = []

jest.mock('products/logs/frontend/components/LogsViewer', () => ({
    LogsViewer: (props: LogsViewerProps) => {
        viewerProps.push(props)
        return <div data-testid="logs-viewer" />
    },
}))

describe('SurroundingLogsPanel', () => {
    beforeEach(() => {
        viewerProps.length = 0
    })

    it('opens the viewer on the five minutes either side of the event', () => {
        render(<SurroundingLogsPanel id="panel" timestamp="2026-03-24T12:00:00.000Z" sessionId="sess-1" />)

        expect(viewerProps[0].initialFilters).toEqual({
            dateRange: { date_from: '2026-03-24T11:55:00.000Z', date_to: '2026-03-24T12:05:00.000Z' },
        })
        expect(viewerProps[0].sessionId).toBe('sess-1')
    })

    it('keeps the same filters object across renders, so the viewer does not drop the user filters', () => {
        const { rerender } = render(<SurroundingLogsPanel id="panel" timestamp="2026-03-24T12:00:00.000Z" />)
        rerender(<SurroundingLogsPanel id="panel" timestamp="2026-03-24T12:00:00.000Z" />)

        expect(viewerProps).toHaveLength(2)
        expect(viewerProps[1].initialFilters).toBe(viewerProps[0].initialFilters)
    })

    it('leaves the range to the viewer when the event has no timestamp', () => {
        render(<SurroundingLogsPanel id="panel" />)

        expect(viewerProps[0].initialFilters).toBeUndefined()
    })
})
