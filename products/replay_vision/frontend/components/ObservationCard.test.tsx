import { render } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { ReplayObservationApi } from '../generated/api.schemas'
import { ObservationDockCard } from './ObservationCard'

describe('ObservationDockCard', () => {
    let scannerRetrieveCalls: number

    beforeEach(() => {
        scannerRetrieveCalls = 0
        useMocks({
            get: {
                // An inline scan's scanner is excluded from this viewset, so a fetch here 404s, and the
                // scanner logic's loader answers a 404 by toasting and replacing the route with
                // /replay-vision. Rendering a summary must therefore never reach this endpoint.
                '/api/projects/:team/vision/scanners/:id/': () => {
                    scannerRetrieveCalls += 1
                    return [404, { detail: 'Not found.' }]
                },
            },
        })
        initKeaTests()
    })

    it('does not fetch the scanner when rendering an observation', () => {
        const observation = {
            id: 'obs-1',
            scanner_id: 'inline-scanner-1',
            session_id: 'sess-1',
            status: 'succeeded',
            scanner_snapshot: { name: '', scanner_type: 'summarizer' },
            scanner_result: { scanner_type: 'summarizer', title: 'A title', summary: 'A summary.' },
        } as unknown as ReplayObservationApi

        render(<ObservationDockCard observation={observation} />)

        expect(scannerRetrieveCalls).toBe(0)
    })
})
