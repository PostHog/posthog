import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
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

describe('recipient detail', () => {
    let lookups: (string | null)[]

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
})
