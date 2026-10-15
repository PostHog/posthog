import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { AgentsRoster } from './AgentsRoster'

const SCANNERS = Array.from({ length: 10 }, (_, index) => ({
    id: `scanner-${index}`,
    name: `Scanner ${index}`,
    description: `Watches step ${index}.`,
    scanner_type: 'monitor',
    enabled: true,
    emits_signals: false,
}))

const EMPTY_LIST = { count: 0, next: null, previous: null, results: [] }

describe('AgentsRoster', () => {
    beforeEach(() => {
        initKeaTests()
        useMocks({
            get: {
                '/api/projects/:team_id/signals/source_configs/': () => [200, { results: [] }],
                '/api/projects/:team_id/vision/scanners/': () => [
                    200,
                    { count: SCANNERS.length, next: null, previous: null, results: SCANNERS },
                ],
                '/api/projects/:team_id/event_definitions/': () => [200, EMPTY_LIST],
                '/api/environments/:team_id/external_data_sources/': () => [200, EMPTY_LIST],
            },
        })
        // The roster only loads its sources behind this flag, so without it every list stays empty.
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.PRODUCT_AUTONOMY], {
            [FEATURE_FLAGS.PRODUCT_AUTONOMY]: true,
        })
    })
    afterEach(cleanup)

    // The cap keeps a long user-created list from burying the sources below it, but a filter that
    // could not reach past it would make a scanner unfindable by name.
    it('caps the scanner list, and lets both the filter and Show more reach past the cap', async () => {
        render(<AgentsRoster />)
        await userEvent.click(await screen.findByText('Replay vision'))

        expect(await screen.findByText('Scanner 7')).toBeInTheDocument()
        expect(screen.queryByText('Scanner 8')).not.toBeInTheDocument()

        await userEvent.type(screen.getByPlaceholderText('Filter scanners'), 'Scanner 9')
        expect(await screen.findByText('Scanner 9')).toBeInTheDocument()

        await userEvent.clear(screen.getByPlaceholderText('Filter scanners'))
        await userEvent.click(await screen.findByText('Show 2 more scanners'))
        expect(await screen.findByText('Scanner 9')).toBeInTheDocument()
    })

    // A failed load leaves every switch reading off and every import source reading unconnected.
    // A click then creates a row that may already exist, so the switches have to stay shut.
    it('holds the source switches shut while the source list has failed to load', async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/signals/source_configs/': () => [500, { detail: 'Server error' }],
            },
        })
        render(<AgentsRoster />)

        expect(await screen.findByText(/Couldn't load your signal sources/)).toBeInTheDocument()
        expect(screen.getByLabelText('Arm Support')).toBeDisabled()
        expect(screen.getByLabelText('Arm GitHub issues')).toBeDisabled()
        expect(screen.queryByText('Connect')).not.toBeInTheDocument()
    })
})
