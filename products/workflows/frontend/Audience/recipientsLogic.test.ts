import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

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

const PAGES_BY_CURSOR: Record<string, RecipientPageApi> = {
    '': { results: [recipient('alex@example.com'), recipient('jamie@example.com')], next_cursor: 'after-jamie' },
    'after-jamie': { results: [recipient('sam@example.com')], next_cursor: null },
}

describe('recipientsLogic', () => {
    let logic: ReturnType<typeof recipientsLogic.build>
    let requests: URLSearchParams[]

    function useRecipientsResponse(respond: (params: URLSearchParams) => [number, unknown]): void {
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
        await expectLogic(logic).toDispatchActions(['loadAudienceRecipientsSuccess', 'loadCoverageSuccess'])
    }

    beforeEach(() => {
        requests = []
        initKeaTests()
        useRecipientsResponse((params) => [200, PAGES_BY_CURSOR[params.get('cursor') ?? '']])
    })

    afterEach(() => {
        logic?.unmount()
        jest.useRealTimers()
        jest.restoreAllMocks()
    })

    it('sends only the last search typed within the debounce window', async () => {
        await mountLogic()
        jest.useFakeTimers()

        logic.actions.setSearch('ja')
        logic.actions.setSearch('jam')
        logic.actions.setSearch('jamie')
        jest.advanceTimersByTime(SEARCH_DEBOUNCE_MS)
        jest.useRealTimers()
        await expectLogic(logic).toDispatchActions(['loadAudienceRecipientsSuccess'])

        expect(requests.map((params) => params.get('search'))).toEqual([null, 'jamie'])
    })

    it('pages forward with the returned cursor and back to the first page', async () => {
        await mountLogic()

        await expectLogic(logic, () => logic.actions.loadNextPage())
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

        await expectLogic(logic, () => logic.actions.setSearch('sam')).toDispatchActions([
            'loadAudienceRecipientsSuccess',
        ])

        expect(requests.at(-1)?.get('cursor')).toBeNull()
        expect(requests.at(-1)?.get('search')).toBe('sam')
    })

    it.each([
        { name: 'no recipient at all', search: '', response: [200, { results: [], next_cursor: null }], view: 'empty' },
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

    it('links unreachable persons to the persons list filtered to persons with no email', async () => {
        const capture = jest.spyOn(posthog, 'capture')
        await mountLogic()

        router.actions.push(unreachablePersonsUrl())
        const { q } = router.values.hashParams

        expect(router.values.location.pathname).toContain(urls.persons())
        expect(q.source.kind).toBe('ActorsQuery')
        expect(q.source.properties).toEqual([
            { type: PropertyFilterType.Person, key: 'email', operator: PropertyOperator.IsNotSet },
        ])

        logic.actions.openUnreachablePersons()
        expect(capture).toHaveBeenCalledWith('audience unreachable persons opened', { count: 12 })
    })
})
