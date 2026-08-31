import { MOCK_DEFAULT_ORGANIZATION, MOCK_TEAM_ID } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { ApiError } from 'lib/api-error'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import {
    signalsScoutChatTasksCreate,
    signalsScoutConfigList,
    signalsScoutConfigUpdate,
    signalsScoutRunsRecentPerScout,
} from 'products/signals/frontend/generated/api'
import type { SignalScoutConfigApi } from 'products/signals/frontend/generated/api.schemas'

import { SignalScoutRunSummary } from '../types'
import { scoutFleetLogic } from './scoutFleetLogic'

jest.mock('posthog-js')
jest.mock('products/signals/frontend/generated/api', () => ({
    signalsScoutChatTasksCreate: jest.fn(),
    signalsScoutConfigDestroy: jest.fn(),
    signalsScoutConfigList: jest.fn(),
    signalsScoutConfigUpdate: jest.fn(),
    signalsScoutRunsFindingsSummary: jest.fn(),
    signalsScoutRunsList: jest.fn(),
    signalsScoutRunsRecentPerScout: jest.fn(),
}))

const mockSignalsScoutChatTasksCreate = signalsScoutChatTasksCreate as jest.MockedFunction<
    typeof signalsScoutChatTasksCreate
>
const mockSignalsScoutConfigList = signalsScoutConfigList as jest.MockedFunction<typeof signalsScoutConfigList>
const mockSignalsScoutConfigUpdate = signalsScoutConfigUpdate as jest.MockedFunction<typeof signalsScoutConfigUpdate>
const mockSignalsScoutRunsRecentPerScout = signalsScoutRunsRecentPerScout as jest.MockedFunction<
    typeof signalsScoutRunsRecentPerScout
>

const BASE_CONFIG: SignalScoutConfigApi = {
    id: 'config-1',
    skill_name: 'signals-scout-errors',
    description: 'Finds error trends.',
    scout_origin: 'canonical',
    owners: [],
    enabled: true,
    status: 'active',
    pause_reason: null,
    emit: true,
    run_interval_minutes: 1440,
    run_cron_schedule: null,
    output_destinations: {},
    structured_output_schema: null,
    mcp_gateway_server_ids: [],
    last_run_at: null,
    consecutive_failure_count: 0,
    status_changed_at: null,
    auto_pause_exempt: false,
    network_access: 'trusted',
    model: null,
    source_product: null,
    source_id: null,
    created_at: '2026-07-22T00:00:00Z',
}

function makeRun(overrides: Partial<SignalScoutRunSummary> = {}): SignalScoutRunSummary {
    return {
        run_id: 'run-1',
        skill_name: BASE_CONFIG.skill_name,
        skill_version: 1,
        status: 'completed',
        metadata: {},
        created_at: '2026-07-22T01:00:00Z',
        started_at: '2026-07-22T01:00:00Z',
        completed_at: '2026-07-22T01:02:00Z',
        summary: '',
        emitted_count: 0,
        emitted_finding_ids: [],
        emitted_report_ids: [],
        edited_report_ids: [],
        ...overrides,
    }
}

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void; reject: (error: Error) => void } {
    let resolvePromise!: (value: T) => void
    let rejectPromise!: (error: Error) => void
    const promise = new Promise<T>((resolve, reject) => {
        resolvePromise = resolve
        rejectPromise = reject
    })
    return { promise, resolve: resolvePromise, reject: rejectPromise }
}

