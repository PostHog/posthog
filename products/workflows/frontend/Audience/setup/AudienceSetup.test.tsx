import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { personalAPIKeysLogic } from 'scenes/settings/user/personalAPIKeysLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { MessageCategoryApi, RecipientApi } from 'products/messaging/frontend/generated/api.schemas'

import { AudienceScene } from '../AudienceScene'
import { audienceSceneLogic } from '../audienceSceneLogic'

const SETUP_HEADING = 'Bring your recipients into PostHog'

function topic(key: string, categoryType: 'marketing' | 'transactional' = 'marketing'): MessageCategoryApi {
    return {
        id: `topic-${key}`,
        key,
        name: key,
        category_type: categoryType,
        created_at: '2026-09-01T00:00:00Z',
        updated_at: '2026-09-01T00:00:00Z',
        created_by: null,
    }
}

const RECIPIENT: RecipientApi = {
    email: 'jamie@example.com',
    all_marketing: 'NO_PREFERENCE',
    topics: {},
    suppression: null,
    persons: [],
    person_count: 0,
    last_sent_at: null,
    preferences_updated_at: null,
}

describe('Audience setup', () => {
    function useAudience({ topics, recipients }: { topics: MessageCategoryApi[]; recipients: RecipientApi[] }): void {
        useMocks({
            get: {
                '/api/projects/:team_id/messaging_categories/': {
                    count: topics.length,
                    next: null,
                    previous: null,
                    results: topics,
                },
                '/api/projects/:team_id/messaging_recipients/': { results: recipients, next_cursor: null },
                '/api/projects/:team_id/messaging_recipients/coverage/': { persons_without_email: 0 },
            },
        })
    }

    function renderAudienceAt(path: string): void {
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_AUDIENCE]: true })
        audienceSceneLogic.mount()
        router.actions.push(path)
        render(<AudienceScene />)
    }

    function sendPreferencesStep(): HTMLElement {
        const step = document.querySelector<HTMLElement>('[data-attr="audience-setup-send-preferences"]')
        if (!step) {
            throw new Error('The send preferences step is not rendered')
        }
        return step
    }

    let capture: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        capture = jest.spyOn(posthog, 'capture')
        Object.defineProperty(navigator, 'clipboard', {
            value: { writeText: jest.fn(() => Promise.resolve()) },
            configurable: true,
        })
    })

    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })

    it.each([
        { audience: 'no topics and no recipients', topics: [], recipients: [], shows: SETUP_HEADING },
        { audience: 'a topic', topics: [topic('newsletter')], recipients: [], shows: 'No recipients yet' },
        { audience: 'a recipient', topics: [], recipients: [RECIPIENT], shows: RECIPIENT.email },
    ])('with $audience, /audience shows "$shows"', async ({ topics, recipients, shows }) => {
        useAudience({ topics, recipients })

        renderAudienceAt(urls.audience())

        expect(await screen.findByText(shows)).toBeInTheDocument()
        const setupShown = shows === SETUP_HEADING
        expect(screen.queryByPlaceholderText('Search by email address') === null).toBe(setupShown)
        expect(capture.mock.calls.some(([event]) => event === 'audience setup viewed')).toBe(setupShown)
    })

    it('opens from the Set up button on Recipients', async () => {
        useAudience({ topics: [], recipients: [RECIPIENT] })
        renderAudienceAt(urls.audience())

        fireEvent.click(await screen.findByText('Set up'))

        expect(await screen.findByText(SETUP_HEADING)).toBeInTheDocument()
        expect(removeProjectIdIfPresent(router.values.location.pathname)).toBe(urls.audienceSetup())
        expect(capture).toHaveBeenCalledWith('audience setup viewed', { source: 'setup_page' })
    })

    it('lists the marketing topic keys in the snippet and the agent prompt, and tracks each copy', async () => {
        useAudience({
            topics: [topic('newsletter'), topic('product-updates'), topic('receipts', 'transactional')],
            recipients: [RECIPIENT],
        })
        renderAudienceAt(urls.audienceSetup())

        await waitFor(() => expect(sendPreferencesStep()).toHaveTextContent("'product-updates': true"))
        expect(sendPreferencesStep()).toHaveTextContent('newsletter: true')
        expect(sendPreferencesStep()).toHaveTextContent('posthog.messaging.setPreferences(email, {')
        expect(sendPreferencesStep()).toHaveTextContent('secretKey: process.env.POSTHOG_PERSONAL_API_KEY')
        expect(sendPreferencesStep()).not.toHaveTextContent('receipts')

        fireEvent.click(screen.getByTestId('copy-code-button'))
        await waitFor(() => expect(capture).toHaveBeenCalledWith('audience snippet copied', { variant: 'snippet' }))

        fireEvent.click(screen.getByText('Prompt for your coding agent'))
        await waitFor(() => expect(sendPreferencesStep()).toHaveTextContent('`newsletter`, `product-updates`'))
        expect(sendPreferencesStep()).not.toHaveTextContent('receipts')

        fireEvent.click(screen.getByTestId('copy-code-button'))
        await waitFor(() =>
            expect(capture).toHaveBeenCalledWith('audience snippet copied', { variant: 'agent_prompt' })
        )
    })

    it('links to a new personal API key with the hog_flow:write scope', async () => {
        useAudience({ topics: [], recipients: [] })
        renderAudienceAt(urls.audience())

        const keyLink = (await screen.findByText('Create personal API key')).closest('a')
        personalAPIKeysLogic.mount()
        router.actions.push(keyLink?.getAttribute('href') ?? '')

        expect(personalAPIKeysLogic.values.editingKeyId).toBe('new')
        expect(personalAPIKeysLogic.values.editingKey.scopes).toEqual(['hog_flow:write'])
    })
})
