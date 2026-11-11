import { MOCK_TEAM_ID } from 'lib/api.mock'

import { render, screen, waitFor } from '@testing-library/react'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import { createElement } from 'react'

import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import * as generatedApi from 'products/workflows/frontend/generated/api'
import type { HogFlowBatchJobApi } from 'products/workflows/frontend/generated/api.schemas'

import { broadcastsLogic } from './broadcastsLogic'

const DRAFT = { id: 'draft-1', name: 'Draft', status: 'draft', tags: ['vip'] }
const LIVE = { id: 'live-1', name: 'Live', status: 'active', tags: ['vip'] }
const RUN = { id: 'job-2', status: 'completed', created_at: '2026-01-01T00:00:00Z' } as HogFlowBatchJobApi
const OLDER_RUN = { id: 'job-1', status: 'active', created_at: '2025-12-01T00:00:00Z' } as HogFlowBatchJobApi
const LIVE_DETAILS = {
    latestBatchJob: RUN,
    totals: { email_sent: 120, failed: 3 },
    hasPendingSchedule: true,
    batchJobStatuses: ['completed'],
}

type Flow = typeof DRAFT & { type?: string; created_by?: string; broadcast_status?: string }

const drafts = (count: number, name: string, extra: Partial<Flow> = {}): Flow[] =>
    Array.from({ length: count }, (_, i) => ({ ...DRAFT, id: `${name}-${i}`, name: `${name} ${i}`, ...extra }))

