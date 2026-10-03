import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { TeamType } from '~/types'

import type { MessageCategoryApi, RecipientApi } from 'products/messaging/frontend/generated/api.schemas'

import { AudienceScene } from './AudienceScene'
import { audienceSceneLogic } from './audienceSceneLogic'
import { recipient } from './recipientTestFixtures'

const NEWSLETTER: MessageCategoryApi = {
    id: '0199c1aa-0000-7000-8000-000000000001',
    key: 'newsletter',
    name: 'Newsletter',
    description: 'Monthly product news',
    public_description: 'Monthly product news',
    category_type: 'marketing',
    created_at: '2026-09-01T10:00:00Z',
    updated_at: '2026-09-01T10:00:00Z',
    created_by: null,
}

const SUPPRESSED_JAMIE: RecipientApi = {
    email: 'jamie@example.com',
    all_marketing: 'NO_PREFERENCE',
    topics: { newsletter: 'OPTED_OUT' },
    suppression: { source: 'BOUNCE', reason: 'Suppressed after 5 soft bounces in a row', suppressed_at: null },
    persons: [{ uuid: '0199c1dd-0000-7000-8000-000000000002', distinct_id: 'jamie-web', name: 'Jamie Chen' }],
    person_count: 1,
    last_sent_at: null,
    preferences_updated_at: '2026-09-20T08:30:00Z',
}

const ALEX = recipient('alex@example.com')

const TEAM_WITH_ENGAGEMENT_EVENTS: TeamType = {
    ...MOCK_DEFAULT_TEAM,
    workflows_config: { capture_workflows_engagement_events: true },
}

