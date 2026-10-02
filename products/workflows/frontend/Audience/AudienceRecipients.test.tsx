import '@testing-library/jest-dom'

import { cleanup, render, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { MessageCategoryApi, RecipientApi } from 'products/messaging/frontend/generated/api.schemas'

import { AudienceRecipients } from './AudienceRecipients'
import { recipientsLogic } from './recipientsLogic'

function recipient(email: string): RecipientApi {
    return {
        email,
        all_marketing: 'OPTED_OUT',
        topics: {},
        suppression: null,
        persons: [],
        person_count: 1,
        last_sent_at: null,
        preferences_updated_at: null,
    }
}

function topic(key: string, name: string, categoryType: 'marketing' | 'transactional'): MessageCategoryApi {
    return {
        id: key,
        key,
        name,
        category_type: categoryType,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        created_by: null,
    }
}

const TOPICS = [topic('newsletter', 'Newsletter', 'marketing'), topic('receipts', 'Receipts', 'transactional')]

const input = (): HTMLInputElement => document.querySelector<HTMLInputElement>('input[role="combobox"]')!
const pills = (): string[] =>
    [...document.querySelectorAll('[aria-label^="Remove filter "]')].map((button) =>
        button.getAttribute('aria-label')!.replace('Remove filter ', '')
    )
const suggestions = (): string[] =>
    [...document.querySelectorAll('[role="option"]')].map((option) => option.textContent ?? '')

describe('AudienceRecipients', () => {
    let requests: URL[]

    function useRecipientsApi(): void {
        useMocks({
            get: {
                '/api/projects/:team_id/messaging_recipients/': ({ request }) => {
                    const requestUrl = new URL(request.url)
                    requests.push(requestUrl)
                    const cursor = requestUrl.searchParams.get('cursor')
                    return [
                        200,
                        cursor
                            ? { results: [recipient('sam@example.com')], next_cursor: null }
                            : { results: [recipient('alex@example.com')], next_cursor: 'after-alex' },
                    ]
                },
                '/api/projects/:team_id/messaging_recipients/coverage/': { persons_without_email: 0 },
                '/api/projects/:team_id/messaging_categories/': { count: TOPICS.length, results: TOPICS },
            },
        })
    }

    function startAt(url: string): void {
        initKeaTests()
        router.actions.push(url)
        render(<AudienceRecipients />)
    }

    beforeEach(() => {
        requests = []
        useRecipientsApi()
    })

    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })

    it('offers All marketing and marketing topics on the topic facets', async () => {
        startAt(urls.audience('recipients'))
        const user = userEvent.setup()

        await user.click(input())
        await user.keyboard('subscribed:')

        await waitFor(() => expect(suggestions()).toEqual(['All marketing', 'Newsletter']))
    })

    it('sends the API value for a value typed in any case', async () => {
        startAt(urls.audience('recipients'))
        const user = userEvent.setup()

        await user.click(input())
        await user.keyboard('suppressed:bounce person:NONE ')

        await waitFor(() =>
            expect(requests.at(-1)?.searchParams.getAll('filter')).toEqual(['suppressed:BOUNCE', 'person:none'])
        )
        expect(pills()).toEqual(['Suppressed: Bounces', 'Person: No person'])
    })

    it('names the filter the API rejects instead of offering a retry', async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/messaging_recipients/': ({ request }) =>
                    new URL(request.url).searchParams.getAll('filter').includes('person:non')
                        ? [
                              400,
                              { type: 'validation_error', attr: 'filter', detail: 'Unknown value `non` for `person`.' },
                          ]
                        : [200, { results: [recipient('alex@example.com')], next_cursor: null }],
            },
        })
        startAt(urls.audience('recipients'))
        const user = userEvent.setup()

        await user.click(input())
        await user.keyboard('person:non ')

        await waitFor(() =>
            expect(document.querySelector('[data-attr="audience-recipients"]')).toHaveTextContent(
                'Unknown value "non" for "person". Remove that filter, or pick a value from the suggestions.'
            )
        )
        expect(document.querySelector('[data-attr="audience-recipients-retry"]')).toBeNull()
    })

    it('sends each pill as its own filter from the first page, and restores the pills from the URL', async () => {
        const capture = jest.spyOn(posthog, 'capture')
        startAt(urls.audience('recipients'))
        await expectLogic(recipientsLogic).toDispatchActions(['loadAudienceRecipientsSuccess'])
        await expectLogic(recipientsLogic, () => recipientsLogic.actions.loadNextPage()).toDispatchActions([
            'loadAudienceRecipientsSuccess',
        ])
        const user = userEvent.setup()

        await user.click(input())
        await user.keyboard('unsubscribed:{Enter}-person:no{Enter}')

        await waitFor(() =>
            expect(requests.at(-1)?.searchParams.getAll('filter')).toEqual([
                'unsubscribed:all-marketing',
                '-person:none',
            ])
        )
        expect(requests.at(-1)?.searchParams.get('cursor')).toBeNull()
        expect(pills()).toEqual(['Unsubscribed from: All marketing', 'Person is not: No person'])

        const filteredUrl = `${router.values.location.pathname}${router.values.location.search}`
        cleanup()
        requests = []
        startAt(filteredUrl)

        await waitFor(() => expect(pills()).toEqual(['Unsubscribed from: All marketing', 'Person is not: No person']))
        expect(requests.map((request) => request.searchParams.getAll('filter'))).toEqual([
            ['unsubscribed:all-marketing', '-person:none'],
        ])
        const filteredEvents = capture.mock.calls.filter(([event]) => event === 'audience recipients filtered')
        expect(filteredEvents).toEqual([
            ['audience recipients filtered', { facets: ['unsubscribed'] }],
            ['audience recipients filtered', { facets: ['person', 'unsubscribed'] }],
        ])
    })
})
