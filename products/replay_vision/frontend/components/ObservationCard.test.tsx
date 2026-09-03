import { render, screen, waitFor } from '@testing-library/react'
import { router } from 'kea-router'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { ReplayObservationApi } from '../generated/api.schemas'
import { ObservationDockCard } from './ObservationCard'

// A summary's observation belongs to an inline scanner, which the scanner viewset excludes. Fetching
// one 404s, and replayScannerLogic answers a load failure by replacing the route with /replay-vision,
// so a card that loads its scanner throws the user off the recording they are watching.
describe('ObservationDockCard', () => {
    let scannerRetrieveCalls: number

    const observation = {
        id: 'obs-1',
        scanner_id: 'inline-scanner-1',
        session_id: 'sess-1',
        status: 'succeeded',
        scanner_snapshot: { name: '', scanner_type: 'summarizer' },
        scanner_result: { model_output: { scanner_type: 'summarizer', title: 'Checkout', summary: 'Bought a hat.' } },
    } as unknown as ReplayObservationApi

    beforeEach(() => {
        scannerRetrieveCalls = 0
        useMocks({
            get: {
                '/api/projects/:team/vision/scanners/:id/': () => {
                    scannerRetrieveCalls += 1
                    return [404, { detail: 'Not found.' }]
                },
            },
        })
        initKeaTests()
        router.actions.push('/replay/sess-1')
    })

    it('renders a summary without navigating away from the recording', async () => {
        const startPath = router.values.location.pathname

        render(<ObservationDockCard observation={observation} />)

        // findByText rejects if the summary never renders, so this is the assertion.
        await screen.findByText('Bought a hat.')

        // The redirect is what the user sees, so assert the route rather than only the request count.
        // Both need a flush: the fetch and the resulting replace are async.
        await waitFor(() => expect(scannerRetrieveCalls).toBe(0))
        expect(router.values.location.pathname).toBe(startPath)
    })
})
