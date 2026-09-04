import { MOCK_DEFAULT_TEAM, MOCK_DEFAULT_USER, MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api-error'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type {
    MCPServiceAccountApi,
    MCPServiceAccountServerApi,
} from 'products/mcp_store/frontend/generated/api.schemas'
import { signalsScoutCreate } from 'products/signals/frontend/generated/api'
import type { SignalScoutCreateResponseApi } from 'products/signals/frontend/generated/api.schemas'

import { SCOUT_DAILY_AT_SCHEDULE_MODE, SCOUT_WEEKLY_ON_SCHEDULE_MODE } from '../utils/scoutRunsWindow'
import { ScoutCreateModalLogicProps, scoutCreateModalLogic, scoutCreateModalLogicKey } from './scoutCreateModalLogic'

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
        owners: [],
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

function teamServer(id: string, name: string): MCPServiceAccountServerApi {
    return {
        id,
        shared_by: {
            id: MOCK_DEFAULT_USER.id,
            uuid: MOCK_DEFAULT_USER.uuid,
            email: MOCK_DEFAULT_USER.email,
            hedgehog_config: null,
        },
        scope: 'team',
        name,
        description: `${name} workspace`,
        url: `https://mcp.${name.toLowerCase()}.example.com/mcp`,
        icon_key: name.toLowerCase(),
        icon_domain: `${name.toLowerCase()}.com`,
        connection_state: 'ready',
        reachable: true,
    }
}

