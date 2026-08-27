import { MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api-error'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { signalsScoutCreate } from 'products/signals/frontend/generated/api'
import type { SignalScoutCreateResponseApi } from 'products/signals/frontend/generated/api.schemas'

import { SCOUT_DAILY_AT_SCHEDULE_MODE } from '../utils/scoutRunsWindow'
import { ScoutCreateModalLogicProps, scoutCreateModalLogic } from './scoutCreateModalLogic'

jest.mock('products/signals/frontend/generated/api', () => ({
    signalsScoutCreate: jest.fn(),
}))

const mockSignalsScoutCreate = signalsScoutCreate as jest.MockedFunction<typeof signalsScoutCreate>

const CREATED_SCOUT: SignalScoutCreateResponseApi = {
    created: true,
    skill: {
        id: 'skill-1',
        name: 'signals-scout-checkout-failures',
        description: 'Investigates recurring checkout failures.',
        version: 1,
        allowed_tools: ['edit_report', 'emit_report'],
    },
    config: {
        id: 'config-1',
        skill_name: 'signals-scout-checkout-failures',
        description: 'Investigates recurring checkout failures.',
        scout_origin: 'custom',
        enabled: false,
        status: 'paused_by_user',
        pause_reason: null,
        emit: false,
        run_interval_minutes: 60,
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
        created_at: '2026-07-24T00:00:00Z',
    },
}

const setRedesignFlag = (enabled: boolean): void => {
    featureFlagLogic.mount()
    featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.INBOX_REDESIGN], {
        [FEATURE_FLAGS.INBOX_REDESIGN]: enabled,
    })
}

