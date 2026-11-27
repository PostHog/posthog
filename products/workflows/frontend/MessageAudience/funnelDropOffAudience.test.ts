import { useMocks } from '~/mocks/jest'
import type { MockResolverInfo } from '~/mocks/utils'
import { FunnelsActorsQuery, FunnelsQuery, InsightActorsQuery, NodeKind } from '~/queries/schema/schema-general'

jest.unmock('posthog-js')

const INGESTION_HOST = 'https://ingest.example.com'
const SETTLED = 'test settled'

type SentEvent = { event: string; properties: Record<string, any> }
type ActorRow = Record<string, any>

interface ActorsPage {
    rows: ActorRow[]
    hasMore?: boolean
    failed?: boolean
}

const funnelsQuery: FunnelsQuery = {
    kind: NodeKind.FunnelsQuery,
    series: [
        { kind: NodeKind.EventsNode, event: '$pageview' },
        { kind: NodeKind.EventsNode, event: 'signed up' },
    ],
}
const dropOff: FunnelsActorsQuery = { kind: NodeKind.FunnelsActorsQuery, source: funnelsQuery, funnelStep: -2 }
const dropOffWithBreakdown: FunnelsActorsQuery = {
    kind: NodeKind.FunnelsActorsQuery,
    source: { ...funnelsQuery, breakdownFilter: { breakdown: '$browser', breakdown_type: 'event' } },
    funnelStep: -2,
    funnelStepBreakdown: 'Chrome',
}
const convertedStep: FunnelsActorsQuery = { ...dropOff, funnelStep: 2 }
const groupDropOff: FunnelsActorsQuery = { ...dropOff, source: { ...funnelsQuery, aggregation_group_type_index: 0 } }
const sessionDropOff: FunnelsActorsQuery = {
    ...dropOff,
    source: { ...funnelsQuery, funnelsFilter: { funnelAggregateByHogQL: 'properties.$session_id' } },
}
const trends: InsightActorsQuery = {
    kind: NodeKind.InsightActorsQuery,
    source: { kind: NodeKind.TrendsQuery, series: [{ kind: NodeKind.EventsNode, event: '$pageview' }] },
}

const person = (index: number, properties?: Record<string, any>): ActorRow => ({
    id: `person-${index}`,
    distinct_ids: [`user-${index}`],
    is_identified: true,
    properties,
    created_at: '2024-01-01T00:00:00Z',
})
const peopleWithEmail = (count: number): ActorRow[] =>
    Array.from({ length: count }, (_, index) => person(index, { email: `user-${index}@example.com` }))
const peopleWithoutEmail: ActorRow[] = [
    person(1, { name: 'No address' }),
    person(2, { email: 'not an address' }),
    person(3),
]
const companies: ActorRow[] = [
    { id: 'company-1', group_key: 'company-1', group_type_index: 0, group_properties: {}, created_at: '' },
]

