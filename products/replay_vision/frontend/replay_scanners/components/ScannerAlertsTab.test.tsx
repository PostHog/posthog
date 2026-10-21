import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, type AppContext } from '~/types'

import { ScannerAlertsTab } from './ScannerAlertsTab'

const SCANNER_ID = '01a014ea-854f-72b5-8192-bb6ac9f212a5'

// A classifier alert matches on exact tag strings, so the form has to offer the tags the scanner
// already has: its configured categories, plus the freeform ones its observations carried.
describe('ScannerAlertsTab', () => {
    beforeEach(() => {
        initKeaTests()
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT,
            resource_access_control: {
                ...window.POSTHOG_APP_CONTEXT?.resource_access_control,
                [AccessControlResourceType.ReplayScanner]: AccessControlLevel.Editor,
                [AccessControlResourceType.SessionRecording]: AccessControlLevel.Viewer,
            },
        } as AppContext
        useMocks({
            get: {
                '/api/projects/:team/vision/scanners/:id/': [
                    200,
                    {
                        id: SCANNER_ID,
                        name: 'Checkout friction',
                        scanner_type: 'classifier',
                        scanner_config: {
                            prompt: 'Sort the session.',
                            tags: ['checkout', 'signup'],
                            multi_label: true,
                        },
                        sampling_rate: 1,
                        enabled: true,
                        user_access_level: AccessControlLevel.Editor,
                    },
                ],
                '/api/projects/:team/vision/scanners/:id/observations/': [200, { results: [], count: 0 }],
                '/api/projects/:team/vision/scanners/:id/observations/stats/': [
                    200,
                    {
                        status_counts: {},
                        coverage: {},
                        labels: {},
                        available_tags: ['checkout', 'payment-declined'],
                        monitor: null,
                        classifier: null,
                        scorer: null,
                    },
                ],
                '/api/projects/:team/vision/alerts/': [200, { results: [], count: 0 }],
                '/api/projects/:team/hog_functions/': [200, { results: [], count: 0 }],
                '/api/projects/:team/integrations/': [200, { results: [], count: 0 }],
            },
        })
    })

    afterEach(() => {
        delete (window as { POSTHOG_APP_CONTEXT?: AppContext }).POSTHOG_APP_CONTEXT
    })

    it('offers the configured categories and the observed freeform tags on a new classifier alert', async () => {
        render(<ScannerAlertsTab scannerId={SCANNER_ID} />)

        const newAlert = await screen.findByText('New alert')
        await userEvent.click(newAlert)

        const nameInput = await waitFor(() => {
            const input = document.querySelector('[data-attr="alert-name"] input, input[name="name"]')
            expect(input).not.toBeNull()
            return input as HTMLInputElement
        })
        await userEvent.type(nameInput, 'Payment problems')
        await userEvent.click(screen.getByText('Continue'))

        const tagsInput = await waitFor(() => {
            const input = document.querySelector('input[data-attr="vision-alert-tags"]')
            expect(input).not.toBeNull()
            return input as HTMLInputElement
        })
        await userEvent.click(tagsInput)

        expect(await screen.findByText('checkout')).not.toBeNull()
        expect(screen.getByText('signup')).not.toBeNull()
        expect(screen.getByText('payment-declined')).not.toBeNull()
    })
})