describe('scoutCreateModalLogic', () => {
    let logic: ReturnType<typeof scoutCreateModalLogic.build>
    let onClose: jest.MockedFunction<() => void>
    let onCreated: jest.MockedFunction<NonNullable<ScoutCreateModalLogicProps['onCreated']>>

    beforeEach(() => {
        initKeaTests()
        // The prefix-in-the-field form is part of the inbox redesign; the legacy contract is pinned below.
        setRedesignFlag(true)
        mockSignalsScoutCreate.mockReset()
        onClose = jest.fn()
        onCreated = jest.fn()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('merges trigger defaults and submits them to the atomic create endpoint', async () => {
        mockSignalsScoutCreate.mockResolvedValue(CREATED_SCOUT)
        logic = scoutCreateModalLogic({
            logicKey: 'prefilled-scout',
            initialValues: {
                name: 'signals-scout-checkout-failures',
                description: 'Investigates recurring checkout failures.',
                body: 'Inspect checkout failure signals and report meaningful regressions.',
                config: {
                    enabled: false,
                    emit: false,
                    run_interval_minutes: 60,
                    output_destinations: {
                        slack: {
                            integration_id: 42,
                            channel: 'C123|#ai-observability',
                        },
                    },
                    tags: ['on-call', 'revenue'],
                },
            },
            onClose,
            onCreated,
        })
        logic.mount()

        expect(logic.values.scoutCreateForm).toEqual({
            name: 'checkout-failures',
            description: 'Investigates recurring checkout failures.',
            body: 'Inspect checkout failure signals and report meaningful regressions.',
            dailyTime: '09:00',
            config: {
                enabled: false,
                emit: false,
                run_interval_minutes: 60,
                run_cron_schedule: null,
                mcp_gateway_server_ids: [],
                output_destinations: {
                    slack: {
                        integration_id: 42,
                        channel: 'C123|#ai-observability',
                    },
                },
                tags: ['on-call', 'revenue'],
            },
        })

        await expectLogic(logic, () => logic.actions.submitScoutCreateForm()).toFinishAllListeners()

        expect(mockSignalsScoutCreate).toHaveBeenCalledWith(String(MOCK_TEAM_ID), {
            name: 'signals-scout-checkout-failures',
            description: 'Investigates recurring checkout failures.',
            body: 'Inspect checkout failure signals and report meaningful regressions.',
            config: {
                enabled: false,
                emit: false,
                run_interval_minutes: 60,
                run_cron_schedule: null,
                mcp_gateway_server_ids: [],
                output_destinations: {
                    slack: {
                        integration_id: 42,
                        channel: 'C123|#ai-observability',
                    },
                },
                tags: ['on-call', 'revenue'],
            },
        })
        expect(onCreated).toHaveBeenCalledWith(CREATED_SCOUT)
        expect(onClose).toHaveBeenCalledTimes(1)
    })

    it('submits a daily run time as a project-timezone cron schedule', async () => {
        mockSignalsScoutCreate.mockResolvedValue(CREATED_SCOUT)
        logic = scoutCreateModalLogic({
            logicKey: 'daily-scout',
            initialValues: {
                name: 'signals-scout-checkout-failures',
                description: 'Investigates recurring checkout failures.',
                body: 'Inspect checkout failure signals and report meaningful regressions.',
            },
            onClose,
            onCreated,
        })
        logic.mount()

        logic.actions.setScoutCreateScheduleMode(SCOUT_DAILY_AT_SCHEDULE_MODE)
        logic.actions.setScoutCreateDailyTime('14:45')

        await expectLogic(logic).toMatchValues({
            scoutCreateForm: expect.objectContaining({
                dailyTime: '14:45',
                config: {
                    enabled: true,
                    emit: true,
                    run_interval_minutes: 1440,
                    run_cron_schedule: '45 14 * * *',
                    tags: [],
                    mcp_gateway_server_ids: [],
                },
            }),
        })
        await expectLogic(logic, () => logic.actions.submitScoutCreateForm()).toFinishAllListeners()

        expect(mockSignalsScoutCreate).toHaveBeenCalledWith(
            String(MOCK_TEAM_ID),
            expect.objectContaining({
                config: {
                    enabled: true,
                    emit: true,
                    run_interval_minutes: 1440,
                    run_cron_schedule: '45 14 * * *',
                    tags: [],
                    mcp_gateway_server_ids: [],
                },
            })
        )
    })

    it('does not submit a daily schedule without a run time', async () => {
        mockSignalsScoutCreate.mockResolvedValue(CREATED_SCOUT)
        logic = scoutCreateModalLogic({
            logicKey: 'daily-scout-without-time',
            initialValues: {
                name: 'signals-scout-checkout-failures',
                description: 'Investigates recurring checkout failures.',
                body: 'Inspect checkout failure signals and report meaningful regressions.',
            },
            onClose,
            onCreated,
        })
        logic.mount()

        logic.actions.setScoutCreateScheduleMode(SCOUT_DAILY_AT_SCHEDULE_MODE)
        logic.actions.setScoutCreateDailyTime('')

        await expectLogic(logic).toMatchValues({
            scoutCreateForm: expect.objectContaining({ dailyTime: '' }),
            scoutCreateFormValidationErrors: expect.objectContaining({ dailyTime: 'Run time is required' }),
        })
        await expectLogic(logic, () => logic.actions.submitScoutCreateForm()).toFinishAllListeners()

        expect(mockSignalsScoutCreate).not.toHaveBeenCalled()
        expect(onCreated).not.toHaveBeenCalled()
        expect(onClose).not.toHaveBeenCalled()
    })

    it('keeps the form open and surfaces a conflicting scout name', async () => {
        const initialValues = {
            name: 'signals-scout-checkout-failures',
            description: 'Investigates recurring checkout failures.',
            body: 'Inspect checkout failure signals and report meaningful regressions.',
        }
        mockSignalsScoutCreate.mockRejectedValue(
            new ApiError('Conflict', 409, undefined, {
                detail: 'A scout with this name already exists with different instructions.',
                attr: 'name',
            })
        )
        logic = scoutCreateModalLogic({
            logicKey: 'conflicting-scout',
            initialValues,
            onClose,
            onCreated,
        })
        logic.mount()

        await expectLogic(logic, () => logic.actions.submitScoutCreateForm()).toFinishAllListeners()

        expect(logic.values.scoutCreateFormManualErrors).toEqual({
            name: 'A scout with this name already exists with different instructions.',
        })
        expect(logic.values.scoutCreateForm).toMatchObject({ ...initialValues, name: 'checkout-failures' })
        expect(onCreated).not.toHaveBeenCalled()
        expect(onClose).not.toHaveBeenCalled()
    })

    it.each([
        ['', 'Name is required'],
        ['checkout failures', 'Name cannot contain spaces. Use hyphens between words.'],
        ['Checkout', 'Lowercase letters, numbers, and hyphens only'],
        ['checkout-failures', undefined],
        ['signals-scout-checkout-failures', undefined],
    ])('validates the typed name %p', async (name, expectedError) => {
        logic = scoutCreateModalLogic({ logicKey: `name-${name}`, onClose, onCreated })
        logic.mount()

        logic.actions.setScoutCreateFormValue('name', name)

        await expectLogic(logic).toMatchValues({
            scoutCreateFormValidationErrors: expect.objectContaining({ name: expectedError }),
        })
    })

    it('adds the prefix once, whether or not it was typed', async () => {
        mockSignalsScoutCreate.mockResolvedValue(CREATED_SCOUT)
        logic = scoutCreateModalLogic({
            logicKey: 'pasted-prefix',
            initialValues: {
                description: 'Investigates recurring checkout failures.',
                body: 'Inspect checkout failure signals and report meaningful regressions.',
            },
            onClose,
            onCreated,
        })
        logic.mount()

        logic.actions.setScoutCreateFormValue('name', ' signals-scout-checkout-failures ')
        await expectLogic(logic, () => logic.actions.submitScoutCreateForm()).toFinishAllListeners()

        expect(mockSignalsScoutCreate).toHaveBeenCalledWith(
            String(MOCK_TEAM_ID),
            expect.objectContaining({ name: 'signals-scout-checkout-failures' })
        )
    })

    // With the redesign flag off the field holds the whole skill name, so the prefix must be typed.
    describe('with the redesign flag off', () => {
        beforeEach(() => setRedesignFlag(false))

        it.each([
            ['checkout-failures', 'Name must start with signals-scout-'],
            ['signals-scout-checkout-failures', undefined],
        ])('validates the full name %p', async (name, expectedError) => {
            logic = scoutCreateModalLogic({ logicKey: `legacy-name-${name}`, onClose, onCreated })
            logic.mount()

            expect(logic.values.scoutCreateForm.name).toBe('signals-scout-')
            logic.actions.setScoutCreateFormValue('name', name)

            await expectLogic(logic).toMatchValues({
                scoutCreateFormValidationErrors: expect.objectContaining({ name: expectedError }),
            })
        })

        it('keeps a prefilled full name and submits it unchanged', async () => {
            mockSignalsScoutCreate.mockResolvedValue(CREATED_SCOUT)
            logic = scoutCreateModalLogic({
                logicKey: 'legacy-prefilled',
                initialValues: {
                    name: 'signals-scout-checkout-failures',
                    description: 'Investigates recurring checkout failures.',
                    body: 'Inspect checkout failure signals and report meaningful regressions.',
                },
                onClose,
                onCreated,
            })
            logic.mount()

            expect(logic.values.scoutCreateForm.name).toBe('signals-scout-checkout-failures')
            await expectLogic(logic, () => logic.actions.submitScoutCreateForm()).toFinishAllListeners()

            expect(mockSignalsScoutCreate).toHaveBeenCalledWith(
                String(MOCK_TEAM_ID),
                expect.objectContaining({ name: 'signals-scout-checkout-failures' })
            )
        })
    })
})
