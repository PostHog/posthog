import '@testing-library/jest-dom'

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { router } from 'kea-router'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { ReplayScannerSceneComponent } from './ReplayScanner'
import { replayScannerLogic } from './replayScannerLogic'
import { replayScannerSceneLogic } from './replayScannerSceneLogic'

const mockImportedTabs: string[] = []

jest.mock('./components/ScannerOverview', () => ({ ScannerOverview: () => <div>Overview content</div> }))
jest.mock('./components/ScannerScoutCard', () => ({ ScannerScoutCard: () => null }))

jest.mock('../search/ObservationSearchTab', () => {
    mockImportedTabs.push('Search')
    return {
        ObservationSearchTab: ({ scanner }: { scanner: { id: string } }) => <div>Search content {scanner.id}</div>,
    }
})
jest.mock('./components/ScannerRunTab', () => {
    mockImportedTabs.push('On-demand')
    return { ScannerRunTab: ({ scannerId }: { scannerId: string }) => <div>On-demand content {scannerId}</div> }
})
jest.mock('./components/ScannerBackfillsTab', () => {
    mockImportedTabs.push('Backfills')
    return { ScannerBackfillsTab: ({ scannerId }: { scannerId: string }) => <div>Backfills content {scannerId}</div> }
})
jest.mock('./components/ScannerConfigReadonly', () => {
    mockImportedTabs.push('Configuration')
    return {
        ScannerConfigReadonly: ({ scanner }: { scanner: { id: string } }) => (
            <div>Configuration content {scanner.id}</div>
        ),
    }
})
jest.mock('./components/ScannerCalibrationTab', () => {
    mockImportedTabs.push('Calibration')
    return {
        ScannerCalibrationTab: ({ scannerId }: { scannerId: string }) => <div>Calibration content {scannerId}</div>,
    }
})
jest.mock('./components/ScannerScoutsTab', () => {
    mockImportedTabs.push('Scouts')
    return { ScannerScoutsTab: ({ scannerId }: { scannerId: string }) => <div>Scouts content {scannerId}</div> }
})
jest.mock('./components/ScannerAlertsTab', () => {
    mockImportedTabs.push('Alerts')
    return { ScannerAlertsTab: ({ scannerId }: { scannerId: string }) => <div>Alerts content {scannerId}</div> }
})

describe('ReplayScanner', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/vision/scanners/:id/': {
                    id: 'scanner-example',
                    name: 'Example scanner',
                    scanner_type: 'monitor',
                    scanner_config: { prompt: 'Find navigation failures.' },
                    sampling_rate: 1,
                    enabled: true,
                },
                '/api/projects/:team/vision/scanners/:id/observations/': { results: [], count: 0 },
                '/api/projects/:team/vision/scanners/:id/observations/stats/': {
                    status_counts: { total: 0, succeeded: 0, failed: 0, ineligible: 0, in_flight: 0 },
                    coverage: { recent_sessions: 0, total_sessions: 0, recent_days: 14 },
                    available_tags: [],
                    labels: { version_markers: [] },
                },
            },
        })
        initKeaTests()
        replayScannerSceneLogic.mount()
        router.actions.push('/replay-vision/scanner-example')
    })

    afterEach(() => replayScannerSceneLogic.unmount())

    it('imports secondary tabs on selection and loads rows only while the observations table is mounted', async () => {
        const { unmount } = render(<ReplayScannerSceneComponent />)
        await screen.findByText('Overview content')
        expect(mockImportedTabs).toEqual([])
        const logic = replayScannerLogic({ id: 'scanner-example' })
        expect(logic.values.observationsActive).toBe(false)

        const tabs = ['Search', 'On-demand', 'Backfills', 'Configuration', 'Calibration', 'Scouts', 'Alerts']
        for (const [index, tab] of tabs.entries()) {
            fireEvent.click(screen.getByRole('tab', { name: new RegExp(`^${tab}`) }))
            expect(screen.getByRole('tab', { name: 'Observations' })).toBeInTheDocument()
            await screen.findByText(`${tab} content scanner-example`)
            expect(mockImportedTabs).toEqual(tabs.slice(0, index + 1))
            expect(router.values.searchParams.tab).toBe(tab.toLowerCase())
            expect(logic.values.observationsActive).toBe(false)
        }

        fireEvent.click(screen.getByRole('tab', { name: 'Observations' }))
        await waitFor(() => expect(logic.values.observationsActive).toBe(true))
        fireEvent.click(screen.getByRole('tab', { name: 'Configuration' }))
        await screen.findByText('Configuration content scanner-example')
        expect(logic.values.observationsActive).toBe(false)
        expect(mockImportedTabs).toEqual(tabs)

        fireEvent.click(screen.getByRole('tab', { name: 'Observations' }))
        await waitFor(() => expect(logic.values.observationsActive).toBe(true))
        unmount()
        expect(logic.values.observationsActive).toBe(false)
    })
})
