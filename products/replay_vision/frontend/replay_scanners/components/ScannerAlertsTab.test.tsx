import { render, screen } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { VisionAlertConfigurationApi } from '../../generated/api.schemas'
import { scannerAlertsLogic } from '../scannerAlertsLogic'
import { ScannerAlertsTab } from './ScannerAlertsTab'

const SCANNER_ID = '01a014ea-854f-72b5-8192-bb6ac9f212a5'
const ALERT_NAME = 'Any rage click observation'

const matchAlert = {
    id: '00000000-0000-0000-0000-0000000000e2',
    scanner_id: SCANNER_ID,
    name: ALERT_NAME,
    enabled: true,
    kind: 'match',
    selection: {},
    state: 'firing',
    notification_config: [],
    created_by: null,
} as unknown as VisionAlertConfigurationApi

// Every write refreshes the list, and kea-loaders keeps the last successful value when a refresh
// fails, so the tab has to answer for a failure that arrives on top of alerts it already loaded.
describe('ScannerAlertsTab', () => {
    let firstResults: VisionAlertConfigurationApi[]
    let alertsListCalls: number

    beforeEach(() => {
        firstResults = []
        alertsListCalls = 0
        useMocks({
            get: {
                '/api/projects/:team/vision/alerts/': () => {
                    alertsListCalls += 1
                    return alertsListCalls > 1
                        ? [500, { detail: 'Server error' }]
                        : [200, { count: firstResults.length, next: null, previous: null, results: firstResults }]
                },
                '/api/projects/:team/vision/scanners/:id/': () => [
                    200,
                    { id: SCANNER_ID, name: 'Checkout', scanner_type: 'summarizer', user_access_level: 'editor' },
                ],
                '/api/projects/:team/vision/scanners/:id/observations/stats/': () => [
                    200,
                    { status_counts: { in_flight: 0 } },
                ],
                '/api/projects/:team/vision/observations/': () => [
                    200,
                    { count: 0, next: null, previous: null, results: [] },
                ],
            },
        })
        initKeaTests()
    })

    it('offers a retry instead of the empty state when a refresh fails', async () => {
        render(<ScannerAlertsTab scannerId={SCANNER_ID} />)
        await screen.findByText(/No alerts on this scanner yet/)

        scannerAlertsLogic({ scannerId: SCANNER_ID }).actions.loadAlerts()

        await screen.findByText("Couldn't load this scanner's alerts.")
        expect(screen.queryByText(/No alerts on this scanner yet/)).toBeNull()
    })

    it('keeps the alerts already loaded when a refresh fails', async () => {
        firstResults = [matchAlert]
        render(<ScannerAlertsTab scannerId={SCANNER_ID} />)
        await screen.findByText(ALERT_NAME)

        scannerAlertsLogic({ scannerId: SCANNER_ID }).actions.loadAlerts()

        await screen.findByText("Couldn't load this scanner's alerts.")
        expect(screen.getByText(ALERT_NAME)).toBeTruthy()
    })
})
