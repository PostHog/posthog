import { MOCK_DEFAULT_ORGANIZATION, MOCK_TEAM_ID } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'

import { signalsScoutConfigList, signalsScoutConfigUpdate } from 'products/signals/frontend/generated/api'
import type { SignalScoutConfigApi } from 'products/signals/frontend/generated/api.schemas'
import { RunSourceEnumApi, TaskExecutionModeEnumApi } from 'products/tasks/frontend/generated/api.schemas'

import { SignalScoutRunSummary } from '../types'
import { SCOUT_AUTHOR_PROMPT } from '../utils/scoutRunsWindow'
import { scoutFleetLogic } from './scoutFleetLogic'

jest.mock('products/signals/frontend/generated/api', () => ({
    signalsScoutConfigDestroy: jest.fn(),
    signalsScoutConfigList: jest.fn(),
    signalsScoutConfigUpdate: jest.fn(),
    signalsScoutRunsFindingsSummary: jest.fn(),
}))

const mockSignalsScoutConfigList = signalsScoutConfigList as jest.MockedFunction<typeof signalsScoutConfigList>
const mockSignalsScoutConfigUpdate = signalsScoutConfigUpdate as jest.MockedFunction<typeof signalsScoutConfigUpdate>

const BASE_CONFIG: SignalScoutConfigApi = {
    id: 'config-1',
    skill_name: 'signals-scout-errors',
    description: 'Finds error trends.',
    scout_origin: 'canonical',
    enabled: true,
    status: 'active',
    pause_reason: null,
    emit: true,
    run_interval_minutes: 1440,
    run_cron_schedule: null,
    output_destinations: {},
    structured_output_schema: null,
    last_run_at: null,
    consecutive_failure_count: 0,
    status_changed_at: null,
    auto_pause_exempt: false,
    network_access: 'trusted',
    model: null,
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
        mockSignalsScoutConfigList.mockReset().mockResolvedValue([])
        mockSignalsScoutConfigUpdate.mockReset()
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

    // The roster is the only consumer of the tag filter, so assert through the buckets it renders.
    const rosterConfigIds = (): string[] =>
        logic.values.rosterBuckets.flatMap((bucket) => bucket.configs.map((config) => config.id))

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

    it('groups the roster by lifecycle, leading with the scouts that are producing', () => {
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
            },
        ])
        // `busy` filed a report in the window, which is what separates Working from Watching.
        logic.actions.loadScoutRunsSuccess([makeRun({ skill_name: 'signals-scout-busy', emitted_report_ids: ['r-1'] })])

        expect(logic.values.rosterBuckets.map((bucket) => bucket.key)).toEqual([
            'working',
            'needs_you',
            'watching',
            'off',
        ])
        expect(logic.values.rosterGroupCounts).toMatchObject({ working: 1, needs_you: 1, watching: 1, off: 1 })
    })

    it('leaves a row where it is when its switch is flipped, instead of relocating it mid-click', async () => {
        logic.actions.loadScoutConfigsSuccess([
            { ...BASE_CONFIG, id: 'quiet', skill_name: 'signals-scout-quiet' },
            { ...BASE_CONFIG, id: 'other', skill_name: 'signals-scout-other' },
        ])
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.rosterBuckets.map((bucket) => bucket.key)).toEqual(['watching'])

        // The optimistic half of a toggle: the switch reads off immediately...
        logic.actions.patchScoutConfigLocally('quiet', { enabled: false })

        // ...but the row stays in the group it was rendered in, rather than jumping to Off.
        expect(logic.values.rosterBuckets.map((bucket) => bucket.key)).toEqual(['watching'])
        expect(rosterConfigIds()).toEqual(['other', 'quiet'])
        expect(logic.values.scoutConfigs?.find((config) => config.id === 'quiet')?.enabled).toBe(false)
    })

    it('re-places rows once server data lands', async () => {
        logic.actions.loadScoutConfigsSuccess([{ ...BASE_CONFIG, id: 'quiet', skill_name: 'signals-scout-quiet' }])
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.loadScoutConfigsSuccess([
            {
                ...BASE_CONFIG,
                id: 'quiet',
                skill_name: 'signals-scout-quiet',
                enabled: false,
                status: 'paused_by_user',
            },
        ])
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.rosterBuckets.map((bucket) => bucket.key)).toEqual(['off'])
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

    it('runs the task it creates, rather than leaving the user on an unstarted one', async () => {
        const repositories = jest.spyOn(api.tasks, 'repositories')
        const create = jest.spyOn(api.tasks, 'create').mockResolvedValue({ id: 'task-1' } as any)
        const run = jest.spyOn(api.tasks, 'run').mockResolvedValue({ id: 'task-1' } as any)

        logic.actions.startScoutChatTask(SCOUT_AUTHOR_PROMPT, 'scout authoring task', 'Suggest a scout')
        await expectLogic(logic).toFinishAllListeners()

        expect(run).toHaveBeenCalledWith('task-1', {
            run_source: RunSourceEnumApi.Manual,
            mode: TaskExecutionModeEnumApi.Interactive,
            // Without the prompt as the first turn, an interactive run boots the agent idle.
            pending_user_message: SCOUT_AUTHOR_PROMPT,
        })
        expect(router.values.location.pathname).toContain('task-1')
        // Pinning a repo would make the run clone it in full, and these prompts never touch code.
        expect(repositories).not.toHaveBeenCalled()
        expect(create).toHaveBeenCalledWith(expect.not.objectContaining({ repository: expect.anything() }))
    })

    it('starts nothing when the organization has not approved AI data processing', async () => {
        organizationLogic.actions.loadCurrentOrganizationSuccess({
            ...MOCK_DEFAULT_ORGANIZATION,
            is_ai_data_processing_approved: false,
        })
        const create = jest.spyOn(api.tasks, 'create').mockResolvedValue({ id: 'task-3' } as any)
        const run = jest.spyOn(api.tasks, 'run').mockResolvedValue({ id: 'task-3' } as any)

        logic.actions.startScoutChatTask(SCOUT_AUTHOR_PROMPT, 'scout authoring task', 'Suggest a scout')
        await expectLogic(logic).toDispatchActions(['startScoutChatTaskFailure'])

        // The tasks run endpoint has no consent check of its own, so dropping the guard here would
        // start an agent sandbox for an organization that declined AI data processing.
        expect(create).not.toHaveBeenCalled()
        expect(run).not.toHaveBeenCalled()
    })

    it('still opens the task when kicking off its run fails', async () => {
        jest.spyOn(api.tasks, 'create').mockResolvedValue({ id: 'task-2' } as any)
        jest.spyOn(api.tasks, 'run').mockRejectedValue(new Error('over the usage limit'))

        logic.actions.startScoutChatTask(SCOUT_AUTHOR_PROMPT, 'scout authoring task', 'Suggest a scout')
        await expectLogic(logic).toDispatchActions(['startScoutChatTaskSuccess'])

        expect(router.values.location.pathname).toContain('task-2')
    })
})
