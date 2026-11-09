import { waitFor } from '@testing-library/react'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { HogFlowBatchJobApi } from 'products/workflows/frontend/generated/api.schemas'

import { broadcastsLogic } from './broadcastsLogic'

const DRAFT = { id: 'draft-1', name: 'Draft', status: 'draft', tags: ['vip'] }
const LIVE = { id: 'live-1', name: 'Live', status: 'active', tags: ['vip'] }
const RUN = { id: 'job-2', status: 'completed', created_at: '2026-01-01T00:00:00Z' } as HogFlowBatchJobApi

describe('broadcastsLogic', () => {
    let logic: ReturnType<typeof broadcastsLogic.build>
    let listed: Record<string, string>[]
    let page: { results: any[]; count: number }
    let batchJobs: () => any
    let schedules: () => any
    let metrics: jest.SpyInstance
    let toastError: jest.SpyInstance

    const listResolver = ({ request }: { request: Request }): [number, any] => {
        listed.push(Object.fromEntries(new URL(request.url).searchParams))
        return [200, page]
    }

    const reload = async (): Promise<void> => {
        logic.actions.loadBroadcasts()
        await expectLogic(logic).toDispatchActions(['loadBroadcastsSuccess'])
    }

    beforeEach(async () => {
        localStorage.clear()
        listed = []
        page = { results: [], count: 0 }
        batchJobs = () => [200, []]
        schedules = () => [200, []]
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/': listResolver,
                '/api/projects/:team_id/hog_flows/': listResolver,
                '/api/projects/:team_id/hog_flows/:id/batch_jobs/': () => batchJobs(),
                '/api/projects/:team_id/hog_flows/:id/schedules/': () => schedules(),
            },
        })
        initKeaTests()
        metrics = jest.spyOn(api, 'queryHogQL').mockResolvedValue({
            results: [
                [120, 'email_sent'],
                [3, 'failed'],
            ],
        } as any)
        toastError = jest.spyOn(lemonToast, 'error').mockReturnValue('' as any)
        logic = broadcastsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadBroadcastsSuccess'])
    })

    afterEach(() => {
        logic.unmount()
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
            query: { type: 'broadcast', limit: '30', offset: '0' },
        },
        {
            filters: { search: 'welcome', status: 'partially_failed', createdBy: 'user-1', tags: ['vip'], page: 3 },
            query: {
                type: 'broadcast',
                search: 'welcome',
                broadcast_status: 'partially_sent',
                created_by: 'user-1',
                tags: '["vip"]',
                limit: '30',
                offset: '60',
            },
        },
    ])('asks the API for the page the filters $filters.status describe', async ({ filters, query }) => {
        page = { results: [], count: 100 }

        logic.actions.setFiltersFromUrl(filters as any)
        await expectLogic(logic).toDispatchActions(['loadBroadcastsSuccess'])

        expect(listed.at(-1)).toEqual(query)
        expect(logic.values).toMatchObject({ filtersPending: false, loadedFilters: filters })
    })

    it('debounces filter edits into one load, back on the first page, and writes them to the URL', async () => {
        page = { results: [], count: 100 }
        logic.actions.setFilters({ page: 3 })
        await expectLogic(logic).toDispatchActions(['loadBroadcastsSuccess'])
        expect(router.values.searchParams).toMatchObject({ page: 3 })
        const loadsBefore = listed.length

        logic.actions.setFilters({ search: 'wel' })
        logic.actions.setFilters({ search: 'welcome', status: 'all' })
        expect(logic.values).toMatchObject({ filtersPending: true, filters: { search: 'welcome', page: 1 } })
        await expectLogic(logic).toDispatchActions(['loadBroadcastsSuccess'])

        expect(listed.slice(loadsBefore)).toEqual([expect.objectContaining({ search: 'welcome', offset: '0' })])
        expect(router.values.searchParams).toEqual({ search: 'welcome' })
        expect(logic.values.filtersPending).toBe(false)
    })

    it('lands on the last real page when the requested one is past the end', async () => {
        page = { results: [], count: 31 }

        router.actions.push('/broadcasts?page=5')
        await expectLogic(logic).toDispatchActions(['loadBroadcastsSuccess', 'loadBroadcastsSuccess'])

        expect(logic.values.filters.page).toBe(2)
        expect(listed.at(-1)).toMatchObject({ offset: '30' })
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

    it('loads each live row its runs, schedules and run metrics, and skips them for drafts', async () => {
        const runsAsked: string[] = []
        batchJobs = () => [200, [RUN, { id: 'job-1', status: 'active' }]]
        schedules = () => [200, [{ status: 'paused' }, { status: 'active' }]]
        useMocks({
            get: {
                '/api/projects/:team_id/hog_flows/:id/batch_jobs/': ({ params }) => {
                    runsAsked.push(String(params.id))
                    return batchJobs()
                },
            },
        })
        page = { results: [DRAFT, LIVE], count: 2 }

        await reload()

        await waitFor(() =>
            expect(logic.values.rowDetailsById).toEqual({
                [DRAFT.id]: { latestBatchJob: null, totals: {}, hasPendingSchedule: undefined, batchJobStatuses: [] },
                [LIVE.id]: {
                    latestBatchJob: RUN,
                    totals: { email_sent: 120, failed: 3 },
                    hasPendingSchedule: true,
                    batchJobStatuses: ['completed', 'active'],
                },
            })
        )
        expect(runsAsked).toEqual([LIVE.id])
        expect(metrics.mock.calls[0][0]).toContain(`app_source_id = 'job-2'`)
    })

    it.each([
        { fails: 'runs', expected: undefined },
        {
            fails: 'schedules',
            expected: {
                latestBatchJob: RUN,
                hasPendingSchedule: undefined,
                totals: { email_sent: 120, failed: 3 },
                batchJobStatuses: ['completed'],
            },
        },
        {
            fails: 'metrics',
            expected: { latestBatchJob: RUN, hasPendingSchedule: false, totals: null, batchJobStatuses: ['completed'] },
        },
    ])('when the $fails request fails, the row keeps what did load', async ({ fails, expected }) => {
        batchJobs = () => (fails === 'runs' ? [500, {}] : [200, [RUN]])
        schedules = () => (fails === 'schedules' ? [500, {}] : [200, []])
        if (fails === 'metrics') {
            metrics.mockRejectedValue(new Error('timeout'))
        }
        logic.actions.setRowDetails(LIVE.id, { latestBatchJob: null, totals: { email_sent: 1 } })
        page = { results: [LIVE], count: 1 }

        await reload()

        await waitFor(() => expect(logic.values.rowDetailsById[LIVE.id]).toEqual(expected))
    })

    it('drops only the run statuses when the list reloads, keeping the tag and counts on screen', () => {
        logic.actions.setRowDetails(LIVE.id, {
            latestBatchJob: RUN,
            totals: { email_sent: 7 },
            batchJobStatuses: ['active'],
        })

        logic.actions.loadBroadcasts()

        expect(logic.values.rowDetailsById[LIVE.id]).toEqual({ latestBatchJob: RUN, totals: { email_sent: 7 } })
    })

    it('flags a failed load and clears the flag on the next attempt', async () => {
        silenceKeaLoadersErrors()
        useMocks({ get: { '/api/projects/:team_id/hog_flows/': () => [500, { detail: 'boom' }] } })

        logic.actions.loadBroadcasts()
        await expectLogic(logic).toDispatchActions(['loadBroadcastsFailure'])

        expect(logic.values.loadFailed).toBe(true)
        expect(toastError).toHaveBeenCalledWith("Couldn't load broadcasts. Refresh the page to try again.")
        useMocks({ get: { '/api/projects/:team_id/hog_flows/': listResolver } })
        logic.actions.loadBroadcasts()
        expect(logic.values.loadFailed).toBe(false)
        await expectLogic(logic).toDispatchActions(['loadBroadcastsSuccess'])
    })

    describe('saving a row’s tags', () => {
        let saved: any[]
        let saveResponse: any

        beforeEach(async () => {
            saved = []
            useMocks({
                post: {
                    '/api/projects/:team_id/hog_flows/bulk_update_tags/': async ({ request }) => {
                        saved.push(await request.json())
                        return [200, saveResponse]
                    },
                },
            })
            // A draft's row lookup makes no request, so none outlives the test.
            page = { results: [DRAFT], count: 1 }
            await reload()
        })

        it.each([
            { tagFilter: [], reloads: 0 },
            { tagFilter: ['vip'], reloads: 1 },
        ])(
            'shows the edit at once and stores the saved tags, reloading only under a tag filter ($tagFilter)',
            async ({ tagFilter, reloads }) => {
                logic.actions.setFiltersFromUrl({ ...logic.values.filters, tags: tagFilter })
                await expectLogic(logic).toDispatchActions(['loadBroadcastsSuccess'])
                const loadsBefore = listed.length
                saveResponse = { updated: [{ id: DRAFT.id, tags: ['vip', 'new'] }], skipped: [] }
                page = { results: [{ ...DRAFT, tags: ['vip', 'new'] }], count: 1 }

                logic.actions.saveBroadcastTags(DRAFT.id, ['vip', 'New'])
                expect(logic.values).toMatchObject({
                    savingTagsFor: DRAFT.id,
                    broadcasts: { results: [{ tags: ['vip', 'New'] }] },
                })
                await expectLogic(logic).toDispatchActions(['broadcastTagsSaved']).toFinishAllListeners()

                expect(saved).toEqual([{ ids: [DRAFT.id], action: 'set', tags: ['vip', 'New'] }])
                expect(logic.values).toMatchObject({
                    savingTagsFor: null,
                    broadcasts: { results: [{ tags: ['vip', 'new'] }] },
                })
                expect(listed.length - loadsBefore).toBe(reloads)
            }
        )

        it('reads the stored tags back with an error when the save is skipped', async () => {
            saveResponse = { updated: [], skipped: [{ id: DRAFT.id, reason: 'No edit access' }] }

            logic.actions.saveBroadcastTags(DRAFT.id, ['other'])
            await expectLogic(logic).toDispatchActions(['broadcastTagsSaved', 'loadBroadcastsSuccess'])

            expect(toastError).toHaveBeenCalledWith("Couldn't save tags: No edit access")
            expect(logic.values).toMatchObject({ savingTagsFor: null, broadcasts: { results: [{ tags: ['vip'] }] } })
        })
    })

    it('restores an archived broadcast as a draft and reloads the list', async () => {
        const patched: any[] = []
        useMocks({
            patch: {
                '/api/projects/:team_id/hog_flows/:id/': async ({ request, params }) => {
                    patched.push({ id: params.id, body: await request.json() })
                    return [200, {}]
                },
            },
        })
        jest.spyOn(lemonToast, 'success').mockReturnValue('' as any)
        const loadsBefore = listed.length

        logic.actions.restoreBroadcast({ id: 'archived-1', name: 'Old' } as any)
        await expectLogic(logic).toDispatchActions(['loadBroadcastsSuccess'])

        expect(patched).toEqual([{ id: 'archived-1', body: { status: 'draft' } }])
        expect(listed.length - loadsBefore).toBe(1)
    })
})
