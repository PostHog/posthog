import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { RecipientPageApi } from 'products/messaging/frontend/generated/api.schemas'

import { optOutCategoriesLogic } from '../OptOuts/optOutCategoriesLogic'
import { recipientsLogic } from './recipientsLogic'
import { MockResponse, useRecipientsApiMocks, recipient } from './recipientTestFixtures'

const SEARCH_DEBOUNCE_MS = 300

const PAGES_BY_CURSOR: Record<string, RecipientPageApi> = {
    '': { results: [recipient('alex@example.com'), recipient('jamie@example.com')], next_cursor: 'after-jamie' },
    'after-jamie': { results: [recipient('sam@example.com')], next_cursor: null },
}

describe('recipientsLogic', () => {
    let logic: ReturnType<typeof recipientsLogic.build>
    let requests: URLSearchParams[]

    function useRecipientsResponse(respond: (params: URLSearchParams) => MockResponse | Promise<MockResponse>): void {
        useRecipientsApiMocks({
            recipients: (params) => {
                requests.push(params)
                return respond(params)
            },
            coverage: [200, { persons_without_email: 12 }],
        })
    }

    async function mountLogic(): Promise<void> {
        logic = recipientsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActionsInAnyOrder([
            'loadAudienceRecipientsSuccess',
            'loadAudienceCoverageSuccess',
        ])
    }

    async function searchForJamie(): Promise<void> {
        await expectLogic(logic, () => logic.actions.setSearch('jamie')).toDispatchActions([
            'loadAudienceRecipientsSuccess',
        ])
    }

    beforeEach(() => {
        requests = []
        initKeaTests()
        useRecipientsResponse((params) => [200, PAGES_BY_CURSOR[params.get('cursor') ?? '']])
    })

    afterEach(() => {
        if (logic?.isMounted()) {
            logic.unmount()
        }
        jest.useRealTimers()
        jest.restoreAllMocks()
    })

    it('sends only the last search typed within the debounce window', async () => {
        await mountLogic()
        jest.useFakeTimers()

        logic.actions.setSearch('ja')
        await jest.advanceTimersByTimeAsync(SEARCH_DEBOUNCE_MS - 1)
        logic.actions.setSearch(' jamie ')
        await jest.advanceTimersByTimeAsync(SEARCH_DEBOUNCE_MS)
        jest.useRealTimers()
        await expectLogic(logic).toDispatchActions(['loadAudienceRecipientsSuccess'])

        expect(requests.map((params) => params.get('search'))).toEqual([null, 'jamie'])
        expect(logic.values.searchPending).toBe(false)
    })

    it('names topics from the team topic list', async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/messaging_categories/': {
                    results: [{ id: 'topic-1', key: 'newsletter', name: 'Newsletter' }],
                    next: null,
                },
            },
        })
        logic = recipientsLogic()
        logic.mount()

        await expectLogic(optOutCategoriesLogic).toDispatchActions(['loadCategoriesSuccess'])

        expect(logic.values.topicNames).toEqual({ newsletter: 'Newsletter' })
    })

    it('pages forward with the returned cursor and back to the first page', async () => {
        await mountLogic()

        logic.actions.loadNextPage()
        logic.actions.loadNextPage()
        await expectLogic(logic)
            .toDispatchActions(['loadAudienceRecipientsSuccess'])
            .toMatchValues({
                recipients: [recipient('sam@example.com')],
                currentPage: 2,
                hasNextPage: false,
                hasPreviousPage: true,
            })

        await expectLogic(logic, () => logic.actions.loadPreviousPage())
            .toDispatchActions(['loadAudienceRecipientsSuccess'])
            .toMatchValues({ currentPage: 1, hasNextPage: true, hasPreviousPage: false })

        expect(requests.map((params) => params.get('cursor'))).toEqual([null, 'after-jamie', null])
        expect(requests.every((params) => params.get('limit') === '50')).toBe(true)
    })

    it('shows the loading view until the first page answers', async () => {
        let releaseFirstPage = (): void => {}
        const firstPageReleased = new Promise<void>((resolve) => {
            releaseFirstPage = resolve
        })
        useRecipientsResponse(async () => {
            await firstPageReleased
            return [200, { results: [], next_cursor: null }]
        })
        logic = recipientsLogic()
        logic.mount()

        expect(logic.values.recipientsView).toBe('loading')
        releaseFirstPage()
        await expectLogic(logic).toDispatchActions(['loadAudienceRecipientsSuccess'])
        expect(logic.values.recipientsView).toBe('empty')
    })

    it('keeps paging back available when a later page comes back empty', async () => {
        await mountLogic()
        useRecipientsResponse((params) =>
            params.get('cursor') ? [200, { results: [], next_cursor: null }] : [200, PAGES_BY_CURSOR['']]
        )

        await expectLogic(logic, () => logic.actions.loadNextPage()).toDispatchActions([
            'loadAudienceRecipientsSuccess',
        ])

        expect(logic.values).toMatchObject({ recipientsView: 'results', recipients: [], hasPreviousPage: true })
    })

    it('starts a new search from the first page', async () => {
        await mountLogic()
        await expectLogic(logic, () => logic.actions.loadNextPage()).toDispatchActions([
            'loadAudienceRecipientsSuccess',
        ])

        await expectLogic(logic, () => logic.actions.setSearch('sam')).toDispatchActions([
            'loadAudienceRecipientsSuccess',
        ])

        expect(requests.at(-1)?.get('cursor')).toBeNull()
        expect(requests.at(-1)?.get('search')).toBe('sam')
    })

    it('stays on the current page when the trimmed search does not change', async () => {
        await mountLogic()
        await expectLogic(logic, () => logic.actions.loadNextPage()).toDispatchActions([
            'loadAudienceRecipientsSuccess',
        ])
        jest.useFakeTimers()

        logic.actions.setSearch(' ')
        await jest.advanceTimersByTimeAsync(SEARCH_DEBOUNCE_MS)
        jest.useRealTimers()
        await expectLogic(logic).toFinishAllListeners()

        expect(requests.map((params) => params.get('cursor'))).toEqual([null, 'after-jamie'])
        expect(logic.values.recipients).toEqual([recipient('sam@example.com')])
    })

    it('reloads the first page at once when the search is cleared', async () => {
        await mountLogic()
        await expectLogic(logic, () => logic.actions.setSearch('nobody')).toDispatchActions([
            'loadAudienceRecipientsSuccess',
        ])

        logic.actions.clearSearch()

        expect(logic.values).toMatchObject({ search: '', lastRequest: { search: '', pageCursors: [] } })
        await expectLogic(logic).toDispatchActions(['loadAudienceRecipientsSuccess'])
        expect(requests.map((params) => params.get('search'))).toEqual([null, 'nobody', null])
    })

    it('ignores paging while a new search waits for its debounce', async () => {
        await mountLogic()

        logic.actions.setSearch('sam')
        logic.actions.loadNextPage()
        await expectLogic(logic).toFinishAllListeners()

        const samCursors = requests
            .filter((params) => params.get('search') === 'sam')
            .map((params) => params.get('cursor'))
        expect(samCursors).toEqual([null])
        expect(requests).toHaveLength(2)
        expect(logic.values.hasPreviousPage).toBe(false)
    })

    it.each([
        { outcome: 'fails', response: [500, { detail: 'Query timed out' }] },
        { outcome: 'succeeds', response: [200, { results: [recipient('slow@example.com')], next_cursor: null }] },
    ] as const)('keeps the newest results when an older search $outcome late', async ({ response }) => {
        await mountLogic()
        let answerSlowSearch = (): void => {}
        const slowSearchAnswered = new Promise<void>((resolve) => {
            answerSlowSearch = resolve
        })
        useRecipientsResponse(async (params) => {
            if (params.get('search') === 'slow') {
                await slowSearchAnswered
                return [response[0], response[1]]
            }
            return [200, PAGES_BY_CURSOR['']]
        })

        await expectLogic(logic, () => logic.actions.setSearch('slow')).toDispatchActions(['loadAudienceRecipients'])
        await expectLogic(logic, () => logic.actions.setSearch('jamie')).toDispatchActions([
            'loadAudienceRecipientsSuccess',
        ])
        answerSlowSearch()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values).toMatchObject({
            recipientsView: 'results',
            loadFailed: false,
            recipients: PAGES_BY_CURSOR[''].results,
            shownRequest: { search: 'jamie', pageCursors: [] },
        })
    })

    it('shows the loading view instead of the previous search while a failed search is retried', async () => {
        await mountLogic()
        let answerRetry = (): void => {}
        const retryAnswered = new Promise<void>((resolve) => {
            answerRetry = resolve
        })
        let slowSearchAttempts = 0
        useRecipientsResponse(async (params) => {
            if (params.get('search') !== 'slow') {
                return [200, PAGES_BY_CURSOR['']]
            }
            slowSearchAttempts += 1
            if (slowSearchAttempts > 1) {
                await retryAnswered
            }
            return [500, { detail: 'Query timed out' }]
        })
        await expectLogic(logic, () => logic.actions.setSearch('slow')).toDispatchActions([
            'loadAudienceRecipientsFailure',
        ])

        logic.actions.retryLoadRecipients()

        expect(logic.values).toMatchObject({
            recipientsView: 'loading',
            recipients: [],
            currentPage: null,
            hasNextPage: false,
            hasPreviousPage: false,
        })
        answerRetry()
        await expectLogic(logic).toDispatchActions(['loadAudienceRecipientsFailure'])
        expect(logic.values.recipientsView).toBe('error')
    })

    it.each([
        {
            name: 'a search finds recipients',
            setUp: async (): Promise<void> => {},
            act: (): void => logic.actions.setSearch('jamie'),
            expected: [['audience recipients filtered', { has_results: true }]],
        },
        {
            name: 'a search finds nobody',
            respond: (): MockResponse => [200, { results: [], next_cursor: null }],
            setUp: async (): Promise<void> => {},
            act: (): void => logic.actions.setSearch('nobody'),
            expected: [['audience recipients filtered', { has_results: false }]],
        },
        {
            name: 'the search is cleared with the button',
            setUp: searchForJamie,
            act: (): void => logic.actions.clearSearch(),
            expected: [['audience recipients search cleared', {}]],
        },
        {
            name: 'the search text is deleted',
            setUp: searchForJamie,
            act: (): void => logic.actions.setSearch(''),
            expected: [['audience recipients search cleared', {}]],
        },
        {
            name: 'the next page opens',
            setUp: async (): Promise<void> => {},
            act: (): void => logic.actions.loadNextPage(),
            expected: [['audience recipients paged', { direction: 'next' }]],
        },
        {
            name: 'a search goes back to its first page',
            setUp: async (): Promise<void> => {
                await searchForJamie()
                await expectLogic(logic, () => logic.actions.loadNextPage()).toDispatchActions([
                    'loadAudienceRecipientsSuccess',
                ])
            },
            act: (): void => logic.actions.loadPreviousPage(),
            expected: [['audience recipients paged', { direction: 'previous' }]],
        },
        {
            name: 'a failed load is retried',
            respond: (): MockResponse => [500, { detail: 'Query timed out' }],
            setUp: async (): Promise<void> => {
                await expectLogic(logic, () => logic.actions.setSearch('slow')).toDispatchActions([
                    'loadAudienceRecipientsFailure',
                ])
            },
            act: (): void => logic.actions.retryLoadRecipients(),
            expected: [['audience recipients retried', {}]],
        },
    ])('tracks it when $name', async ({ respond, setUp, act, expected }) => {
        await mountLogic()
        if (respond) {
            useRecipientsResponse(respond)
        }
        await setUp()
        const capture = jest.spyOn(posthog, 'capture')
        capture.mockClear()

        act()
        await expectLogic(logic).toFinishAllListeners()

        expect(capture.mock.calls.filter(([event]) => event.startsWith('audience '))).toEqual(expected)
    })

    it('keeps the current page on screen without a toast when the next page fails, and retries that page', async () => {
        await mountLogic()
        const toastError = jest.spyOn(lemonToast, 'error')
        useRecipientsResponse((params) =>
            params.get('cursor') ? [500, { detail: 'Query timed out' }] : [200, PAGES_BY_CURSOR['']]
        )

        await expectLogic(logic, () => logic.actions.loadNextPage()).toDispatchActions([
            'loadAudienceRecipientsFailure',
        ])

        expect(logic.values).toMatchObject({
            recipientsView: 'results',
            loadFailed: true,
            recipients: PAGES_BY_CURSOR[''].results,
            hasNextPage: true,
        })
        expect(toastError).not.toHaveBeenCalled()

        useRecipientsResponse((params) => [200, PAGES_BY_CURSOR[params.get('cursor') ?? '']])
        await expectLogic(logic, () => logic.actions.retryLoadRecipients()).toDispatchActions([
            'loadAudienceRecipientsSuccess',
        ])

        expect(requests.at(-1)?.get('cursor')).toBe('after-jamie')
        expect(logic.values).toMatchObject({ loadFailed: false, recipients: [recipient('sam@example.com')] })
    })

    it.each(['', '   '])('shows the empty view for a team with no recipient and the search %j', async (search) => {
        useRecipientsResponse(() => [200, { results: [], next_cursor: null }])
        await mountLogic()

        logic.actions.setSearch(search)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.recipientsView).toBe('empty')
    })

    it.each([
        {
            name: 'a search nobody matches',
            search: 'nobody',
            response: [200, { results: [], next_cursor: null }],
            view: 'no-match',
        },
        { name: 'a failed request', search: 'slow', response: [500, { detail: 'Query timed out' }], view: 'error' },
        { name: 'a page of recipients', search: 'jamie', response: [200, PAGES_BY_CURSOR['']], view: 'results' },
    ] as const)('shows the $view view for $name', async ({ search, response, view }) => {
        await mountLogic()
        useRecipientsResponse(() => [response[0], response[1]])

        await expectLogic(logic, () => logic.actions.setSearch(search)).toDispatchActions([
            response[0] === 200 ? 'loadAudienceRecipientsSuccess' : 'loadAudienceRecipientsFailure',
        ])

        expect(logic.values.recipientsView).toBe(view)
    })
})