describe('recipient detail', () => {
    let lookups: (string | null)[]
    let timelineQueries: string[]

    function useRecipientLookup(response: [number, unknown]): void {
        useMocks({
            get: {
                '/api/projects/:team_id/messaging_recipients/': ({ request }) => {
                    const params = new URL(request.url).searchParams
                    const email = params.get('email')
                    if (!email) {
                        const listed = params.get('search') ? [SUPPRESSED_JAMIE] : [SUPPRESSED_JAMIE, ALEX]
                        return [200, { results: listed, next_cursor: null }]
                    }
                    lookups.push(email)
                    return response
                },
                '/api/projects/:team_id/messaging_recipients/coverage/': { persons_without_email: 0 },
                '/api/projects/:team_id/messaging_categories/': { results: [NEWSLETTER], next: null },
            },
            post: {
                '/api/environments/:team_id/query/:kind': async ({ request }) => {
                    const { query } = ((await request.json()) as { query: { query: string } }).query
                    if (!query.includes('$workflows_email_')) {
                        return [200, { results: [] }]
                    }
                    timelineQueries.push(query)
                    return [
                        200,
                        {
                            results: [
                                ['$workflows_email_unsubscribed', '2026-09-30T11:00:00Z', null, null, '$all'],
                                [
                                    '$workflows_email_link_clicked',
                                    '2026-09-30T10:05:00Z',
                                    'September news',
                                    'https://example.com/pricing',
                                    null,
                                ],
                                ['$workflows_email_opened', '2026-09-30T10:00:00Z', 'September news', null, null],
                            ],
                        },
                    ]
                },
            },
            patch: {
                '/api/projects/:team_id/': () => [200, TEAM_WITH_ENGAGEMENT_EVENTS],
            },
        })
    }

    function showRecipients(team: TeamType = MOCK_DEFAULT_TEAM): void {
        initKeaTests(true, team)
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_AUDIENCE]: true })
        router.actions.push(urls.audience())
        render(<AudienceScene />)
    }

    async function openRecipient(team: TeamType = MOCK_DEFAULT_TEAM): Promise<void> {
        showRecipients(team)
        fireEvent.click(await screen.findByText('jamie@example.com'))
    }

    function currentUrl(): string {
        const { pathname, search, hash } = router.values.location
        return `${pathname}${search}${hash}`
    }

    function capturedEvents(eventName: string): unknown[][] {
        return jest.mocked(posthog.capture).mock.calls.filter(([event]) => event === eventName)
    }

    beforeEach(() => {
        lookups = []
        timelineQueries = []
        jest.spyOn(posthog, 'capture')
    })

    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })

    it('looks the address up, shows why it is suppressed and tracks the visit once without the address', async () => {
        useRecipientLookup([200, { results: [SUPPRESSED_JAMIE], next_cursor: null }])
        await openRecipient()

        expect(await screen.findByText(/Suppressed after 5 soft bounces in a row/)).toBeInTheDocument()
        for (const suppressionListLink of screen.getAllByText('Open suppression list')) {
            expect(suppressionListLink.closest('a')).toHaveAttribute(
                'href',
                expect.stringContaining(urls.audience('suppression'))
            )
        }
        expect(lookups).toEqual(['jamie@example.com'])
        expect(capturedEvents('audience recipient opened')).toHaveLength(1)
        expect(JSON.stringify(capturedEvents('audience recipient opened'))).not.toContain('example.com')
    })

    it('opens from its row without the address in the url or breadcrumbs, and goes back to the same search', async () => {
        useRecipientLookup([200, { results: [SUPPRESSED_JAMIE], next_cursor: null }])
        showRecipients()
        expect(await screen.findByText('alex@example.com')).toBeInTheDocument()
        fireEvent.change(screen.getByLabelText('Search recipients by email address'), { target: { value: 'jamie' } })
        await waitFor(() => expect(screen.queryByText('alex@example.com')).not.toBeInTheDocument())
        const listUrl = currentUrl()

        fireEvent.click(await screen.findByText('jamie@example.com'))

        expect(await screen.findByText(/Suppressed after 5 soft bounces in a row/)).toBeInTheDocument()
        expect(currentUrl()).toEqual(listUrl)
        expect(listUrl).not.toContain('example.com')
        expect(JSON.stringify(audienceSceneLogic.values.breadcrumbs)).not.toContain('example.com')

        fireEvent.click(screen.getByText('Back to recipients'))

        expect(await screen.findByLabelText('Search recipients by email address')).toHaveValue('jamie')
        expect(await screen.findByText('jamie@example.com')).toBeInTheDocument()
        expect(screen.queryByText('alex@example.com')).not.toBeInTheDocument()
    })

    it('keeps the recipient page out of autocapture and replay', async () => {
        useRecipientLookup([200, { results: [SUPPRESSED_JAMIE], next_cursor: null }])
        await openRecipient()

        expect(await screen.findByTestId('audience-recipient-detail')).toHaveClass('ph-no-capture')
    })

    it('shows its own error with a retry instead of a toast, and tracks the visit once it loads', async () => {
        const toastError = jest.spyOn(lemonToast, 'error')
        let failNextLookup = true
        useMocks({
            get: {
                '/api/projects/:team_id/messaging_recipients/': ({ request }) => {
                    if (!new URL(request.url).searchParams.get('email')) {
                        return [200, { results: [SUPPRESSED_JAMIE], next_cursor: null }]
                    }
                    if (failNextLookup) {
                        failNextLookup = false
                        return [500, { detail: 'The query took too long.' }]
                    }
                    return [200, { results: [SUPPRESSED_JAMIE], next_cursor: null }]
                },
                '/api/projects/:team_id/messaging_recipients/coverage/': { persons_without_email: 0 },
                '/api/projects/:team_id/messaging_categories/': { results: [NEWSLETTER], next: null },
            },
        })
        await openRecipient()

        fireEvent.click((await screen.findAllByTestId('audience-recipient-retry'))[0])

        expect(await screen.findByText(/Suppressed after 5 soft bounces in a row/)).toBeInTheDocument()
        expect(toastError).not.toHaveBeenCalled()
        expect(capturedEvents('audience recipient opened')).toHaveLength(1)
    })

    it('shows a way back to the list when the address is unknown', async () => {
        useRecipientLookup([404, { detail: 'No recipient with this email address.' }])
        await openRecipient()

        expect(await screen.findByText('No recipient with this address')).toBeInTheDocument()
        expect(capturedEvents('audience recipient opened')).toEqual([])

        fireEvent.click(screen.getByText('Back to recipients'))

        expect(await screen.findByText('jamie@example.com')).toBeInTheDocument()
        expect(screen.queryByText('No recipient with this address')).not.toBeInTheDocument()
    })

    it('with engagement events on, lists the email events for the address in lower case, not the person', async () => {
        useRecipientLookup([200, { results: [SUPPRESSED_JAMIE], next_cursor: null }])
        await openRecipient(TEAM_WITH_ENGAGEMENT_EVENTS)

        const timeline = await screen.findByTestId('audience-recipient-timeline')
        expect(await within(timeline).findByText('Clicked a link')).toBeInTheDocument()
        expect(within(timeline).getByText('https://example.com/pricing')).toBeInTheDocument()
        expect(within(timeline).getByText('Opened')).toBeInTheDocument()
        expect(within(timeline).getByText('Unsubscribed')).toBeInTheDocument()
        expect(within(timeline).getByText('All marketing')).toBeInTheDocument()
        expect(screen.getByText(/follows the address, not a person/)).toBeInTheDocument()
        expect(timelineQueries).toHaveLength(1)
        expect(timelineQueries[0]).toContain("lower(properties.$email_to) = 'jamie@example.com'")
        expect(timelineQueries[0]).toContain("lower(properties.$email) = 'jamie@example.com'")
    })

    it('with engagement events off, offers to turn them on and then shows the timeline', async () => {
        useRecipientLookup([200, { results: [SUPPRESSED_JAMIE], next_cursor: null }])
        await openRecipient()

        const turnOnButton = await screen.findByTestId('audience-turn-on-engagement-events-button')
        expect(timelineQueries).toEqual([])

        fireEvent.click(turnOnButton)

        const timeline = await screen.findByTestId('audience-recipient-timeline')
        expect(await within(timeline).findByText('Clicked a link')).toBeInTheDocument()
        expect(capturedEvents('audience engagement events enabled')).toEqual([
            ['audience engagement events enabled', { surface: 'recipient' }],
        ])
    })

    it('opens the preferences page this recipient sees and tracks the preview from the recipient page', async () => {
        const linkRequests: unknown[] = []
        useRecipientLookup([200, { results: [SUPPRESSED_JAMIE], next_cursor: null }])
        useMocks({
            post: {
                '/api/projects/:team_id/messaging_preferences/generate_link/': async ({ request }) => {
                    linkRequests.push(await request.json())
                    return [200, { preferences_url: 'https://app.example.com/messaging-preferences/token/' }]
                },
            },
        })
        const openWindow = jest.spyOn(window, 'open').mockImplementation(() => null)
        await openRecipient()

        fireEvent.click(await screen.findByTestId('audience-recipient-preferences-page'))

        await waitFor(() =>
            expect(openWindow).toHaveBeenCalledWith('https://app.example.com/messaging-preferences/token/', '_blank')
        )
        expect(linkRequests).toEqual([{ recipient: 'jamie@example.com' }])
        expect(capturedEvents('messaging preferences page previewed')).toEqual([
            ['messaging preferences page previewed', { surface: 'recipient' }],
        ])
    })
})
