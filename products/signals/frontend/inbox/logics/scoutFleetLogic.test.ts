import { MOCK_DEFAULT_ORGANIZATION, MOCK_TEAM_ID } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'

import {
    signalsScoutChatTasksCreate,
    signalsScoutConfigList,
    signalsScoutConfigUpdate,
    signalsScoutMetadataGet,
} from 'products/signals/frontend/generated/api'
import type { SignalScoutConfigApi } from 'products/signals/frontend/generated/api.schemas'

import { scoutFleetLogic } from './scoutFleetLogic'

jest.mock('products/signals/frontend/generated/api', () => ({
    signalsScoutChatTasksCreate: jest.fn(),
    signalsScoutConfigDestroy: jest.fn(),
    signalsScoutConfigList: jest.fn(),
    signalsScoutConfigUpdate: jest.fn(),
    signalsScoutMetadataGet: jest.fn(),
    signalsScoutRunsFindingsSummary: jest.fn(),
}))

const mockSignalsScoutChatTasksCreate = signalsScoutChatTasksCreate as jest.MockedFunction<
    typeof signalsScoutChatTasksCreate
>
const mockSignalsScoutConfigList = signalsScoutConfigList as jest.MockedFunction<typeof signalsScoutConfigList>
const mockSignalsScoutConfigUpdate = signalsScoutConfigUpdate as jest.MockedFunction<typeof signalsScoutConfigUpdate>
const mockSignalsScoutMetadataGet = signalsScoutMetadataGet as jest.MockedFunction<typeof signalsScoutMetadataGet>

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
    mcp_gateway_server_ids: [],
    last_run_at: null,
    consecutive_failure_count: 0,
    status_changed_at: null,
    auto_pause_exempt: false,
    network_access: 'trusted',
    model: null,
    created_at: '2026-07-22T00:00:00Z',
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
        mockSignalsScoutMetadataGet.mockReset().mockResolvedValue({
            enrolled: true,
            banner_message: null,
            limits: {
                max_runs_per_tick: 1,
                max_runs_per_day: null,
                runs_today: 0,
                runs_remaining_today: null,
            },
        })

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
        expect(logic.values.visibleConfigs.map((config) => config.id)).toEqual(['config-1', 'config-2'])

        logic.actions.patchScoutConfigLocally(revenueScout.id, { tags: [] })
        logic.actions.patchScoutConfigLocally(onCallScout.id, { tags: [] })

        expect(logic.values.selectedScoutTags).toEqual(['revenue', 'on-call'])
        expect(logic.values.activeScoutTags).toEqual([])
        expect(logic.values.visibleConfigs).toHaveLength(3)
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

    it('resets the in-flight chat type when the kickoff fails', async () => {
        mockSignalsScoutChatTasksCreate.mockRejectedValue(new Error('over the usage limit'))

        logic.actions.startScoutChatTask('author_scout', 'scout authoring task')
        await expectLogic(logic).toDispatchActions(['startScoutChatTaskFailure'])

        expect(logic.values.runningChatType).toBeNull()
    })
})
