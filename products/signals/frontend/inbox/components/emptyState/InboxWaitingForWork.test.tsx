/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { mockSourceConfigs } from '../../__mocks__/inboxMocks'
import { InboxWaitingForWork } from './InboxWaitingForWork'

jest.mock('posthog-js')

function mockWatchers(sourceConfigs: unknown[]): void {
    useMocks({
        get: {
            '/api/environments/:team_id/external_data_sources/': () => [
                200,
                { results: [], count: 0, next: null, previous: null },
            ],
            '/api/projects/:team_id/signals/reports/': () => [
                200,
                { count: 0, next: null, previous: null, results: [] },
            ],
            '/api/projects/:team_id/signals/reports/available_reviewers': {},
            '/api/projects/:team_id/signals/source_configs/': () => [
                200,
                { results: sourceConfigs, count: sourceConfigs.length, next: null, previous: null },
            ],
            '/api/projects/:team_id/signals/scout/configs/': () => [200, []],
            '/api/projects/:team_id/vision/scanners/': () => [
                200,
                { results: [], count: 0, next: null, previous: null },
            ],
        },
    })
}

describe('InboxWaitingForWork', () => {
    beforeEach(() => {
        initKeaTests()
        // The source-config and Vision-scanner loads are gated on this flag, and the setup verdict
        // never settles without them.
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.PRODUCT_AUTONOMY], {
            [FEATURE_FLAGS.PRODUCT_AUTONOMY]: true,
        })
    })

    afterEach(cleanup)

    // The screen promised that agents were working on a project where nothing was enabled, so a
    // setup run that ended without turning anything on read as "wait longer" forever.
    it('offers a way to finish setup when nothing is watching', async () => {
        mockWatchers([])

        render(<InboxWaitingForWork />)

        await waitFor(() => expect(screen.getByText("Setup isn't finished")).toBeInTheDocument())
        expect(screen.queryByText('Your agents are working in the background')).toBeNull()
        expect(screen.getByText('Turn on sources')).toBeInTheDocument()
        expect(screen.getByText('Browse scouts')).toBeInTheDocument()
    })

    it('keeps the waiting state once something is watching', async () => {
        mockWatchers(mockSourceConfigs.results)

        render(<InboxWaitingForWork />)

        await waitFor(() => expect(screen.getByText('Your agents are working in the background')).toBeInTheDocument())
        expect(screen.queryByText("Setup isn't finished")).toBeNull()
    })
})
