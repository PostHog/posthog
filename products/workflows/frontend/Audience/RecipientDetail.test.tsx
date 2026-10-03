import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
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
import { recipientDetailLogic } from './recipientDetailLogic'
import { MockResponse, recipient } from './recipientTestFixtures'

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

type TimelineRow = [string, string, string | null, string | null, string | null]

const THREE_EMAIL_EVENTS: TimelineRow[] = [
    ['$workflows_email_unsubscribed', '2026-09-30T11:00:00Z', null, null, '$all'],
    ['$workflows_email_link_clicked', '2026-09-30T10:05:00Z', 'September news', 'https://example.com/pricing', null],
    ['$workflows_email_opened', '2026-09-30T10:00:00Z', 'September news', null, null],
]

const FOUND_JAMIE: MockResponse = [200, { results: [SUPPRESSED_JAMIE], next_cursor: null }]

const TEAM_WITH_ENGAGEMENT_EVENTS: TeamType = {
    ...MOCK_DEFAULT_TEAM,
    workflows_config: { capture_workflows_engagement_events: true },
}

describe('recipient detail', () => {
    let lookups: string[]
    let timelineQueries: string[]
    let respondToLookup: () => MockResponse | Promise<MockResponse>
    let respondToTimeline: () => MockResponse | Promise<MockResponse>

    function heldResponse(): { respond: () => Promise<MockResponse>; release: (response: MockResponse) => void } {
        let release: (response: MockResponse) => void = () => {}
        const response = new Promise<MockResponse>((resolve) => {
            release = resolve
        })
        return { respond: () => response, release }
    }

    function useRecipientMocks(): void {
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
                    return respondToLookup()
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
                    return respondToTimeline()
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
        respondToLookup = () => FOUND_JAMIE
        respondToTimeline = () => [200, { results: THREE_EMAIL_EVENTS }]
        useRecipientMocks()
        jest.spyOn(posthog, 'capture')
    })

    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
        Reflect.deleteProperty(navigator, 'clipboard')
    })

    it('looks the address up, shows why it is suppressed and tracks the visit once without the address', async () => {
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
        expect(screen.getByText('Back to recipients').closest('button')).toHaveFocus()

        fireEvent.click(screen.getByText('Back to recipients'))

        const search = await screen.findByLabelText('Search recipients by email address')
        expect(search).toHaveValue('jamie')
        expect(search).toHaveFocus()
        expect(await screen.findByText('jamie@example.com')).toBeInTheDocument()
        expect(screen.queryByText('alex@example.com')).not.toBeInTheDocument()
    })

    it.each([
        { click: 'a plain click', modifiers: {} },
        { click: 'a Cmd-click', modifiers: { metaKey: true } },
        { click: 'a Ctrl-click', modifiers: { ctrlKey: true } },
    ])('opens a recipient on $click on its address', async ({ modifiers }) => {
        showRecipients()

        fireEvent.click(await screen.findByText('jamie@example.com'), modifiers)

        expect(await screen.findByTestId('audience-recipient-detail')).toBeInTheDocument()
    })

    it('stays open while its activity pages and the side panel opens, and closes on a tab change', async () => {
        const twentyFiveEvents = Array.from(
            { length: 25 },
            (_, index): TimelineRow => [
                '$workflows_email_sent',
                `2026-09-${String(30 - index).padStart(2, '0')}T10:00:00Z`,
                `Issue ${index + 1}`,
                null,
                null,
            ]
        )
        respondToTimeline = () => [200, { results: twentyFiveEvents }]
        await openRecipient(TEAM_WITH_ENGAGEMENT_EVENTS)

        const timeline = await screen.findByTestId('audience-recipient-timeline')
        await within(timeline).findByText('Issue 1')
        fireEvent.click(within(timeline).getByLabelText('Next page'))

        expect(await within(timeline).findByText('Issue 21')).toBeInTheDocument()
        router.actions.replace(`${router.values.location.pathname}${router.values.location.search}#panel=docs`)
        expect(screen.getByTestId('audience-recipient-detail')).toBeInTheDocument()

        router.actions.push(urls.audience('topics'))
        router.actions.push(urls.audience())

        expect(await screen.findByLabelText('Search recipients by email address')).toBeInTheDocument()
        expect(screen.queryByTestId('audience-recipient-detail')).not.toBeInTheDocument()
    })

    it('keeps the recipient page out of autocapture and replay', async () => {
        await openRecipient()

        expect(await screen.findByTestId('audience-recipient-detail')).toHaveClass('ph-no-capture')
    })

    it('tracks a copied address without the address', async () => {
        const writeText = jest.fn().mockResolvedValue(undefined)
        Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
        await openRecipient()

        fireEvent.click(await screen.findByTestId('audience-recipient-copy-email'))

        await waitFor(() =>
            expect(capturedEvents('audience recipient address copied')).toEqual([
                ['audience recipient address copied', {}],
            ])
        )
        expect(writeText).toHaveBeenCalledWith('jamie@example.com')
    })

    it('shows its own error with a retry instead of a toast, and tracks the visit once it loads', async () => {
        const toastError = jest.spyOn(lemonToast, 'error')
        respondToLookup = () => {
            respondToLookup = () => FOUND_JAMIE
            return [500, { detail: 'The query took too long.' }]
        }
        await openRecipient()

        fireEvent.click((await screen.findAllByTestId('audience-recipient-retry'))[0])

        expect(await screen.findByText(/Suppressed after 5 soft bounces in a row/)).toBeInTheDocument()
        expect(toastError).not.toHaveBeenCalled()
        expect(capturedEvents('audience recipient opened')).toHaveLength(1)
        expect(capturedEvents('audience recipient retried')).toEqual([['audience recipient retried', {}]])
    })

    it('keeps a reopened recipient when the lookup from its earlier visit fails late', async () => {
        const firstLookup = heldResponse()
        respondToLookup = () => {
            respondToLookup = () => FOUND_JAMIE
            return firstLookup.respond()
        }
        await openRecipient()
        fireEvent.click(await screen.findByText('Back to recipients'))
        fireEvent.click(await screen.findByText('jamie@example.com'))
        expect(await screen.findByText(/Suppressed after 5 soft bounces in a row/)).toBeInTheDocument()

        firstLookup.release([500, { detail: 'The query took too long.' }])

        await expectLogic(recipientDetailLogic({ email: 'jamie@example.com' })).toFinishAllListeners()
        expect(screen.getByText(/Suppressed after 5 soft bounces in a row/)).toBeInTheDocument()
        expect(screen.queryByTestId('audience-recipient-retry')).not.toBeInTheDocument()
    })

    it.each([
        { answer: 'a 404', response: [404, { detail: 'No recipient with this email address.' }] as MockResponse },
        { answer: 'an empty page', response: [200, { results: [], next_cursor: null }] as MockResponse },
    ])('shows a way back to the list when the lookup answers with $answer', async ({ response }) => {
        const lookup = heldResponse()
        respondToLookup = lookup.respond
        await openRecipient()
        await waitFor(() => expect(lookups).toEqual(['jamie@example.com']))
        expect(screen.queryByText('No recipient with this address')).not.toBeInTheDocument()

        lookup.release(response)

        expect(await screen.findByText('No recipient with this address')).toBeInTheDocument()
        expect(capturedEvents('audience recipient opened')).toEqual([])

        fireEvent.click(screen.getByText('Back to recipients'))

        expect(await screen.findByText('jamie@example.com')).toBeInTheDocument()
        expect(screen.queryByText('No recipient with this address')).not.toBeInTheDocument()
    })

    it('with engagement events on, lists the email events for the address in lower case, not the person', async () => {
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

    it('shows a failed activity load inline instead of a toast and loads it again on retry', async () => {
        const toastError = jest.spyOn(lemonToast, 'error')
        respondToTimeline = () => {
            respondToTimeline = () => [200, { results: THREE_EMAIL_EVENTS }]
            return [500, { detail: 'Query timed out' }]
        }
        await openRecipient(TEAM_WITH_ENGAGEMENT_EVENTS)

        fireEvent.click((await screen.findAllByTestId('audience-recipient-timeline-retry'))[0])

        const timeline = await screen.findByTestId('audience-recipient-timeline')
        expect(await within(timeline).findByText('Clicked a link')).toBeInTheDocument()
        expect(toastError).not.toHaveBeenCalled()
    })

    it('with engagement events off, offers to turn them on and then shows the timeline', async () => {
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

    it.each([
        { outcome: 'opens', openedWindow: {} as Window, previews: 1 },
        { outcome: 'is blocked', openedWindow: null, previews: 0 },
    ])(
        'asks for the preferences page this recipient sees and tracks the preview only when it $outcome',
        async ({ openedWindow, previews }) => {
            const linkRequests: unknown[] = []
            const openWindow = jest.spyOn(window, 'open').mockImplementation(() => openedWindow)
            await openRecipient()
            useMocks({
                post: {
                    '/api/projects/:team_id/messaging_preferences/generate_link/': async ({ request }) => {
                        linkRequests.push(await request.json())
                        return [200, { preferences_url: 'https://app.example.com/messaging-preferences/token/' }]
                    },
                },
            })

            fireEvent.click(await screen.findByTestId('audience-recipient-preferences-page'))

            await waitFor(() =>
                expect(openWindow).toHaveBeenCalledWith(
                    'https://app.example.com/messaging-preferences/token/',
                    '_blank'
                )
            )
            await expectLogic(recipientDetailLogic({ email: 'jamie@example.com' })).toFinishAllListeners()
            expect(linkRequests).toEqual([{ recipient: 'jamie@example.com' }])
            expect(capturedEvents('messaging preferences page previewed')).toEqual(
                Array(previews).fill(['messaging preferences page previewed', { surface: 'recipient' }])
            )
        }
    )
})