function scoutAccountResponse(servers: MCPServiceAccountServerApi[]): [number, Record<string, unknown>] {
    const account: MCPServiceAccountApi = {
        id: 'scout-id',
        name: 'scout',
        description: 'scout agent',
        handle: 'svc-scout',
        agent_key: 'scout',
        status: 'active',
        server_ids: servers.map(({ id }) => id),
        servers,
        last_active_at: null,
        created_at: '2026-07-22T00:00:00Z',
        updated_at: '2026-07-22T00:00:00Z',
    }
    return [200, { count: 1, next: null, previous: null, results: [account] }]
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
        // The draft is persisted to localStorage; clear it so one test's draft can't leak into another.
        localStorage.clear()
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
            weeklyDay: '1',
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

    it('selects every team MCP server by default, unless the opener passed its own selection', async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/mcp_gateway/service_accounts/': () =>
                    scoutAccountResponse([teamServer('github-id', 'GitHub'), teamServer('linear-id', 'Linear')]),
            },
        })

        logic = scoutCreateModalLogic({ logicKey: 'default-servers', onClose })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.scoutCreateForm.config.mcp_gateway_server_ids).toEqual(['github-id', 'linear-id'])
        // The default selection must not mark the untouched form as changed, or the modal would block
        // the first overlay-close click and warn of unsaved input that does not exist.
        expect(logic.values.scoutCreateFormChanged).toBe(false)

        // A caller that chose specific servers keeps that choice.
        const prefilled = scoutCreateModalLogic({
            logicKey: 'prefilled-servers',
            initialValues: { config: { mcp_gateway_server_ids: ['linear-id'] } },
            onClose,
        })
        prefilled.mount()
        await expectLogic(prefilled).toFinishAllListeners()
        expect(prefilled.values.scoutCreateForm.config.mcp_gateway_server_ids).toEqual(['linear-id'])
        prefilled.unmount()
    })

    it('clears the servers-defaulted marker on create so the next open re-applies the default', async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/mcp_gateway/service_accounts/': () =>
                    scoutAccountResponse([teamServer('github-id', 'GitHub'), teamServer('linear-id', 'Linear')]),
            },
        })
        mockSignalsScoutCreate.mockResolvedValue(CREATED_SCOUT)

        const logicKey = scoutCreateModalLogicKey(undefined)
        logic = scoutCreateModalLogic({ logicKey, onClose, onCreated })
        logic.mount()
        // The team's servers load, so the default is applied and the marker is set.
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.mcpServersDefaulted).toBe(true)
        expect(logic.values.scoutCreateForm.config.mcp_gateway_server_ids).toEqual(['github-id', 'linear-id'])

        logic.actions.setScoutCreateFormValue('name', 'checkout-failures')
        logic.actions.setScoutCreateFormValue('description', 'Investigates recurring checkout failures.')
        logic.actions.setScoutCreateFormValue(
            'body',
            'Inspect checkout failure signals and report meaningful regressions.'
        )
        await expectLogic(logic, () => logic.actions.submitScoutCreateForm()).toFinishAllListeners()
        // A successful create discards the draft, so the marker resets to its initial value.
        expect(logic.values.mcpServersDefaulted).toBe(false)
        logic.unmount()

        // The next blank open re-applies the all-servers default instead of opening with every server off.
        const reopened = scoutCreateModalLogic({ logicKey, onClose })
        reopened.mount()
        await expectLogic(reopened).toFinishAllListeners()
        expect(reopened.values.mcpServersDefaulted).toBe(true)
        expect(reopened.values.scoutCreateForm.config.mcp_gateway_server_ids).toEqual(['github-id', 'linear-id'])
        reopened.unmount()
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

    it('submits a weekly day and run time as a cron schedule', async () => {
        mockSignalsScoutCreate.mockResolvedValue(CREATED_SCOUT)
        logic = scoutCreateModalLogic({
            logicKey: 'weekly-scout',
            initialValues: {
                name: 'signals-scout-checkout-failures',
                description: 'Investigates recurring checkout failures.',
                body: 'Inspect checkout failure signals and report meaningful regressions.',
            },
            onClose,
            onCreated,
        })
        logic.mount()

        logic.actions.setScoutCreateScheduleMode(SCOUT_WEEKLY_ON_SCHEDULE_MODE)
        logic.actions.setScoutCreateWeeklyDay('4')
        logic.actions.setScoutCreateDailyTime('14:45')

        await expectLogic(logic).toMatchValues({
            scoutCreateForm: expect.objectContaining({
                weeklyDay: '4',
                dailyTime: '14:45',
                config: expect.objectContaining({ run_cron_schedule: '45 14 * * 4' }),
            }),
        })
        await expectLogic(logic, () => logic.actions.submitScoutCreateForm()).toFinishAllListeners()

        expect(mockSignalsScoutCreate).toHaveBeenCalledWith(
            String(MOCK_TEAM_ID),
            expect.objectContaining({
                config: expect.objectContaining({ run_cron_schedule: '45 14 * * 4' }),
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

    it('restores a persisted draft when reopened under the same key', async () => {
        logic = scoutCreateModalLogic({ logicKey: scoutCreateModalLogicKey(undefined), onClose })
        logic.mount()
        logic.actions.setScoutCreateFormValue('body', 'Watch checkout latency and report spikes.')
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.scoutCreateFormChanged).toBe(true)
        logic.unmount()

        // A fresh instance under the same key is what a remount after navigating away looks like.
        const reopened = scoutCreateModalLogic({ logicKey: scoutCreateModalLogicKey(undefined), onClose })
        reopened.mount()
        expect(reopened.values.scoutCreateForm.body).toBe('Watch checkout latency and report spikes.')
        // The changed flag must restore with the draft, or the modal's unsaved-input guard would be
        // off and one backdrop click would silently discard the restored draft.
        expect(reopened.values.scoutCreateFormChanged).toBe(true)
        reopened.unmount()
    })

    it('picks a run day for a draft persisted before the weekly mode existed', async () => {
        const logicKey = scoutCreateModalLogicKey(undefined)
        const first = scoutCreateModalLogic({ logicKey, onClose })
        first.mount()
        first.actions.setScoutCreateFormValue('body', 'Watch checkout latency and report spikes.')
        await expectLogic(first).toFinishAllListeners()
        first.unmount()

        // kea-localstorage restores the stored object over the whole reducer default instead of
        // merging in fields added since, so a draft written before the weekly mode shipped comes
        // back with no run day at all. Strip the key to reproduce that draft.
        for (const key of Object.keys(localStorage)) {
            const stored = localStorage.getItem(key)
            if (stored?.includes('"weeklyDay"')) {
                const draft = JSON.parse(stored)
                delete draft.weeklyDay
                localStorage.setItem(key, JSON.stringify(draft))
            }
        }

        logic = scoutCreateModalLogic({ logicKey, onClose })
        logic.mount()
        logic.actions.setScoutCreateScheduleMode(SCOUT_WEEKLY_ON_SCHEDULE_MODE)

        await expectLogic(logic).toMatchValues({
            scoutCreateForm: expect.objectContaining({
                weeklyDay: '1',
                config: expect.objectContaining({ run_cron_schedule: '0 9 * * 1' }),
            }),
        })
    })

    it('does not restore a persisted draft after switching to another project', async () => {
        const logicKey = scoutCreateModalLogicKey(undefined)
        const first = scoutCreateModalLogic({ logicKey, onClose })
        first.mount()
        first.actions.setScoutCreateFormValue('body', 'Watch checkout latency and report spikes.')
        await expectLogic(first).toFinishAllListeners()
        first.unmount()

        // Switching project reloads the app under a different team. localStorage is not cleared here,
        // unlike in beforeEach, so the first project's draft is still stored. The draft is scoped to
        // the project it was written in, so it must not restore under another project.
        initKeaTests(true, { ...MOCK_DEFAULT_TEAM, id: MOCK_TEAM_ID + 1 })
        logic = scoutCreateModalLogic({ logicKey, onClose })
        logic.mount()
        expect(logic.values.scoutCreateForm.body).toBe('')
    })

    it.each([
        [undefined, 'new'],
        [{}, 'new'],
        [{ name: 'signals-scout-ai-observability-daily-digest' }, 'signals-scout-ai-observability-daily-digest'],
    ])('keys the draft per opening context: %p', (initialValues, expectedKey) => {
        expect(scoutCreateModalLogicKey(initialValues)).toBe(expectedKey)
    })

    it('keys a name-less template draft apart from the blank create form', () => {
        // A deep-link template can prefill a description and body but carry no valid name. Keying on
        // name alone would put it in the blank form's 'new' slot, so a restored draft from one context
        // would clobber the other. Each context must get its own key.
        const blankKey = scoutCreateModalLogicKey({})
        const templateKey = scoutCreateModalLogicKey({
            description: 'Investigates recurring checkout failures.',
            body: 'Inspect checkout failure signals and report meaningful regressions.',
        })
        const otherTemplateKey = scoutCreateModalLogicKey({
            description: 'Watches signup latency.',
            body: 'Report signup latency spikes.',
        })

        expect(templateKey).not.toBe(blankKey)
        expect(templateKey).not.toBe(otherTemplateKey)
        // The same payload keys the same slot, so a template keeps its own draft across a remount.
        expect(
            scoutCreateModalLogicKey({
                description: 'Investigates recurring checkout failures.',
                body: 'Inspect checkout failure signals and report meaningful regressions.',
            })
        ).toBe(templateKey)
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
