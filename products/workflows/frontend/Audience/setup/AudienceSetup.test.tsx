import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { personalAPIKeysLogic } from 'scenes/settings/user/personalAPIKeysLogic'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import type { MessageCategoryApi, RecipientApi } from 'products/messaging/frontend/generated/api.schemas'

import { AudienceScene } from '../AudienceScene'
import { audienceSceneLogic } from '../audienceSceneLogic'
import { MockResponse, recipient, topic, topicsPage, useRecipientsApiMocks } from '../recipientTestFixtures'

const SETUP_HEADING = 'Bring your recipients into PostHog'
const SEARCH_PLACEHOLDER = 'Search by email address'

const RECIPIENT = recipient('jamie@example.com')

describe('Audience setup', () => {
    function useAudience({
        topics,
        recipients,
        recipientsResponse = [200, { results: recipients, next_cursor: null }],
        personsWithoutEmail = 0,
    }: {
        topics: MessageCategoryApi[] | 'failing' | (() => Promise<MockResponse>)
        recipients: RecipientApi[]
        recipientsResponse?: MockResponse
        personsWithoutEmail?: number
    }): void {
        useRecipientsApiMocks({
            recipients: () => recipientsResponse,
            coverage: [200, { persons_without_email: personsWithoutEmail }],
            topics: () =>
                typeof topics === 'function'
                    ? topics()
                    : topics === 'failing'
                      ? [500, { detail: 'Server error' }]
                      : topicsPage(topics),
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
        {
            audience: 'topics that failed to load',
            topics: 'failing' as const,
            recipients: [],
            shows: 'No recipients yet',
        },
    ])('with $audience, /audience shows "$shows"', async ({ topics, recipients, shows }) => {
        useAudience({ topics, recipients })

        renderAudienceAt(urls.audience())

        expect(await screen.findByText(shows)).toBeInTheDocument()
        const setupShown = shows === SETUP_HEADING
        expect(screen.queryByPlaceholderText(SEARCH_PLACEHOLDER) === null).toBe(setupShown)
        const setupViews = capture.mock.calls.filter(([event]) => event === 'audience setup viewed')
        expect(setupViews).toEqual(setupShown ? [['audience setup viewed', { source: 'empty_state' }]] : [])
    })

    it('shows neither the list nor setup until the topics have loaded', async () => {
        let releaseTopics = (): void => {}
        const topicsReleased = new Promise<void>((resolve) => {
            releaseTopics = resolve
        })
        useAudience({
            topics: async () => {
                await topicsReleased
                return topicsPage([])
            },
            recipients: [],
        })
        renderAudienceAt(urls.audience())
        await waitFor(() =>
            expect(document.querySelector('[data-attr="audience-recipients-first-load"]')).toBeInTheDocument()
        )

        expect(screen.queryByPlaceholderText(SEARCH_PLACEHOLDER)).not.toBeInTheDocument()
        expect(screen.queryByText(SETUP_HEADING)).not.toBeInTheDocument()

        releaseTopics()

        expect(await screen.findByText(SETUP_HEADING)).toBeInTheDocument()
    })

    it('shows the access denied screen instead of setup to a member without access to recipients', async () => {
        useAudience({
            topics: [],
            recipients: [],
            recipientsResponse: [
                403,
                { code: 'permission_denied', detail: 'You need hog_flow viewer access to view recipients.' },
            ],
        })

        renderAudienceAt(urls.audienceSetup())

        expect(await screen.findByText(/viewer access to Workflows/)).toBeInTheDocument()
        expect(screen.queryByText(SETUP_HEADING)).not.toBeInTheDocument()
    })

    it('keeps the unreachable persons notice above setup', async () => {
        useAudience({ topics: [], recipients: [], personsWithoutEmail: 3 })

        renderAudienceAt(urls.audience())

        expect(await screen.findByText(SETUP_HEADING)).toBeInTheDocument()
        expect(await screen.findByText("3 persons can't be reached")).toBeInTheDocument()
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

        await waitFor(() => expect(sendPreferencesStep()).toHaveTextContent('"product-updates": true'))
        expect(sendPreferencesStep()).toHaveTextContent('newsletter: false')
        expect(sendPreferencesStep()).toHaveTextContent('Set each value from what the user picked')
        expect(sendPreferencesStep()).toHaveTextContent('posthog.messaging.setPreferences(email, {')
        expect(sendPreferencesStep()).toHaveTextContent('secretKey: process.env.POSTHOG_PERSONAL_API_KEY')
        expect(sendPreferencesStep()).toHaveTextContent('enableLocalEvaluation: false')
        expect(sendPreferencesStep()).not.toHaveTextContent('receipts')

        fireEvent.click(screen.getByTestId('copy-code-button'))
        await waitFor(() => expect(capture).toHaveBeenCalledWith('audience snippet copied', { variant: 'snippet' }))

        fireEvent.click(screen.getByText('Prompt for your coding agent'))
        await waitFor(() => expect(sendPreferencesStep()).toHaveTextContent('"newsletter", "product-updates"'))
        expect(sendPreferencesStep()).not.toHaveTextContent('receipts')

        fireEvent.click(screen.getByTestId('copy-code-button'))
        await waitFor(() =>
            expect(capture).toHaveBeenCalledWith('audience snippet copied', { variant: 'agent_prompt' })
        )
    })

    it('offers a retry instead of a snippet without topic keys when the topics fail to load', async () => {
        useAudience({ topics: 'failing', recipients: [RECIPIENT] })
        renderAudienceAt(urls.audienceSetup())

        expect(await screen.findByText(/Couldn't load your topics/)).toBeInTheDocument()
        expect(sendPreferencesStep()).not.toHaveTextContent('setPreferences(email')

        useAudience({ topics: [topic('newsletter')], recipients: [RECIPIENT] })
        fireEvent.click(screen.getAllByTestId('audience-setup-retry-topics')[0])

        await waitFor(() => expect(sendPreferencesStep()).toHaveTextContent('newsletter: false'))
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
