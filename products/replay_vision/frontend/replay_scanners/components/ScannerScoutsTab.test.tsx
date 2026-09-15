import { render, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, type AppContext } from '~/types'

import { ScannerScoutsTab } from './ScannerScoutsTab'

const SCANNER_ID = '01a014ea-854f-72b5-8192-bb6ac9f212a5'

// The scouts list and the scanner load in parallel, so the create form can open before the scanner
// answers and the default name it seeds from is still the nameless fallback. These tests hold the
// scanner response back until after the form is open, which is the real timing, not a simulated one.
describe('ScannerScoutsTab', () => {
    let resolveScanner: (body: Record<string, unknown>) => void

    const scanner = {
        id: SCANNER_ID,
        name: 'Rage clicks on checkout',
        scanner_type: 'monitor',
        user_access_level: AccessControlLevel.Editor,
    }

    const nameInput = (): HTMLInputElement =>
        document.querySelector('[data-attr="vision-scout-form-name"]') as HTMLInputElement

    beforeEach(() => {
        initKeaTests()
        resolveScanner = () => {}
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT,
            resource_access_control: {
                ...window.POSTHOG_APP_CONTEXT?.resource_access_control,
                [AccessControlResourceType.ReplayScanner]: AccessControlLevel.Editor,
                [AccessControlResourceType.SessionRecording]: AccessControlLevel.Viewer,
                [AccessControlResourceType.LlmSkill]: AccessControlLevel.Editor,
            },
        } as AppContext
        useMocks({
            get: {
                '/api/projects/:team/vision/scanners/:id/': () =>
                    new Promise((resolve) => {
                        resolveScanner = (body) => resolve([200, body])
                    }),
                '/api/projects/:team/vision/scanners/:id/observations/stats/': [
                    200,
                    {
                        status_counts: {},
                        coverage: {},
                        labels: {},
                        available_tags: [],
                        monitor: null,
                        classifier: null,
                    },
                ],
                '/api/projects/:team/signals/scout/configs/': [200, []],
                '/api/projects/:team/signals/scout/runs/recent-per-scout/': [200, []],
                '/api/projects/:team/signals/scout/metadata/current/': [200, { enrolled: true }],
                '/api/projects/:team/vision/scanners/:id/scout_reports/': [200, []],
            },
        })
    })

    afterEach(() => {
        delete (window as { POSTHOG_APP_CONTEXT?: AppContext }).POSTHOG_APP_CONTEXT
    })

    async function openDailyDigestForm(): Promise<void> {
        render(<ScannerScoutsTab scannerId={SCANNER_ID} />)

        const useTemplate = await waitFor(
            () => {
                const button = document.querySelector('[data-attr="vision-scout-template-daily-digest"]')
                expect(button).not.toBeNull()
                return button as HTMLElement
            },
            // The button must be there while the scanner is still pending, or the race isn't real.
            { interval: 10 }
        )
        await userEvent.click(useTemplate)
        await waitFor(() => expect(nameInput()).toBeTruthy())
    }

    it('follows the scanner name into the form when it arrives after the form is open', async () => {
        await openDailyDigestForm()
        // Before the scanner answers, the scanner logic holds a team-named placeholder, so the
        // seeded name is derived from that rather than the scanner the person is looking at.
        expect(nameInput().value).toBe('MockHog App + Marketing monitor daily digest')

        resolveScanner(scanner)
        await waitFor(() => expect(nameInput().value).toBe('Rage clicks on checkout daily digest'))
    })

    it('keeps a name the person typed once the scanner answers', async () => {
        await openDailyDigestForm()

        const user = userEvent.setup()
        await user.clear(nameInput())
        await user.type(nameInput(), 'My own name')

        resolveScanner(scanner)
        // The placeholder tracks the template's default, so it proves the loaded name reached the
        // form; the value then proves the typed name survived it.
        await waitFor(() => expect(nameInput().placeholder).toBe('Rage clicks on checkout daily digest'))
        expect(nameInput().value).toBe('My own name')
    })
})