describe('scoutFleetLogic', () => {
    let logic: ReturnType<typeof scoutFleetLogic.build>

    beforeEach(async () => {
        initKeaTests()
        mockSignalsScoutChatTasksCreate.mockReset()
        mockSignalsScoutConfigList.mockReset().mockResolvedValue([])
        mockSignalsScoutConfigUpdate.mockReset()
        mockSignalsScoutRunsRecentPerScout.mockReset().mockResolvedValue([])
        logic = scoutFleetLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.loadScoutConfigsSuccess([BASE_CONFIG])
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('queues updates for a scout while its previous update is in flight', async () => {
        const firstRequest = deferred<SignalScoutConfigApi>()
        const queuedUpdates = {
            run_interval_minutes: 60,
            output_destinations: {
                slack: { integration_id: 42, channel: 'CSCOUTS|#scout-findings' },
            },
        }
        const finalConfig: SignalScoutConfigApi = {
            ...BASE_CONFIG,
            enabled: false,
            ...queuedUpdates,
        }
        mockSignalsScoutConfigUpdate.mockReturnValueOnce(firstRequest.promise).mockResolvedValueOnce(finalConfig)

        logic.actions.updateScoutConfig(BASE_CONFIG.id, { enabled: false })
        logic.actions.updateScoutConfig(BASE_CONFIG.id, { run_interval_minutes: 60 })
        logic.actions.updateScoutConfig(BASE_CONFIG.id, { output_destinations: queuedUpdates.output_destinations })

        expect(mockSignalsScoutConfigUpdate).toHaveBeenCalledTimes(1)
        expect(logic.values.scoutConfigs?.[0]).toMatchObject({ enabled: false, ...queuedUpdates })

        firstRequest.resolve({ ...BASE_CONFIG, enabled: false })
        await expectLogic(logic).toFinishAllListeners()

        expect(mockSignalsScoutConfigUpdate).toHaveBeenNthCalledWith(1, String(MOCK_TEAM_ID), BASE_CONFIG.id, {
            enabled: false,
        })
        expect(mockSignalsScoutConfigUpdate).toHaveBeenNthCalledWith(
            2,
            String(MOCK_TEAM_ID),
            BASE_CONFIG.id,
            queuedUpdates
        )
        expect(logic.values.scoutConfigs?.[0]).toEqual(finalConfig)
        expect(logic.values.updatingScoutIds).toEqual([])
    })

    // The roster is the only consumer of the tag filter, so assert through the rows it renders.
    const rosterConfigIds = (): string[] => logic.values.rosterScouts.map((row) => row.config.id)

    it('filters scouts by any selected tag and stops applying tags that are no longer in use', () => {
        const revenueScout = { ...BASE_CONFIG, tags: ['revenue'] }
        const onCallScout = {
            ...BASE_CONFIG,
            id: 'config-2',
            skill_name: 'signals-scout-on-call',
            tags: ['on-call'],
        }
        const untaggedScout = {
            ...BASE_CONFIG,
            id: 'config-3',
            skill_name: 'signals-scout-product',
            tags: [],
        }
        logic.actions.loadScoutConfigsSuccess([revenueScout, onCallScout, untaggedScout])

        logic.actions.setScoutTagFilter(['revenue', 'on-call'])

        expect(logic.values.activeScoutTags).toEqual(['revenue', 'on-call'])
        expect(rosterConfigIds()).toEqual(['config-1', 'config-2'])

        logic.actions.patchScoutConfigLocally(revenueScout.id, { tags: [] })
        logic.actions.patchScoutConfigLocally(onCallScout.id, { tags: [] })

        expect(logic.values.selectedScoutTags).toEqual(['revenue', 'on-call'])
        expect(logic.values.activeScoutTags).toEqual([])
        expect(rosterConfigIds()).toHaveLength(3)
    })

    it('lists the whole roster A→Z and tags each row with its lifecycle group', () => {
        logic.actions.setRosterEvaluatedAt(new Date('2026-08-28T12:00:00Z').valueOf())
        logic.actions.loadScoutConfigsSuccess([
            { ...BASE_CONFIG, id: 'quiet', skill_name: 'signals-scout-quiet' },
            { ...BASE_CONFIG, id: 'busy', skill_name: 'signals-scout-busy' },
            {
                ...BASE_CONFIG,
                id: 'off',
                skill_name: 'signals-scout-off',
                enabled: false,
                status: 'paused_by_user',
            },
            {
                ...BASE_CONFIG,
                id: 'broken',
                skill_name: 'signals-scout-broken',
                enabled: false,
                status: 'paused_by_system',
                pause_reason: 'repeated_failures',
                status_changed_at: '2026-08-27T12:00:00Z',
            },
            {
                ...BASE_CONFIG,
                id: 'stale-pause',
                skill_name: 'signals-scout-stale-pause',
                enabled: false,
                status: 'paused_by_system',
                pause_reason: 'no_output',
                status_changed_at: '2026-08-20T12:00:00Z',
            },
            {
                ...BASE_CONFIG,
                id: 'warned',
                skill_name: 'signals-scout-warned',
                status: 'pending_pause',
                pause_reason: 'ignored',
            },
            {
                ...BASE_CONFIG,
                id: 'quiet-warning',
                skill_name: 'signals-scout-quiet-warning',
                status: 'pending_pause',
                pause_reason: 'no_output',
            },
        ])
        // `busy` filed a report in the window, which is what separates Working from Watching.
        logic.actions.loadScoutRunsSuccess([makeRun({ skill_name: 'signals-scout-busy', emitted_report_ids: ['r-1'] })])

        // One flat list ordered by name, not split across lifecycle sections.
        expect(logic.values.rosterScouts.map((row) => [row.config.id, row.group])).toEqual([
            ['broken', 'needs_you'],
            ['busy', 'working'],
            ['off', 'off'],
            ['quiet', 'watching'],
            ['quiet-warning', 'needs_you'],
            ['stale-pause', 'needs_you'],
            ['warned', 'needs_you'],
        ])
        // The stats tell a warning apart from a recent pause; human and stale pauses are neither.
        expect(logic.values.pauseAttentionCounts).toEqual({ pausingSoon: 1, recentlyPaused: 1 })
    })

    it('keeps configs unresolved until the current team is available', async () => {
        logic.unmount()
        teamLogic.actions.loadCurrentTeamSuccess(null)
        mockSignalsScoutConfigList.mockClear()
        logic = scoutFleetLogic()
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()

        expect(mockSignalsScoutConfigList).not.toHaveBeenCalled()
        expect(logic.values.scoutConfigs).toBeNull()
    })

    // The roster mounts from short-lived components, so an unmount mid-request is routine. The
    // loader reconciles against `values.scoutConfigs`, and that read throws once the reducer branch
    // leaves the store — a silent error report from a page the user has already left.
    it('reports nothing when the roster unmounts while its config request is in flight', async () => {
        const request = deferred<SignalScoutConfigApi[]>()
        mockSignalsScoutConfigList.mockReturnValueOnce(request.promise)

        logic.actions.loadScoutConfigs()
        logic.unmount()
        request.resolve([BASE_CONFIG])
        // Drain the microtasks the loader resumes on, so the assertion sees its full continuation.
        await new Promise(setImmediate)

        expect(posthog.captureException).not.toHaveBeenCalled()
    })

    // The 500 row is the point of this case: a guard wide enough to swallow it would leave a real
    // scout-configs outage looking identical to a project the user simply cannot reach.
    it.each([
        [403, 'loadScoutConfigsSuccess'],
        [404, 'loadScoutConfigsSuccess'],
        [500, 'loadScoutConfigsFailure'],
    ])('resolves a %s from the config list to %s', async (status, expectedAction) => {
        mockSignalsScoutConfigList.mockRejectedValueOnce(new ApiError('nope', status))

        logic.actions.loadScoutConfigs()

        await expectLogic(logic).toDispatchActions([expectedAction])
    })

    it('sends newer queued updates after an earlier request fails', async () => {
        const firstRequest = deferred<SignalScoutConfigApi>()
        const failingRequest = deferred<SignalScoutConfigApi>()
        const outputDestinations = {
            slack: { integration_id: 42, channel: 'CSCOUTS|#scout-findings' },
        }
        const finalConfig: SignalScoutConfigApi = {
            ...BASE_CONFIG,
            enabled: false,
            output_destinations: outputDestinations,
        }
        mockSignalsScoutConfigUpdate
            .mockReturnValueOnce(firstRequest.promise)
            .mockReturnValueOnce(failingRequest.promise)
            .mockResolvedValueOnce(finalConfig)

        logic.actions.updateScoutConfig(BASE_CONFIG.id, { enabled: false })
        logic.actions.updateScoutConfig(BASE_CONFIG.id, { run_interval_minutes: 60 })

        firstRequest.resolve({ ...BASE_CONFIG, enabled: false })
        await expectLogic(logic).toDispatchActions(['patchScoutConfigLocally'])
        expect(mockSignalsScoutConfigUpdate).toHaveBeenCalledTimes(2)

        logic.actions.updateScoutConfig(BASE_CONFIG.id, { output_destinations: outputDestinations })
        failingRequest.reject(new Error('request failed'))
        await expectLogic(logic).toFinishAllListeners()

        expect(mockSignalsScoutConfigUpdate).toHaveBeenNthCalledWith(2, String(MOCK_TEAM_ID), BASE_CONFIG.id, {
            run_interval_minutes: 60,
        })
        expect(mockSignalsScoutConfigUpdate).toHaveBeenNthCalledWith(3, String(MOCK_TEAM_ID), BASE_CONFIG.id, {
            output_destinations: outputDestinations,
        })
        expect(logic.values.scoutConfigs?.[0]).toEqual(finalConfig)
        expect(logic.values.updatingScoutIds).toEqual([])
    })

    it('starts the chat task server-side and navigates to it', async () => {
        mockSignalsScoutChatTasksCreate.mockResolvedValue({ task_id: 'task-1' })

        logic.actions.startScoutChatTask('author_scout', 'scout authoring task')
        await expectLogic(logic).toDispatchActions(['startScoutChatTaskSuccess'])

        expect(mockSignalsScoutChatTasksCreate).toHaveBeenCalledWith(String(MOCK_TEAM_ID), {
            chat_type: 'author_scout',
        })
        expect(router.values.location.pathname).toContain('task-1')
    })

    it('starts nothing when the organization has not approved AI data processing', async () => {
        organizationLogic.actions.loadCurrentOrganizationSuccess({
            ...MOCK_DEFAULT_ORGANIZATION,
            is_ai_data_processing_approved: false,
        })

        logic.actions.startScoutChatTask('author_scout', 'scout authoring task')
        await expectLogic(logic).toDispatchActions(['startScoutChatTaskFailure'])

        // The endpoint enforces no consent check of its own, so dropping the guard here would
        // start an agent sandbox for an organization that declined AI data processing.
        expect(mockSignalsScoutChatTasksCreate).not.toHaveBeenCalled()
    })

    it('reports roster filtering with the search length, not the term', async () => {
        jest.useFakeTimers()
        try {
            const capture = posthog.capture as jest.Mock
            capture.mockClear()
            logic.actions.loadScoutConfigsSuccess([
                BASE_CONFIG,
                { ...BASE_CONFIG, id: 'config-2', skill_name: 'signals-scout-revenue', enabled: false },
            ])

            logic.actions.setScoutEnabledFilter('disabled')
            logic.actions.setScoutSearch('rev')
            logic.actions.setScoutSearch('reve')
            await jest.advanceTimersByTimeAsync(600)
            logic.actions.setScoutSearch('')
            await jest.advanceTimersByTimeAsync(600)

            const scoutActions = capture.mock.calls
                .filter(([event]) => event === 'Scout action')
                .map(([, properties]) => properties)
            expect(scoutActions).toEqual([
                expect.objectContaining({ action_type: 'filter_enabled', filter: 'disabled', filter_match_count: 1 }),
                expect.objectContaining({ action_type: 'search_scouts', search_length: 4, filter_match_count: 1 }),
            ])
            expect(JSON.stringify(scoutActions)).not.toContain('reve')
        } finally {
            jest.useRealTimers()
        }
    })

    it('drops the delayed search write when the user navigates before the debounce settles', async () => {
        jest.useFakeTimers()
        try {
            router.actions.push(urls.inbox('scouts'))
            logic.actions.setScoutSearch('rev')
            // Open a scout's detail before the debounce elapses; the roster logic stays mounted beside it.
            router.actions.push(urls.inboxScout('signals-scout-revenue'))
            await jest.advanceTimersByTimeAsync(600)

            // The stale roster filter must not land on the detail route it does not own.
            expect(router.values.location.pathname).toContain('signals-scout-revenue')
            expect(router.values.searchParams.scoutSearch).toBeUndefined()
        } finally {
            jest.useRealTimers()
        }
    })

    it('writes non-default roster filters to the URL and keeps the bare view clean', async () => {
        jest.useFakeTimers()
        try {
            // The URL only carries tags the fleet still uses, so the roster needs a scout wearing one.
            logic.actions.loadScoutConfigsSuccess([{ ...BASE_CONFIG, tags: ['revenue'] }])
            logic.actions.setScoutEnabledFilter('disabled')
            logic.actions.setScoutTagFilter(['revenue'])
            logic.actions.setScoutSearch('rev')
            // The search param is written on a debounce, so let its pause elapse.
            await jest.advanceTimersByTimeAsync(600)

            expect(router.values.searchParams).toMatchObject({
                scoutEnabled: 'disabled',
                scoutTags: 'revenue',
                scoutSearch: 'rev',
            })

            logic.actions.setScoutEnabledFilter('all')
            logic.actions.setScoutTagFilter([])
            logic.actions.setScoutSearch('')
            await jest.advanceTimersByTimeAsync(600)

            expect(router.values.searchParams.scoutEnabled).toBeUndefined()
            expect(router.values.searchParams.scoutTags).toBeUndefined()
            expect(router.values.searchParams.scoutSearch).toBeUndefined()
        } finally {
            jest.useRealTimers()
        }
    })

    it('restores roster filters from a shared URL', async () => {
        router.actions.push(urls.inbox('scouts'), {
            scoutEnabled: 'enabled',
            scoutTags: 'revenue,on-call',
            scoutSearch: 'rev',
        })
        await expectLogic(logic).toDispatchActions(['hydrateRosterFilters'])

        expect(logic.values.scoutEnabledFilter).toEqual('enabled')
        expect(logic.values.selectedScoutTags).toEqual(['revenue', 'on-call'])
        expect(logic.values.scoutSearch).toEqual('rev')
    })

    it('resets the roster filters when Back or Forward reaches a bare URL', async () => {
        // A filtered roster, reached by a shared link or by toggling the controls.
        router.actions.push(urls.inbox('scouts'), { scoutEnabled: 'enabled', scoutTags: 'revenue' })
        await expectLogic(logic).toDispatchActions(['hydrateRosterFilters'])
        expect(logic.values.scoutEnabledFilter).toEqual('enabled')
        expect(logic.values.selectedScoutTags).toEqual(['revenue'])

        // Back or Forward onto the bare entry arrives as a POP carrying no roster params.
        await expectLogic(logic, () => {
            router.actions.locationChanged({
                method: 'POP',
                pathname: urls.inbox('scouts'),
                search: '',
                searchParams: {},
                hash: '',
                hashParams: {},
                url: urls.inbox('scouts'),
            })
        }).toDispatchActions(['hydrateRosterFilters'])

        expect(logic.values.scoutEnabledFilter).toEqual('all')
        expect(logic.values.selectedScoutTags).toEqual([])
        expect(logic.values.scoutSearch).toEqual('')
        // The bare entry is left as-is, so a second Back still reaches the entries beneath it.
        expect(router.values.searchParams.scoutEnabled).toBeUndefined()
        expect(router.values.searchParams.scoutTags).toBeUndefined()
    })

    it('reflects a persisted filter back into a bare roster URL on fresh navigation', async () => {
        // The user filtered the roster, then opened the bare roster URL afresh (a PUSH, not Back).
        router.actions.push(urls.inbox('scouts'), { scoutEnabled: 'enabled' })
        await expectLogic(logic).toDispatchActions(['hydrateRosterFilters'])
        expect(logic.values.scoutEnabledFilter).toEqual('enabled')

        router.actions.push(urls.inbox('scouts'))
        await expectLogic(logic).toFinishAllListeners()

        // The filter persists and is written back so the restored view stays shareable.
        expect(logic.values.scoutEnabledFilter).toEqual('enabled')
        expect(router.values.searchParams.scoutEnabled).toEqual('enabled')
    })

    it('drops a typed search that a URL hydration has already replaced', async () => {
        jest.useFakeTimers()
        try {
            const capture = posthog.capture as jest.Mock
            router.actions.push(urls.inbox('scouts'))
            logic.actions.setScoutSearch('reve')
            capture.mockClear()

            // A shared link or Back reaches the same route with a different search before the
            // debounce settles. Hydration does not abort the breakpoint, so the stale query must
            // not report itself or write itself back over the hydrated URL.
            router.actions.push(urls.inbox('scouts'), { scoutSearch: 'rev' })
            await jest.advanceTimersByTimeAsync(600)

            expect(capture.mock.calls.filter(([event]) => event === 'Scout action')).toEqual([])
            expect(router.values.searchParams.scoutSearch).toEqual('rev')
        } finally {
            jest.useRealTimers()
        }
    })

    it('keeps the roster filters out of a bare URL that a sibling logic replaces', async () => {
        router.actions.push(urls.inbox('scouts'), { scoutEnabled: 'enabled' })
        await expectLogic(logic).toDispatchActions(['hydrateRosterFilters'])

        // A sibling inbox logic restores its own params by replacing the bare URL, which happens
        // while a Back onto that bare entry is still being handled.
        await expectLogic(logic, () => {
            router.actions.locationChanged({
                method: 'REPLACE',
                pathname: urls.inbox('scouts'),
                search: '?scope=all',
                searchParams: { scope: 'all' },
                hash: '',
                hashParams: {},
                url: `${urls.inbox('scouts')}?scope=all`,
            })
        }).toFinishAllListeners()

        // Riding along here would leave the URL filtered once the Back resets the controls.
        expect(router.values.searchParams.scoutEnabled).toBeUndefined()
    })

    it('restores a search that the router parsed as a number', async () => {
        // Opening the link parses the query string, and kea-router turns `scoutSearch=123` into the
        // number 123, which a string-only read drops.
        router.actions.push(`${urls.inbox('scouts')}?scoutSearch=123`)
        await expectLogic(logic).toDispatchActions(['hydrateRosterFilters'])

        expect(logic.values.scoutSearch).toEqual('123')
    })

    it('drops a tag from the URL once no scout uses it', async () => {
        jest.useFakeTimers()
        try {
            const revenueScout = { ...BASE_CONFIG, tags: ['revenue'] }
            logic.actions.loadScoutConfigsSuccess([revenueScout])
            logic.actions.setScoutTagFilter(['revenue'])
            expect(router.values.searchParams.scoutTags).toEqual('revenue')

            // Retagging the last scout empties the tag control, so the roster is visibly unfiltered.
            // A URL that still carries the tag would re-filter on refresh if the tag came back.
            logic.actions.patchScoutConfigLocally(revenueScout.id, { tags: [] })
            logic.actions.setScoutSearch('rev')
            await jest.advanceTimersByTimeAsync(600)

            expect(logic.values.activeScoutTags).toEqual([])
            expect(router.values.searchParams.scoutTags).toBeUndefined()
        } finally {
            jest.useRealTimers()
        }
    })

    it('resets the in-flight chat type when the kickoff fails', async () => {
        mockSignalsScoutChatTasksCreate.mockRejectedValue(new Error('over the usage limit'))

        logic.actions.startScoutChatTask('author_scout', 'scout authoring task')
        await expectLogic(logic).toDispatchActions(['startScoutChatTaskFailure'])

        expect(logic.values.runningChatType).toBeNull()
    })

    // The 60s roster poll returns freshly parsed objects every cycle. Without per-item
    // reconciliation, every poll replaces every reference and the memoized roster re-renders on
    // an idle page. With it, an unchanged response must preserve identity end-to-end.
    describe('poll identity stability', () => {
        // Mirror what a real poll gets from the API: every response is a fresh JSON parse,
        // so identical content still arrives as all-new object references.
        const freshConfigs = (...configs: SignalScoutConfigApi[]): SignalScoutConfigApi[] =>
            configs.map((config) => JSON.parse(JSON.stringify(config)))

        it('keeps the configs array and every config reference when a poll changes nothing', async () => {
            mockSignalsScoutConfigList.mockImplementation(async () => freshConfigs(BASE_CONFIG))

            logic.actions.loadScoutConfigs()
            await expectLogic(logic).toDispatchActions(['loadScoutConfigs', 'loadScoutConfigsSuccess'])
            const first = logic.values.scoutConfigs

            logic.actions.loadScoutConfigs()
            await expectLogic(logic).toDispatchActions(['loadScoutConfigs', 'loadScoutConfigsSuccess'])
            const second = logic.values.scoutConfigs

            expect(second).toBe(first)
            expect(second?.[0]).toBe(first?.[0])
        })

        it('keeps unchanged config references when a poll changes one config', async () => {
            const otherConfig = { ...BASE_CONFIG, id: 'config-2', skill_name: 'signals-scout-revenue' }
            mockSignalsScoutConfigList.mockImplementation(async () => freshConfigs(BASE_CONFIG, otherConfig))

            logic.actions.loadScoutConfigs()
            await expectLogic(logic).toDispatchActions(['loadScoutConfigs', 'loadScoutConfigsSuccess'])
            const first = logic.values.scoutConfigs

            mockSignalsScoutConfigList.mockImplementation(async () =>
                freshConfigs({ ...BASE_CONFIG, enabled: false }, otherConfig)
            )
            logic.actions.loadScoutConfigs()
            await expectLogic(logic).toDispatchActions(['loadScoutConfigs', 'loadScoutConfigsSuccess'])
            const second = logic.values.scoutConfigs

            expect(second).not.toBe(first)
            expect(second?.[0].enabled).toBe(false)
            expect(second?.[1]).toBe(first?.[1])
        })

        it('advances time-sensitive roster states when an unchanged runs poll crosses a boundary', async () => {
            jest.useFakeTimers()
            try {
                jest.setSystemTime(Date.UTC(2026, 7, 4))
                const settledRun = makeRun({ run_id: 'run-settled', status: 'completed' })
                mockSignalsScoutRunsRecentPerScout.mockImplementation(async () => [
                    JSON.parse(JSON.stringify(settledRun)),
                ])
                logic.unmount()
                logic = scoutFleetLogic()
                logic.mount()
                await expectLogic(logic).toFinishAllListeners()
                logic.actions.loadScoutConfigsSuccess([
                    BASE_CONFIG,
                    {
                        ...BASE_CONFIG,
                        id: 'paused',
                        skill_name: 'signals-scout-paused',
                        enabled: false,
                        status: 'paused_by_system',
                        pause_reason: 'repeated_failures',
                        status_changed_at: '2026-07-29T00:00:00Z',
                    },
                ])
                logic.actions.loadScoutRuns()
                await expectLogic(logic).toDispatchActions(['loadScoutRuns', 'loadScoutRunsSuccess'])
                const firstRuns = logic.values.scoutRuns

                expect(logic.values.rosterScouts[0].group).toBe('settling_in')
                expect(logic.values.pauseAttentionCounts.recentlyPaused).toBe(1)

                jest.setSystemTime(Date.UTC(2026, 7, 6))
                logic.actions.loadScoutRuns()
                await expectLogic(logic).toDispatchActions(['loadScoutRuns', 'loadScoutRunsSuccess'])

                expect(logic.values.scoutRuns).toBe(firstRuns)
                expect(logic.values.rosterScouts[0].group).toBe('watching')
                expect(logic.values.pauseAttentionCounts.recentlyPaused).toBe(0)
            } finally {
                jest.useRealTimers()
            }
        })

        it('keeps the runs array and settled run references when a poll changes nothing', async () => {
            const settledRun = makeRun({ run_id: 'run-settled', status: 'completed' })
            mockSignalsScoutRunsRecentPerScout.mockImplementation(async () => [JSON.parse(JSON.stringify(settledRun))])

            logic.actions.loadScoutRuns()
            await expectLogic(logic).toDispatchActions(['loadScoutRuns', 'loadScoutRunsSuccess'])
            const first = logic.values.scoutRuns
            const firstRoster = logic.values.rosterScouts

            logic.actions.loadScoutRuns()
            await expectLogic(logic).toDispatchActions(['loadScoutRuns', 'loadScoutRunsSuccess'])
            const second = logic.values.scoutRuns

            expect(second).toBe(first)
            expect(second[0]).toBe(first[0])
            expect(logic.values.rosterScouts).toBe(firstRoster)
        })

        it('keeps settled run references but not live ones when a poll reruns with a live run', async () => {
            const settledRun = makeRun({ run_id: 'run-settled', status: 'completed' })
            const liveRun = makeRun({ run_id: 'run-live', status: 'in_progress' })
            mockSignalsScoutRunsRecentPerScout.mockImplementation(async () =>
                [settledRun, liveRun].map((run) => JSON.parse(JSON.stringify(run)))
            )

            logic.actions.loadScoutRuns()
            await expectLogic(logic).toDispatchActions(['loadScoutRuns', 'loadScoutRunsSuccess'])
            const first = logic.values.scoutRuns

            logic.actions.loadScoutRuns()
            await expectLogic(logic).toDispatchActions(['loadScoutRuns', 'loadScoutRunsSuccess'])
            const second = logic.values.scoutRuns

            // A live run must refresh identity — its rows render wall-clock durations that have
            // to advance with each poll. Settled neighbours stay reference-stable.
            expect(second).not.toBe(first)
            expect(second.find((run) => run.run_id === 'run-settled')).toBe(
                first.find((run) => run.run_id === 'run-settled')
            )
            expect(second.find((run) => run.run_id === 'run-live')).not.toBe(
                first.find((run) => run.run_id === 'run-live')
            )
        })
    })
})
