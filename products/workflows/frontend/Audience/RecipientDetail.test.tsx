import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { TeamType } from '~/types'

import type { MessageCategoryApi, RecipientApi } from 'products/messaging/frontend/generated/api.schemas'

import { AudienceScene } from './AudienceScene'

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
                    lookups.push(new URL(request.url).searchParams.get('email'))
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

    function openRecipient(team: TeamType = MOCK_DEFAULT_TEAM): void {
        initKeaTests(true, team)
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_AUDIENCE]: true })
        router.actions.push('/audience/recipients/Jamie%40example.com')
        render(<AudienceScene />)
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
        openRecipient()

        expect(await screen.findByText(/Suppressed after 5 soft bounces in a row/)).toBeInTheDocument()
        for (const suppressionListLink of screen.getAllByText('Open suppression list')) {
            expect(suppressionListLink.closest('a')).toHaveAttribute(
                'href',
                expect.stringContaining(urls.audience('suppression'))
            )
        }
        expect(lookups).toEqual(['Jamie@example.com'])
        expect(capturedEvents('audience recipient opened')).toHaveLength(1)
        expect(JSON.stringify(capturedEvents('audience recipient opened'))).not.toContain('example.com')
    })

    it('shows a way back to the list when the address is unknown', async () => {
        useRecipientLookup([404, { detail: 'No recipient with this email address.' }])
        openRecipient()

        expect(await screen.findByText('No recipient with this address')).toBeInTheDocument()
        expect(screen.getByText('Back to recipients').closest('a')).toHaveAttribute(
            'href',
            expect.stringContaining(urls.audience())
        )
        expect(capturedEvents('audience recipient opened')).toEqual([])
    })

    it('with engagement events on, lists the email events for the address in lower case, not the person', async () => {
        useRecipientLookup([200, { results: [SUPPRESSED_JAMIE], next_cursor: null }])
        openRecipient(TEAM_WITH_ENGAGEMENT_EVENTS)

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
        openRecipient()

        const turnOnButton = await screen.findByTestId('audience-turn-on-engagement-events-button')
        expect(timelineQueries).toEqual([])

        fireEvent.click(turnOnButton)

        const timeline = await screen.findByTestId('audience-recipient-timeline')
        expect(await within(timeline).findByText('Clicked a link')).toBeInTheDocument()
        expect(capturedEvents('audience engagement events enabled')).toEqual([
            ['audience engagement events enabled', { surface: 'recipient' }],
        ])
    })
})