describe('broadcastsLogic', () => {
    let logic: ReturnType<typeof broadcastsLogic.build>
    let listed: Record<string, string>[]
    let flows: Flow[]
    let runs: Record<string, HogFlowBatchJobApi[]>
    let schedules: Record<string, { status: string }[]>
    let sends: Record<string, Record<string, number>>
    // Each fault fails the next request to its endpoint, then clears, so a test can wait until it was served.
    let failing: Set<'list' | 'runs' | 'schedules' | 'metrics'>
    let held: { list?: Promise<void>; runs?: Promise<void> }

    const listFlows = async ({ request }: { request: Request }): Promise<[number, any]> => {
        const query = Object.fromEntries(new URL(request.url).searchParams)
        listed.push(query)
        await held.list
        if (failing.delete('list')) {
            return [500, { detail: 'boom' }]
        }
        const matches = flows.filter(
            (flow) =>
                (!query.type || (flow.type ?? 'broadcast') === query.type) &&
                (!query.search || flow.name.includes(query.search)) &&
                (!query.broadcast_status || flow.broadcast_status === query.broadcast_status) &&
                (!query.created_by || flow.created_by === query.created_by) &&
                (!query.tags || JSON.parse(query.tags).some((tag: string) => flow.tags.includes(tag)))
        )
        const offset = Number(query.offset)
        return [200, { count: matches.length, results: matches.slice(offset, offset + Number(query.limit)) }]
    }

    // Stands in for the app_metrics table: counts are filed per run, and only a filter on the run narrows them.
    const queryMetrics = async ({ request }: { request: Request }): Promise<[number, any]> => {
        if (failing.delete('metrics')) {
            return [500, { detail: 'timeout' }]
        }
        const { query } = await request.json()
        const job = /app_source_id\s*=\s*'([^']+)'/.exec(query.query)?.[1]
        const totals: Record<string, number> = {}
        const runsCounted = Object.entries(sends).filter(([id]) => !job || id === job)
        for (const [metric, count] of runsCounted.flatMap(([, counts]) => Object.entries(counts))) {
            totals[metric] = (totals[metric] ?? 0) + count
        }
        return [200, { results: Object.entries(totals).map(([metric, total]) => [total, metric]) }]
    }

    const reload = async (): Promise<void> => {
        logic.actions.loadBroadcasts()
        await expectLogic(logic).toDispatchActions(['loadBroadcastsSuccess'])
    }

    const loadLiveRow = async (): Promise<void> => {
        flows = [LIVE]
        runs[LIVE.id] = [RUN]
        schedules[LIVE.id] = [{ status: 'active' }]
        sends = { [RUN.id]: LIVE_DETAILS.totals }
        await reload()
        await waitFor(() => expect(logic.values.rowDetailsById[LIVE.id]).toEqual(LIVE_DETAILS))
    }

    const settleRequestsAheadOfANewOne = async (): Promise<void> => {
        await generatedApi.hogFlowsBatchJobsList(String(MOCK_TEAM_ID), LIVE.id)
        await new Promise((resolve) => setTimeout(resolve, 0))
    }

    beforeEach(async () => {
        localStorage.clear()
        listed = []
        flows = []
        runs = {}
        schedules = {}
        sends = {}
        failing = new Set()
        held = {}
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/': listFlows,
                '/api/projects/:team_id/hog_flows/': listFlows,
                '/api/projects/:team_id/hog_flows/:id/batch_jobs/': async ({ params }) => {
                    await held.runs
                    return failing.delete('runs') ? [500, {}] : [200, runs[String(params.id)] ?? []]
                },
                '/api/projects/:team_id/hog_flows/:id/schedules/': ({ params }) =>
                    failing.delete('schedules') ? [500, {}] : [200, schedules[String(params.id)] ?? []],
            },
            post: {
                '/api/environments/:team_id/query/:query_kind/': queryMetrics,
            },
            patch: {
                '/api/projects/:team_id/hog_flows/:id/': async ({ request, params }) => {
                    const flow = flows.find(({ id }) => id === params.id)!
                    Object.assign(flow, await request.json())
                    return [200, flow]
                },
            },
        })
        initKeaTests()
        logic = broadcastsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadBroadcastsSuccess'])
    })

    afterEach(() => {
        if (logic.isMounted()) {
            logic.unmount()
        }
        lemonToast.dismiss()
        jest.useRealTimers()
        jest.restoreAllMocks()
        resumeKeaLoadersErrors()
    })

    it('keeps the filters when a link back to the list carries no query params', () => {
        router.actions.push('/broadcasts?status=sent&search=welcome')
        expect(logic.values.filters.status).toEqual('sent')

        router.actions.push('/broadcasts')

        expect(logic.values.filters.status).toEqual('sent')
        expect(logic.values.filters.search).toEqual('welcome')
        expect(router.values.searchParams).toMatchObject({ status: 'sent', search: 'welcome' })
    })

    it('defaults the tags filter when the saved filters have none', () => {
        logic.actions.setFilters({ search: 'welcome' })
        const key = Object.keys(localStorage).find((k) => k.includes('broadcasts_list_filters'))!
        const { tags: _, ...savedBeforeTags } = JSON.parse(localStorage.getItem(key)!)
        localStorage.setItem(key, JSON.stringify(savedBeforeTags))
        logic.unmount()
        router.actions.push('/broadcasts')

        logic = broadcastsLogic()
        logic.mount()

        expect(logic.values.filters).toMatchObject({ search: 'welcome', tags: [] })
    })

    it.each([
        {
            filters: { search: '', status: 'all', createdBy: null, tags: [], page: 1 },
            shown: { first: 'welcome 0', last: 'welcome 29', count: 74 },
        },
        {
            filters: { search: 'welcome', status: 'partially_failed', createdBy: 'user-1', tags: ['vip'], page: 3 },
            shown: { first: 'welcome 60', last: 'welcome 69', count: 70 },
        },
    ])('shows the page the filters $filters.status describe', async ({ filters, shown }) => {
        const matching = { created_by: 'user-1', broadcast_status: 'partially_sent' }
        flows = [
            ...drafts(70, 'welcome', matching),
            ...drafts(1, 'other', matching),
            ...drafts(1, 'welcome by someone else', { ...matching, created_by: 'user-2' }),
            ...drafts(1, 'welcome sent', { ...matching, broadcast_status: 'sent' }),
            ...drafts(1, 'welcome untagged', { ...matching, tags: [] }),
            ...drafts(1, 'welcome workflow', { ...matching, type: 'workflow' }),
        ]

        logic.actions.setFiltersFromUrl(filters as any)
        await expectLogic(logic).toDispatchActions(['loadBroadcastsSuccess'])

        const { results, count } = logic.values.broadcasts
        expect({ first: results[0].name, last: results.at(-1)!.name, count }).toEqual(shown)
        expect(logic.values.filtersPending).toBe(false)
    })

    it('waits for a pause in filter edits, then shows their first page and writes them to the URL', async () => {
        flows = [...drafts(31, 'other'), { ...DRAFT, name: 'Welcome' }, { ...DRAFT, id: 'well', name: 'Well done' }]
        router.actions.push('/broadcasts?page=2')
        await expectLogic(logic).toDispatchActions(['loadBroadcastsSuccess'])
        const names = (): (string | null)[] => logic.values.broadcasts.results.map(({ name }) => name)
        const page2 = ['other 30', 'Welcome', 'Well done']
        expect(names()).toEqual(page2)

        jest.useFakeTimers()
        logic.actions.setFilters({ search: 'Wel' })
        await jest.advanceTimersByTimeAsync(200)
        logic.actions.setFilters({ search: 'Welcome' })
        await jest.advanceTimersByTimeAsync(299)
        expect(names()).toEqual(page2)
        expect(logic.values).toMatchObject({ filtersPending: true, filters: { search: 'Welcome', page: 1 } })

        await jest.advanceTimersByTimeAsync(1)
        jest.useRealTimers()
        await waitFor(() => expect(names()).toEqual(['Welcome']))
        expect(router.values.searchParams).toEqual({ search: 'Welcome' })
        expect(logic.values.filtersPending).toBe(false)
    })

    it('lands on the last real page when the requested one is past the end', async () => {
        flows = drafts(31, 'welcome')

        router.actions.push('/broadcasts?page=5')
        await expectLogic(logic).toDispatchActions(['loadBroadcastsSuccess', 'loadBroadcastsSuccess'])

        expect(logic.values.filters.page).toBe(2)
        expect(logic.values.broadcasts.results.map(({ name }) => name)).toEqual(['welcome 30'])
    })

    it.each([
        { url: '?status=bogus&page=-4', filters: { status: 'all', page: 1 } },
        { url: '?page=abc&tags=vip', filters: { page: 1, tags: ['vip'] } },
        {
            url: `?tags=${encodeURIComponent('["a","b"]')}&created_by=u-1`,
            filters: { tags: ['a', 'b'], createdBy: 'u-1' },
        },
        { url: `?search=${'a'.repeat(250)}`, filters: { search: 'a'.repeat(200) } },
    ])('reads $url from the URL as $filters', ({ url, filters }) => {
        router.actions.push(`/broadcasts${url}`)

        expect(logic.values.filters).toEqual({
            search: '',
            status: 'all',
            createdBy: null,
            tags: [],
            page: 1,
            ...filters,
        })
    })

    it('shows each live row its latest run’s counts and status, and leaves drafts without a run', async () => {
        flows = [DRAFT, LIVE]
        runs = { [DRAFT.id]: [OLDER_RUN], [LIVE.id]: [RUN, OLDER_RUN] }
        schedules[LIVE.id] = [{ status: 'paused' }, { status: 'active' }]
        sends = { [RUN.id]: LIVE_DETAILS.totals, [OLDER_RUN.id]: { email_sent: 40 } }

        await reload()

        await waitFor(() =>
            expect(logic.values.rowDetailsById).toEqual({
                [DRAFT.id]: { latestBatchJob: null, totals: {}, hasPendingSchedule: undefined, batchJobStatuses: [] },
                [LIVE.id]: { ...LIVE_DETAILS, batchJobStatuses: ['completed', 'active'] },
            })
        )
    })

    it.each([
        { fails: 'runs' as const, expected: undefined },
        { fails: 'schedules' as const, expected: { ...LIVE_DETAILS, hasPendingSchedule: undefined } },
        { fails: 'metrics' as const, expected: { ...LIVE_DETAILS, totals: null } },
    ])('when the $fails request fails on a refresh, the row keeps what did load', async ({ fails, expected }) => {
        await loadLiveRow()
        failing.add(fails)

        await reload()

        await waitFor(() => expect(failing).not.toContain(fails))
        await settleRequestsAheadOfANewOne()
        await waitFor(() => expect(logic.values.rowDetailsById[LIVE.id]).toEqual(expected))
    })

    it('drops a live row’s lookup without an error when the list unmounts before its runs arrive', async () => {
        let releaseRuns!: () => void
        held.runs = new Promise<void>((resolve) => {
            releaseRuns = resolve
        })
        runs[LIVE.id] = [RUN]
        const rejections: unknown[] = []
        const onRejection = (error: unknown): void => {
            rejections.push(error)
        }
        process.on('unhandledRejection', onRejection)
        try {
            flows = [LIVE]
            await reload()

            logic.unmount()
            releaseRuns()
            await settleRequestsAheadOfANewOne()
        } finally {
            process.off('unhandledRejection', onRejection)
        }

        expect(rejections).toEqual([])
    })

    it('drops only the run statuses when the list reloads, keeping the tag and counts on screen', async () => {
        await loadLiveRow()
        let releaseList!: () => void
        held.list = new Promise<void>((resolve) => {
            releaseList = resolve
        })

        logic.actions.loadBroadcasts()

        const { batchJobStatuses: _, ...shownWhileLoading } = LIVE_DETAILS
        expect(logic.values.rowDetailsById[LIVE.id]).toEqual(shownWhileLoading)
        releaseList()
        await waitFor(() => expect(logic.values.rowDetailsById[LIVE.id]).toEqual(LIVE_DETAILS))
    })

    it('flags a failed load and clears the flag on the next attempt', async () => {
        silenceKeaLoadersErrors()
        failing.add('list')

        logic.actions.loadBroadcasts()
        await expectLogic(logic).toDispatchActions(['loadBroadcastsFailure'])

        expect(logic.values.loadFailed).toBe(true)
        render(createElement(jest.requireActual('react-toastify').ToastContainer))
        await screen.findByText("Couldn't load broadcasts. Refresh the page to try again.")
        logic.actions.loadBroadcasts()
        expect(logic.values.loadFailed).toBe(false)
        await expectLogic(logic).toDispatchActions(['loadBroadcastsSuccess'])
    })

    describe('saving a row’s tags', () => {
        let saveResponse: any

        beforeEach(async () => {
            saveResponse = undefined
            useMocks({
                post: {
                    '/api/projects/:team_id/hog_flows/bulk_update_tags/': async ({ request }) => {
                        const { ids, action, tags } = (await request.json()) as Record<string, any>
                        const sent: string[] = tags.map((tag: string) => tag.toLowerCase())
                        const apply: Record<string, (old: string[]) => string[]> = {
                            set: () => sent,
                            add: (old) => [...old, ...sent],
                            remove: (old) => old.filter((tag) => !sent.includes(tag)),
                        }
                        const hit = (flow: Flow): boolean => !saveResponse && ids.includes(flow.id)
                        flows = flows.map((flow) => (hit(flow) ? { ...flow, tags: apply[action](flow.tags) } : flow))
                        return [200, saveResponse ?? { updated: flows.filter(hit), skipped: [] }]
                    },
                },
            })
            // A draft's row lookup makes no request, so none outlives the test.
            flows = [DRAFT]
            await reload()
        })

        it.each([
            { tagFilter: [], shown: [{ tags: ['new'] }] },
            { tagFilter: ['vip'], shown: [] },
        ])(
            'shows the edit at once and stores the saved tags, reloading only under a tag filter ($tagFilter)',
            async ({ tagFilter, shown }) => {
                logic.actions.setFiltersFromUrl({ ...logic.values.filters, tags: tagFilter })
                await expectLogic(logic).toDispatchActions(['loadBroadcastsSuccess'])

                logic.actions.saveBroadcastTags(DRAFT.id, ['New'])
                expect(logic.values).toMatchObject({
                    savingTagsFor: DRAFT.id,
                    broadcasts: { results: [{ tags: ['New'] }] },
                })
                await expectLogic(logic).toDispatchActions(['broadcastTagsSaved']).toFinishAllListeners()

                await waitFor(() =>
                    expect(logic.values).toMatchObject({ savingTagsFor: null, broadcasts: { results: shown } })
                )
            }
        )

        it('reads the stored tags back with an error when the save is skipped', async () => {
            saveResponse = { updated: [], skipped: [{ id: DRAFT.id, reason: 'No edit access' }] }

            logic.actions.saveBroadcastTags(DRAFT.id, ['other'])
            await expectLogic(logic).toDispatchActions(['broadcastTagsSaved', 'loadBroadcastsSuccess'])

            render(createElement(jest.requireActual('react-toastify').ToastContainer))
            await screen.findByText("Couldn't save tags: No edit access")
            expect(logic.values).toMatchObject({ savingTagsFor: null, broadcasts: { results: [{ tags: ['vip'] }] } })
        })
    })

    it('restores an archived broadcast as a draft and reloads the list', async () => {
        const archived = { id: 'archived-1', name: 'Old', status: 'archived', tags: [] }
        flows = [archived]

        logic.actions.restoreBroadcast(archived)
        await expectLogic(logic).toDispatchActions(['loadBroadcastsSuccess'])

        expect(logic.values.broadcasts.results).toMatchObject([{ id: 'archived-1', status: 'draft' }])
    })
})
