import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { FacetSearchValue } from 'lib/components/FacetSearchBar/facetSearch'
import { PERSON_DISPLAY_NAME_COLUMN_NAME } from 'lib/constants'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { PropertyFilterType, PropertyOperator } from '~/types'

import type { RecipientApi, RecipientPageApi } from 'products/messaging/frontend/generated/api.schemas'

import { recipientsLogic } from './recipientsLogic'
import { unreachablePersonsUrl } from './unreachablePersonsUrl'

const SEARCH_DEBOUNCE_MS = 300

function recipient(email: string): RecipientApi {
    return {
        email,
        all_marketing: 'NO_PREFERENCE',
        topics: {},
        suppression: null,
        persons: [],
        person_count: 0,
        last_sent_at: null,
        preferences_updated_at: null,
    }
}

function textSearch(text: string): FacetSearchValue {
    return { filters: [], text }
}

const PAGES_BY_CURSOR: Record<string, RecipientPageApi> = {
    '': { results: [recipient('alex@example.com'), recipient('jamie@example.com')], next_cursor: 'after-jamie' },
    'after-jamie': { results: [recipient('sam@example.com')], next_cursor: null },
}

describe('recipientsLogic', () => {
    let logic: ReturnType<typeof recipientsLogic.build>
    let requests: URLSearchParams[]

    type MockResponse = [number, unknown]

    function useRecipientsResponse(respond: (params: URLSearchParams) => MockResponse | Promise<MockResponse>): void {
        useMocks({
            get: {
                '/api/projects/:team_id/messaging_recipients/': ({ request }) => {
                    const params = new URL(request.url).searchParams
                    requests.push(params)
                    return respond(params)
                },
                '/api/projects/:team_id/messaging_recipients/coverage/': { persons_without_email: 12 },
            },
        })
    }

    async function mountLogic(): Promise<void> {
        logic = recipientsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadAudienceRecipientsSuccess', 'loadAudienceCoverageSuccess'])
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

    it('sends and links only the last search typed within the debounce window', async () => {
        await mountLogic()
        jest.useFakeTimers()

        logic.actions.setSearchValue(textSearch('ja'))
        logic.actions.setSearchValue(textSearch('jam'))
        logic.actions.setSearchValue(textSearch('jamie'))
        expect(router.values.searchParams.q).toBeUndefined()
        jest.advanceTimersByTime(SEARCH_DEBOUNCE_MS)
        jest.useRealTimers()
        await expectLogic(logic).toDispatchActions(['loadAudienceRecipientsSuccess'])

        expect(router.values.searchParams.q).toBe('jamie')

        expect(requests.map((params) => params.get('search'))).toEqual([null, 'jamie'])
    })

    it('clears the search and its link with one request, even while a new search waits for its debounce', async () => {
        await mountLogic()
        await expectLogic(logic, () => logic.actions.setSearchValue(textSearch('sam'))).toDispatchActions([
            'loadAudienceRecipientsSuccess',
        ])
        expect(router.values.searchParams.q).toBe('sam')
        jest.useFakeTimers()

        logic.actions.setSearchValue(textSearch('ja'))
        logic.actions.clearSearch()
        jest.advanceTimersByTime(SEARCH_DEBOUNCE_MS)
        jest.useRealTimers()
        await expectLogic(logic).toFinishAllListeners()

        expect(requests.map((params) => params.get('search'))).toEqual([null, 'sam', null])
        expect(router.values.searchParams.q).toBeUndefined()
    })

    it('pages forward with the returned cursor and back to the first page', async () => {
        await mountLogic()

        logic.actions.loadNextPage()
        expect(logic.values.hasNextPage).toBe(false)
        logic.actions.loadNextPage()
        await expectLogic(logic)
            .toDispatchActions(['loadAudienceRecipientsSuccess'])
            .toMatchValues({ recipients: [recipient('sam@example.com')], hasNextPage: false, hasPreviousPage: true })

        await expectLogic(logic, () => logic.actions.loadPreviousPage())
            .toDispatchActions(['loadAudienceRecipientsSuccess'])
            .toMatchValues({ hasNextPage: true, hasPreviousPage: false })

        expect(requests.map((params) => params.get('cursor'))).toEqual([null, 'after-jamie', null])
        expect(requests.every((params) => params.get('limit') === '50')).toBe(true)
    })

    it('starts a new search from the first page', async () => {
        await mountLogic()
        await expectLogic(logic, () => logic.actions.loadNextPage()).toDispatchActions([
            'loadAudienceRecipientsSuccess',
        ])

        await expectLogic(logic, () => logic.actions.setSearchValue(textSearch('sam'))).toDispatchActions([
            'loadAudienceRecipientsSuccess',
        ])

        expect(requests.at(-1)?.get('cursor')).toBeNull()
        expect(requests.at(-1)?.get('search')).toBe('sam')
    })

    it('ignores paging while a new search waits for its debounce', async () => {
        await mountLogic()

        logic.actions.setSearchValue(textSearch('sam'))
        logic.actions.loadNextPage()
        await expectLogic(logic).toFinishAllListeners()

        const samCursors = requests
            .filter((params) => params.get('search') === 'sam')
            .map((params) => params.get('cursor'))
        expect(samCursors).toEqual([null])
        expect(requests).toHaveLength(2)
        expect(logic.values.hasPreviousPage).toBe(false)
    })

    it('keeps the newest results when an older search fails late', async () => {
        await mountLogic()
        let failSlowSearch = (): void => {}
        const slowSearchFailed = new Promise<void>((resolve) => {
            failSlowSearch = resolve
        })
        useRecipientsResponse(async (params) => {
            if (params.get('search') === 'slow') {
                await slowSearchFailed
                return [500, { detail: 'Query timed out' }]
            }
            return [200, PAGES_BY_CURSOR['']]
        })

        await expectLogic(logic, () => logic.actions.setSearchValue(textSearch('slow'))).toDispatchActions([
            'loadAudienceRecipients',
        ])
        await expectLogic(logic, () => logic.actions.setSearchValue(textSearch('jamie'))).toDispatchActions([
            'loadAudienceRecipientsSuccess',
        ])
        failSlowSearch()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.recipientsView).toBe('results')
        expect(logic.values.recipients).toEqual(PAGES_BY_CURSOR[''].results)
    })

    it('keeps the current page on screen when the next page fails', async () => {
        await mountLogic()
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
    })

    it.each([
        { name: 'no recipient at all', search: '', response: [200, { results: [], next_cursor: null }], view: 'empty' },
        {
            name: 'a search nobody matches',
            search: 'nobody',
            response: [200, { results: [], next_cursor: null }],
            view: 'no-match',
        },
        {
            name: 'a search of only spaces',
            search: '   ',
            response: [200, { results: [], next_cursor: null }],
            view: 'empty',
        },
        { name: 'a failed request', search: 'slow', response: [500, { detail: 'Query timed out' }], view: 'error' },
        { name: 'a page of recipients', search: 'jamie', response: [200, PAGES_BY_CURSOR['']], view: 'results' },
    ] as const)('shows the $view view for $name', async ({ search, response, view }) => {
        useRecipientsResponse(() => [response[0], response[1]])
        logic = recipientsLogic()
        logic.mount()

        await expectLogic(logic, () => logic.actions.setSearchValue(textSearch(search))).toFinishAllListeners()

        expect(logic.values.recipientsView).toBe(view)
    })

    it('links unreachable persons to the persons list filtered to persons with no email', () => {
        router.actions.push(unreachablePersonsUrl())
        const { q } = router.values.hashParams

        expect(router.values.location.pathname).toContain(urls.persons())
        expect(q.full).toBe(true)
        expect(q.source.kind).toBe('ActorsQuery')
        // Without an explicit select the persons list renders its person column as "Unknown"
        expect(q.source.select).toContain(PERSON_DISPLAY_NAME_COLUMN_NAME)
        expect(q.source.properties).toEqual([
            { type: PropertyFilterType.Person, key: 'email', operator: PropertyOperator.IsNotSet },
        ])
    })
})
