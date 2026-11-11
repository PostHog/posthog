import { cleanup, render, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, type AppContext } from '~/types'

import { ScannerScoutsTab } from './ScannerScoutsTab'

const SCANNER_ID = '01a014ea-854f-72b5-8192-bb6ac9f212a5'

// The templates and the scanner load in parallel, so the create form can open before the scanner
// answers. This test holds the scanner response back until after the form is open.
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
                '/api/projects/:team/vision/scanners/:id/scouts/templates/': [
                    200,
                    [
                        {
                            key: 'daily-digest',
                            title: 'Daily digest',
                            description: 'A daily summary of what this scanner found.',
                            default_name: 'Rage clicks on checkout daily digest',
                            cron: '0 9 * * *',
                            body: 'Read the scanner and file a digest.',
                        },
                    ],
                ],
                '/api/projects/:team/vision/scanners/:id/scout_reports/': [200, []],
            },
        })
    })

    afterEach(() => {
        cleanup()
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

    it('seeds the form from the server template and blocks create until the scanner loads', async () => {
        await openDailyDigestForm()
        const submit = (): HTMLElement =>
            document.querySelector('[data-attr="vision-scout-form-submit"]') as HTMLElement
        expect(nameInput().value).toBe('Rage clicks on checkout daily digest')
        // The skill name is derived from the scanner name at creation and never changes, so creating
        // before the scanner answers would bake the logic's team-named placeholder into it.
        expect(submit().getAttribute('aria-disabled')).toBe('true')

        resolveScanner(scanner)
        await waitFor(() => expect(submit().getAttribute('aria-disabled')).not.toBe('true'))
    })
})