describe('funnel drop-off audience checked', () => {
    const sentEvents: SentEvent[] = []
    let posthog: typeof import('posthog-js').default
    let initKeaTests: typeof import('~/test/init').initKeaTests
    let expectLogic: typeof import('kea-test-utils').expectLogic
    let personsModalLogic: typeof import('scenes/trends/persons-modal/personsModalLogic').personsModalLogic
    let logic: ReturnType<typeof personsModalLogic.build>
    let actorsRequests: { search: string; offset?: number; release: () => void }[]
    let firstRequestArrived: Promise<void>

    beforeAll(async () => {
        jest.resetModules()
        posthog = (await import('posthog-js')).default
        posthog.init('phc_example', {
            api_host: INGESTION_HOST,
            persistence: 'memory',
            request_batching: false,
            disable_compression: true,
            advanced_disable_flags: true,
            autocapture: false,
            capture_pageview: false,
        })
        initKeaTests = (await import('~/test/init')).initKeaTests
        expectLogic = (await import('kea-test-utils')).expectLogic
        personsModalLogic = (await import('scenes/trends/persons-modal/personsModalLogic')).personsModalLogic
    })

    async function deliveredAudienceEvents(): Promise<Record<string, any>[]> {
        posthog.capture(SETTLED)
        for (let tick = 0; tick < 100 && !sentEvents.some(({ event }) => event === SETTLED); tick++) {
            await jest.advanceTimersByTimeAsync(10)
        }
        await jest.advanceTimersByTimeAsync(100)
        expect(sentEvents.map(({ event }) => event)).toContain(SETTLED)
        const sharedKeys = new Set(Object.keys(sentEvents.find(({ event }) => event === SETTLED)?.properties ?? {}))
        return sentEvents
            .filter(({ event }) => event === 'funnel drop-off audience checked')
            .map(({ properties }) =>
                Object.fromEntries(
                    Object.entries(properties).filter(([key]) => !key.startsWith('$sdk_debug_') && !sharedKeys.has(key))
                )
            )
    }

    function actorsQueryMocks(pages: ActorsPage[], { holdFirstRequest = false } = {}): Parameters<typeof useMocks>[0] {
        let arrive = (): void => {}
        firstRequestArrived = new Promise<void>((resolve) => {
            arrive = resolve
        })
        return {
            post: {
                [`${INGESTION_HOST}/e/`]: async ({ request }: MockResolverInfo) => {
                    sentEvents.push(...((await request.json()) as { batch: SentEvent[] }).batch)
                    return [200, { status: 1 }]
                },
                '/api/environments/:team_id/query/:kind/': async ({ params, request }: MockResolverInfo) => {
                    if (params.kind !== NodeKind.ActorsQuery) {
                        return [200, {}]
                    }
                    const { query } = (await request.json()) as { query: { search?: string; offset?: number } }
                    let release = (): void => {}
                    const released = new Promise<void>((resolve) => {
                        release = resolve
                    })
                    actorsRequests.push({ search: query.search ?? '', offset: query.offset, release })
                    const page = pages[Math.min(actorsRequests.length, pages.length) - 1]
                    arrive()
                    if (holdFirstRequest && actorsRequests.length === 1) {
                        await released
                    }
                    if (page.failed) {
                        return [500, { detail: 'Query failed' }]
                    }
                    return [
                        200,
                        {
                            results: page.rows.map((row) => [row]),
                            columns: ['actor'],
                            hasMore: page.hasMore ?? false,
                            limit: 100,
                            offset: query.offset ?? 0,
                            missing_actors_count: 0,
                        },
                    ]
                },
            },
        }
    }

    async function openModal(query: FunnelsActorsQuery | InsightActorsQuery): Promise<void> {
        logic = personsModalLogic({ query, url: null })
        logic.mount()
        await firstRequestArrived
    }

    async function searchFor(search: string): Promise<void> {
        logic.actions.setSearchTerm(search)
        await jest.advanceTimersByTimeAsync(500)
    }

    async function settle(): Promise<void> {
        const listeners = expectLogic(logic).toFinishAllListeners()
        await jest.runOnlyPendingTimersAsync()
        await listeners
    }

    beforeEach(() => {
        initKeaTests()
        jest.useFakeTimers()
        actorsRequests = []
        sentEvents.length = 0
    })

    afterEach(() => {
        logic?.unmount()
        jest.useRealTimers()
    })

    it.each([
        {
            name: 'a drop-off where one person has an address',
            query: dropOff,
            rows: [...peopleWithEmail(1), ...peopleWithoutEmail],
            expected: [{ has_results: true, with_email_bucket: '1-9' }],
        },
        {
            name: 'a drop-off with a breakdown',
            query: dropOffWithBreakdown,
            rows: peopleWithEmail(10),
            expected: [{ has_results: true, with_email_bucket: '10-99' }],
        },
        {
            name: 'a full first page of people with an address',
            query: dropOff,
            rows: peopleWithEmail(100),
            expected: [{ has_results: true, with_email_bucket: '100+' }],
        },
        {
            name: 'an empty drop-off',
            query: dropOff,
            rows: [],
            expected: [{ has_results: false, with_email_bucket: '0' }],
        },
        {
            name: 'a drop-off where no one has an address',
            query: dropOff,
            rows: peopleWithoutEmail,
            expected: [{ has_results: true, with_email_bucket: '0' }],
        },
        { name: 'a converted step', query: convertedStep, rows: peopleWithEmail(3), expected: [] },
        { name: 'a trends query', query: trends, rows: peopleWithEmail(3), expected: [] },
        { name: 'a group funnel', query: groupDropOff, rows: companies, expected: [] },
        { name: 'a funnel of unique sessions', query: sessionDropOff, rows: [], expected: [] },
        {
            name: 'a drop-off whose first load fails',
            query: dropOff,
            rows: peopleWithEmail(3),
            failed: true,
            expected: [],
        },
    ])('reports the audience of $name once its first page loads', async ({ query, rows, failed, expected }) => {
        useMocks(actorsQueryMocks([{ rows, failed }]))

        await openModal(query)
        await settle()

        expect(await deliveredAudienceEvents()).toEqual(expected)
    })

    it('sends no event when a search replaces the first request', async () => {
        useMocks(actorsQueryMocks([{ rows: peopleWithEmail(3) }], { holdFirstRequest: true }))

        await openModal(dropOff)
        await searchFor('example')
        actorsRequests[0].release()
        await settle()

        expect(actorsRequests.map(({ search }) => search)).toEqual(['', 'example'])
        expect(await deliveredAudienceEvents()).toEqual([])
    })

    it('sends no event when the modal closes before the first page loads', async () => {
        useMocks(actorsQueryMocks([{ rows: peopleWithEmail(3) }], { holdFirstRequest: true }))

        await openModal(dropOff)
        logic.actions.closeModal()
        actorsRequests[0].release()
        await settle()

        expect(await deliveredAudienceEvents()).toEqual([])
    })

    it.each([
        { name: 'a search', next: async (): Promise<void> => searchFor('example') },
        { name: 'load more', next: async (): Promise<void> => logic.actions.loadNextActors() },
        {
            name: 'a breakdown change',
            next: async (): Promise<void> => logic.actions.updateActorsQuery({ funnelStepBreakdown: 'Firefox' }),
        },
    ])('sends no second event for $name after the first page loaded', async ({ next }) => {
        useMocks(actorsQueryMocks([{ rows: peopleWithEmail(3), hasMore: true }, { rows: peopleWithEmail(20) }]))

        await openModal(dropOffWithBreakdown)
        await settle()
        await next()
        await settle()

        expect(actorsRequests).toHaveLength(2)
        expect(await deliveredAudienceEvents()).toEqual([{ has_results: true, with_email_bucket: '1-9' }])
    })
})
