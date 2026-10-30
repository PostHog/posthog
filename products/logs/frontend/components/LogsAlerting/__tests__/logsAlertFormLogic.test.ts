import { MOCK_TEAM_ID } from '~/lib/api.mock'

import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import { initKeaTests } from '~/test/init'
import { AnyPropertyFilter, FilterLogicalOperator, UniversalFiltersGroup } from '~/types'

import {
    logsAlertsCreate,
    logsAlertsList,
    logsAlertsPartialUpdate,
    logsAlertsSimulateCreate,
} from 'products/logs/frontend/generated/api'
import {
    GroupingModeEnumApi,
    LogsAlertConfigurationApi,
    LogsAlertConfigurationStateEnumApi,
    LogsAlertGroupingApi,
    LogsAlertSimulateResponseApi,
} from 'products/logs/frontend/generated/api.schemas'

import { buildFormDefaults, LogsAlertFormType, logsAlertFormLogic } from '../logsAlertFormLogic'
import { LogsAlertGroupBy } from '../logsAlertGrouping'

jest.mock('products/logs/frontend/generated/api', () => ({
    logsAlertsCreate: jest.fn(),
    logsAlertsPartialUpdate: jest.fn(),
    logsAlertsList: jest.fn(),
    logsAlertsDestroy: jest.fn(),
    logsAlertsSimulateCreate: jest.fn(),
}))

jest.mock('posthog-js')

jest.mock('@posthog/lemon-ui', () => ({
    lemonToast: {
        success: jest.fn(),
        error: jest.fn(),
    },
}))

const mockLogsAlertsCreate = logsAlertsCreate as jest.MockedFunction<typeof logsAlertsCreate>
const mockLogsAlertsPartialUpdate = logsAlertsPartialUpdate as jest.MockedFunction<typeof logsAlertsPartialUpdate>
const mockLogsAlertsList = logsAlertsList as jest.MockedFunction<typeof logsAlertsList>
const mockLogsAlertsSimulateCreate = logsAlertsSimulateCreate as jest.MockedFunction<typeof logsAlertsSimulateCreate>

const MOCK_PROJECT_ID = String(MOCK_TEAM_ID)

const MOCK_ALERT: LogsAlertConfigurationApi = {
    id: 'alert-uuid-1',
    name: 'Test Alert',
    enabled: true,
    filters: { severityLevels: ['error'] },
    threshold_count: 50,
    threshold_operator: 'above',
    window_minutes: 5,
    evaluation_periods: 2,
    datapoints_to_alarm: 1,
    cooldown_minutes: 10,
    state: LogsAlertConfigurationStateEnumApi.NotFiring,
    check_interval_minutes: 5,
    next_check_at: null,
    last_notified_at: null,
    last_checked_at: null,
    consecutive_failures: 0,
    last_error_message: null,
    destination_types: [],
    platform_owned: false,
    state_timeline: [],
    first_enabled_at: null,
    created_at: '2024-01-01T00:00:00Z',
    created_by: {
        id: 1,
        uuid: 'user-uuid',
        distinct_id: 'user-distinct-id',
        first_name: 'Test',
        email: 'test@example.com',
        hedgehog_config: null,
    },
    updated_at: null,
}

const MOCK_CREATED_ALERT: LogsAlertConfigurationApi = {
    ...MOCK_ALERT,
    id: 'newly-created-uuid',
}

const VALID_FORM_VALUES: LogsAlertFormType = {
    name: 'My Alert',
    severityLevels: ['error'],
    serviceNames: [],
    filterGroup: { type: FilterLogicalOperator.And, values: [] },
    thresholdOperator: 'above',
    thresholdCount: 100,
    windowMinutes: 10,
    evaluationPeriods: 1,
    datapointsToAlarm: 1,
    cooldownMinutes: 0,
    scheduleRestriction: null,
    groupBy: 'none',
    maxInstances: 20,
}

function givenTeamAlerts(alerts: LogsAlertConfigurationApi[]): void {
    mockLogsAlertsList.mockResolvedValue({ count: alerts.length, next: null, previous: null, results: alerts })
}

const PLATFORM_ALERT: LogsAlertConfigurationApi = { ...MOCK_ALERT, platform_owned: true }

const GROUPED_BY_SERVICE_ALERT: LogsAlertConfigurationApi = {
    ...MOCK_ALERT,
    grouping: { mode: 'by_result_labels', keys: ['service_name'], max_instances: 30 },
}

describe('logsAlertFormLogic', () => {
    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()

        // Prevent afterMount loadAlerts from throwing — must be set before mount() fires it
        ;(require('products/logs/frontend/generated/api').logsAlertsList as jest.Mock).mockResolvedValue({
            results: [],
            count: 0,
        })
    })

    describe('errors validation', () => {
        // kea-forms exposes alertFormValidationErrors which always returns
        // the raw computed errors, regardless of touched/submit state.
        // alertFormErrors only surfaces them after the form is submitted or touched.

        it('reports name error when name is empty', () => {
            const logic = logsAlertFormLogic({ alert: null })
            logic.mount()

            logic.actions.setAlertFormValues({ name: '', severityLevels: ['error'] })

            expect(logic.values.alertFormValidationErrors.name).toBe('Name is required')

            logic.unmount()
        })

        it('reports name error when name is only whitespace', () => {
            const logic = logsAlertFormLogic({ alert: null })
            logic.mount()

            logic.actions.setAlertFormValues({ name: '   ', severityLevels: ['error'] })

            expect(logic.values.alertFormValidationErrors.name).toBe('Name is required')

            logic.unmount()
        })

        it('clears name error when name has non-whitespace content', () => {
            const logic = logsAlertFormLogic({ alert: null })
            logic.mount()

            logic.actions.setAlertFormValues({ name: 'Valid name', severityLevels: ['error'] })

            expect(logic.values.alertFormValidationErrors.name).toBeUndefined()

            logic.unmount()
        })

        it('rejects invalid quiet hours before submitting', async () => {
            const logic = logsAlertFormLogic({ alert: null })
            logic.mount()

            logic.actions.setAlertFormValues({
                name: 'My Alert',
                severityLevels: ['error'],
                scheduleRestriction: { blocked_windows: [{ start: '10:00', end: '10:00' }] },
            })

            await expectLogic(logic, () => {
                logic.actions.submitAlertForm()
            }).toFinishAllListeners()

            expect(mockLogsAlertsCreate).not.toHaveBeenCalled()
            logic.unmount()
        })

        it('shows error toast on submit when no filter criteria are set', async () => {
            const logic = logsAlertFormLogic({ alert: null })
            logic.mount()

            logic.actions.setAlertFormValues({
                name: 'My Alert',
                severityLevels: [],
                serviceNames: [],
                filterGroup: { type: FilterLogicalOperator.And, values: [] },
            })

            await expectLogic(logic, () => {
                logic.actions.submitAlertForm()
            }).toFinishAllListeners()

            expect(lemonToast.error).toHaveBeenCalledWith('At least one filter is required')
            expect(mockLogsAlertsCreate).not.toHaveBeenCalled()

            logic.unmount()
        })

        it.each<[string, Partial<LogsAlertFormType>]>([
            [
                'severityLevels populated',
                {
                    severityLevels: ['error'],
                    serviceNames: [],
                    filterGroup: { type: FilterLogicalOperator.And, values: [] },
                },
            ],
            [
                'serviceNames populated',
                {
                    severityLevels: [],
                    serviceNames: ['my-service'],
                    filterGroup: { type: FilterLogicalOperator.And, values: [] },
                },
            ],
            [
                'filterGroup has values',
                {
                    severityLevels: [],
                    serviceNames: [],
                    filterGroup: {
                        type: FilterLogicalOperator.And,
                        values: [
                            {
                                key: 'env',
                                value: 'prod',
                                operator: 'exact',
                                type: 'event',
                            } as AnyPropertyFilter,
                        ],
                    },
                },
            ],
        ])('submits successfully when %s', async (_, filters) => {
            mockLogsAlertsCreate.mockResolvedValue(MOCK_CREATED_ALERT)
            const logic = logsAlertFormLogic({ alert: null })
            logic.mount()

            logic.actions.setAlertFormValues({ name: 'My Alert', ...filters })

            await expectLogic(logic, () => {
                logic.actions.submitAlertForm()
            }).toFinishAllListeners()

            expect(mockLogsAlertsCreate).toHaveBeenCalled()

            logic.unmount()
        })

        it('alertFormErrors surfaces name error after submit attempt with validation failures', async () => {
            const logic = logsAlertFormLogic({ alert: null })
            logic.mount()

            logic.actions.setAlertFormValues({
                name: '',
                severityLevels: ['error'],
                serviceNames: [],
                filterGroup: { type: FilterLogicalOperator.And, values: [] },
            })

            await expectLogic(logic, () => {
                logic.actions.submitAlertForm()
            }).toFinishAllListeners()

            expect(logic.values.alertFormErrors.name).toBe('Name is required')

            logic.unmount()
        })
    })

    describe('create path (props.alert is null)', () => {
        let logic: ReturnType<typeof logsAlertFormLogic.build>
        let onCreateSuccess: jest.Mock

        beforeEach(() => {
            mockLogsAlertsCreate.mockResolvedValue(MOCK_CREATED_ALERT)
            onCreateSuccess = jest.fn()
            logic = logsAlertFormLogic({ alert: null, onCreateSuccess })
            logic.mount()
        })

        afterEach(() => {
            logic?.unmount()
        })

        it('calls logsAlertsCreate with correct payload on submit', async () => {
            await expectLogic(logic, () => {
                logic.actions.setAlertFormValues(VALID_FORM_VALUES)
                logic.actions.submitAlertForm()
            }).toFinishAllListeners()

            expect(mockLogsAlertsCreate).toHaveBeenCalledTimes(1)
            expect(mockLogsAlertsCreate).toHaveBeenCalledWith(
                MOCK_PROJECT_ID,
                expect.objectContaining({
                    name: 'My Alert',
                    filters: { severityLevels: ['error'] },
                    threshold_count: 100,
                    threshold_operator: 'above',
                    window_minutes: 10,
                    evaluation_periods: 1,
                    datapoints_to_alarm: 1,
                    cooldown_minutes: 0,
                })
            )
        })

        it('does not call logsAlertsPartialUpdate on create path', async () => {
            await expectLogic(logic, () => {
                logic.actions.setAlertFormValues(VALID_FORM_VALUES)
                logic.actions.submitAlertForm()
            }).toFinishAllListeners()

            expect(mockLogsAlertsPartialUpdate).not.toHaveBeenCalled()
        })

        it('shows success toast after create', async () => {
            await expectLogic(logic, () => {
                logic.actions.setAlertFormValues(VALID_FORM_VALUES)
                logic.actions.submitAlertForm()
            }).toFinishAllListeners()

            expect(lemonToast.success).toHaveBeenCalledWith('Alert created')
            expect(onCreateSuccess).toHaveBeenCalledTimes(1)
        })

        it('trims whitespace from name in create payload', async () => {
            await expectLogic(logic, () => {
                logic.actions.setAlertFormValues({ ...VALID_FORM_VALUES, name: '  trimmed  ' })
                logic.actions.submitAlertForm()
            }).toFinishAllListeners()

            expect(mockLogsAlertsCreate).toHaveBeenCalledWith(
                MOCK_PROJECT_ID,
                expect.objectContaining({ name: 'trimmed' })
            )
        })

        it('builds filters with only serviceNames when only serviceNames are provided', async () => {
            await expectLogic(logic, () => {
                logic.actions.setAlertFormValues({
                    ...VALID_FORM_VALUES,
                    severityLevels: [],
                    serviceNames: ['svc-a', 'svc-b'],
                    filterGroup: { type: FilterLogicalOperator.And, values: [] },
                })
                logic.actions.submitAlertForm()
            }).toFinishAllListeners()

            expect(mockLogsAlertsCreate).toHaveBeenCalledWith(
                MOCK_PROJECT_ID,
                expect.objectContaining({
                    filters: { serviceNames: ['svc-a', 'svc-b'] },
                })
            )
        })

        it('wraps filterGroup values in outer And group in payload', async () => {
            const innerGroup: UniversalFiltersGroup = {
                type: FilterLogicalOperator.And,
                values: [{ key: 'env', value: 'prod', operator: 'exact', type: 'event' } as AnyPropertyFilter],
            }

            await expectLogic(logic, () => {
                logic.actions.setAlertFormValues({
                    ...VALID_FORM_VALUES,
                    severityLevels: [],
                    serviceNames: [],
                    filterGroup: innerGroup,
                })
                logic.actions.submitAlertForm()
            }).toFinishAllListeners()

            expect(mockLogsAlertsCreate).toHaveBeenCalledWith(
                MOCK_PROJECT_ID,
                expect.objectContaining({
                    filters: {
                        filterGroup: {
                            type: FilterLogicalOperator.And,
                            values: [innerGroup],
                        },
                    },
                })
            )
        })

        it('excludes empty filter keys from payload filters', async () => {
            await expectLogic(logic, () => {
                logic.actions.setAlertFormValues({
                    ...VALID_FORM_VALUES,
                    severityLevels: ['info'],
                    serviceNames: [],
                    filterGroup: { type: FilterLogicalOperator.And, values: [] },
                })
                logic.actions.submitAlertForm()
            }).toFinishAllListeners()

            const calledWith = mockLogsAlertsCreate.mock.calls[0][1]!
            expect((calledWith.filters as Record<string, unknown>).serviceNames).toBeUndefined()
            expect((calledWith.filters as Record<string, unknown>).filterGroup).toBeUndefined()
        })

        it('shows error toast when create API throws with detail', async () => {
            mockLogsAlertsCreate.mockRejectedValue({ detail: 'Quota exceeded' })

            await expectLogic(logic, () => {
                logic.actions.setAlertFormValues(VALID_FORM_VALUES)
                logic.actions.submitAlertForm()
            }).toFinishAllListeners()

            expect(lemonToast.error).toHaveBeenCalledWith('Quota exceeded')
        })

        it('shows error toast from message field when detail is absent', async () => {
            mockLogsAlertsCreate.mockRejectedValue(new Error('Network failure'))

            await expectLogic(logic, () => {
                logic.actions.setAlertFormValues(VALID_FORM_VALUES)
                logic.actions.submitAlertForm()
            }).toFinishAllListeners()

            expect(lemonToast.error).toHaveBeenCalledWith('Network failure')
        })

        it('shows fallback error toast when neither detail nor message is present', async () => {
            mockLogsAlertsCreate.mockRejectedValue({})

            await expectLogic(logic, () => {
                logic.actions.setAlertFormValues(VALID_FORM_VALUES)
                logic.actions.submitAlertForm()
            }).toFinishAllListeners()

            expect(lemonToast.error).toHaveBeenCalledWith('Failed to save alert')
        })
    })

    describe('edit path (props.alert is set)', () => {
        let logic: ReturnType<typeof logsAlertFormLogic.build>

        beforeEach(() => {
            mockLogsAlertsPartialUpdate.mockResolvedValue(MOCK_ALERT)
            logic = logsAlertFormLogic({ alert: MOCK_ALERT })
            logic.mount()
        })

        afterEach(() => {
            logic?.unmount()
        })

        it('calls logsAlertsPartialUpdate with correct alert id and payload on submit', async () => {
            await expectLogic(logic, () => {
                logic.actions.setAlertFormValues(VALID_FORM_VALUES)
                logic.actions.submitAlertForm()
            }).toFinishAllListeners()

            expect(mockLogsAlertsPartialUpdate).toHaveBeenCalledTimes(1)
            expect(mockLogsAlertsPartialUpdate).toHaveBeenCalledWith(
                MOCK_PROJECT_ID,
                MOCK_ALERT.id,
                expect.objectContaining({
                    name: 'My Alert',
                    filters: { severityLevels: ['error'] },
                    threshold_count: 100,
                    threshold_operator: 'above',
                    window_minutes: 10,
                    evaluation_periods: 1,
                    datapoints_to_alarm: 1,
                    cooldown_minutes: 0,
                })
            )
        })

        it('does not call logsAlertsCreate on edit path', async () => {
            await expectLogic(logic, () => {
                logic.actions.setAlertFormValues(VALID_FORM_VALUES)
                logic.actions.submitAlertForm()
            }).toFinishAllListeners()

            expect(mockLogsAlertsCreate).not.toHaveBeenCalled()
        })

        it('shows success toast after update', async () => {
            await expectLogic(logic, () => {
                logic.actions.setAlertFormValues(VALID_FORM_VALUES)
                logic.actions.submitAlertForm()
            }).toFinishAllListeners()

            expect(lemonToast.success).toHaveBeenCalledWith('Alert updated')
        })

        it('pre-populates name from existing alert', () => {
            expect(logic.values.alertForm.name).toBe(MOCK_ALERT.name)
        })

        it('pre-populates severityLevels from existing alert filters', () => {
            expect(logic.values.alertForm.severityLevels).toEqual(['error'])
        })

        it('allows existing alerts without filters', () => {
            const existingAlertWithoutFilters = { ...MOCK_ALERT, filters: null } as unknown as LogsAlertConfigurationApi

            expect(buildFormDefaults(existingAlertWithoutFilters).severityLevels).toEqual([])
        })

        it('pre-populates numeric fields from existing alert', () => {
            expect(logic.values.alertForm.thresholdCount).toBe(MOCK_ALERT.threshold_count)
            expect(logic.values.alertForm.windowMinutes).toBe(MOCK_ALERT.window_minutes)
            expect(logic.values.alertForm.evaluationPeriods).toBe(MOCK_ALERT.evaluation_periods)
            expect(logic.values.alertForm.datapointsToAlarm).toBe(MOCK_ALERT.datapoints_to_alarm)
            expect(logic.values.alertForm.cooldownMinutes).toBe(MOCK_ALERT.cooldown_minutes)
        })

        it('shows error toast when partial update API throws', async () => {
            mockLogsAlertsPartialUpdate.mockRejectedValue({ detail: 'Permission denied' })

            await expectLogic(logic, () => {
                logic.actions.setAlertFormValues(VALID_FORM_VALUES)
                logic.actions.submitAlertForm()
            }).toFinishAllListeners()

            expect(lemonToast.error).toHaveBeenCalledWith('Permission denied')
        })
    })

    describe('grouping', () => {
        it.each<[string, LogsAlertConfigurationApi | null, LogsAlertConfigurationApi[], boolean]>([
            ['alert the source owns', MOCK_ALERT, [], false],
            ['alert the source owns in a team that has cut over', MOCK_ALERT, [PLATFORM_ALERT], false],
            ['alert the platform owns', PLATFORM_ALERT, [], true],
            ['alert that already groups', GROUPED_BY_SERVICE_ALERT, [], true],
            ['new alert in a team that has not cut over', null, [MOCK_ALERT], false],
            ['new alert in a team that has cut over', null, [MOCK_ALERT, PLATFORM_ALERT], true],
        ])('can group for %s', async (_, alert, teamAlerts, expected) => {
            givenTeamAlerts(teamAlerts)
            const logic = logsAlertFormLogic({ alert })
            logic.mount()

            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.canGroup).toBe(expected)
            logic.unmount()
        })

        it.each<[string, LogsAlertConfigurationApi, string]>([
            [
                'an ungrouped alert that is not firing',
                PLATFORM_ALERT,
                "Saving resets this alert's state, and it starts tracking each group on its own.",
            ],
            [
                'an ungrouped alert that is firing',
                { ...PLATFORM_ALERT, state: LogsAlertConfigurationStateEnumApi.Firing },
                "Saving resets this alert's state, and it starts tracking each group on its own. The alert is firing now, so its open notification won't get a resolve message.",
            ],
            [
                'a grouped alert',
                GROUPED_BY_SERVICE_ALERT,
                "Saving resets every group this alert tracks. Groups that are firing now won't get a resolve message for their open notifications.",
            ],
        ])('describes regrouping %s', (_, alert, expected) => {
            const logic = logsAlertFormLogic({ alert })
            logic.mount()

            expect(logic.values.regroupConfirmation).toBe(expected)
            logic.unmount()
        })

        it('leaves grouping out of the payload when the alert cannot group', async () => {
            mockLogsAlertsPartialUpdate.mockResolvedValue(MOCK_ALERT)
            const logic = logsAlertFormLogic({ alert: MOCK_ALERT })
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.setAlertFormValues(VALID_FORM_VALUES)
                logic.actions.submitAlertForm()
            }).toFinishAllListeners()

            expect(mockLogsAlertsPartialUpdate.mock.calls[0][2]).not.toHaveProperty('grouping')
            logic.unmount()
        })

        it('creates a grouped alert with the default group limit in a cut-over team', async () => {
            givenTeamAlerts([PLATFORM_ALERT])
            mockLogsAlertsCreate.mockResolvedValue(MOCK_CREATED_ALERT)
            const logic = logsAlertFormLogic({ alert: null })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.setAlertFormValues(VALID_FORM_VALUES)
                logic.actions.setGroupBy('service_and_severity')
                logic.actions.submitAlertForm()
            }).toFinishAllListeners()

            expect(logic.values.isRegroupConfirmationOpen).toBe(false)
            expect(mockLogsAlertsCreate.mock.calls[0][1]).toMatchObject({
                grouping: { mode: 'by_result_labels', keys: ['service_name', 'severity_text'], max_instances: 20 },
            })
            expect(posthog.capture).toHaveBeenCalledWith('logs alert grouping changed', {
                group_by: 'service_and_severity',
                previous_group_by: 'none',
                is_editing: false,
            })
            logic.unmount()
        })

        it('asks before regrouping a platform alert and saves once confirmed', async () => {
            mockLogsAlertsPartialUpdate.mockResolvedValue(PLATFORM_ALERT)
            const logic = logsAlertFormLogic({ alert: PLATFORM_ALERT })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.setGroupBy('service')
                logic.actions.submitAlertForm()
            }).toFinishAllListeners()

            expect(logic.values.isRegroupConfirmationOpen).toBe(true)
            expect(mockLogsAlertsPartialUpdate).not.toHaveBeenCalled()

            await expectLogic(logic, () => {
                logic.actions.confirmRegroup()
            }).toFinishAllListeners()

            expect(mockLogsAlertsPartialUpdate).toHaveBeenCalledWith(
                MOCK_PROJECT_ID,
                PLATFORM_ALERT.id,
                expect.objectContaining({
                    grouping: { mode: 'by_result_labels', keys: ['service_name'], max_instances: 20 },
                })
            )
            expect(posthog.capture).toHaveBeenCalledWith('logs alert regroup confirmed', {
                group_by: 'service',
                previous_group_by: 'none',
            })
            logic.unmount()
        })

        it.each<[string, LogsAlertConfigurationApi, Partial<LogsAlertFormType>, LogsAlertGroupingApi | undefined]>([
            [
                'a new group limit',
                GROUPED_BY_SERVICE_ALERT,
                { maxInstances: 50 },
                { mode: GroupingModeEnumApi.ByResultLabels, keys: ['service_name'], max_instances: 50 },
            ],
            [
                'a rename, keeping the stored key order',
                {
                    ...MOCK_ALERT,
                    grouping: {
                        mode: GroupingModeEnumApi.ByResultLabels,
                        keys: ['severity_text', 'service_name'],
                        max_instances: 30,
                    },
                },
                { name: 'Renamed' },
                {
                    mode: GroupingModeEnumApi.ByResultLabels,
                    keys: ['severity_text', 'service_name'],
                    max_instances: 30,
                },
            ],
            [
                'a rename of an alert grouped by keys the form cannot show',
                {
                    ...MOCK_ALERT,
                    grouping: {
                        mode: GroupingModeEnumApi.ByResultLabels,
                        keys: ['service_name', 'http_route'],
                        max_instances: 30,
                    },
                },
                { name: 'Renamed' },
                undefined,
            ],
        ])('saves %s without regrouping', async (_, alert, change, expectedGrouping) => {
            mockLogsAlertsPartialUpdate.mockResolvedValue(alert)
            const logic = logsAlertFormLogic({ alert })
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.setAlertFormValues(change)
                logic.actions.submitAlertForm()
            }).toFinishAllListeners()

            expect(logic.values.isRegroupConfirmationOpen).toBe(false)
            expect(mockLogsAlertsPartialUpdate.mock.calls[0][2]?.grouping).toEqual(expectedGrouping)
            logic.unmount()
        })

        it.each([NaN, 0, 101, 2.5])('blocks a save with a group limit of %s', async (maxInstances) => {
            const logic = logsAlertFormLogic({ alert: GROUPED_BY_SERVICE_ALERT })
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.setAlertFormValue('maxInstances', maxInstances)
                logic.actions.submitAlertForm()
            }).toFinishAllListeners()

            expect(logic.values.alertFormValidationErrors.maxInstances).toBe('Enter a whole number from 1 to 100.')
            expect(mockLogsAlertsPartialUpdate).not.toHaveBeenCalled()
            logic.unmount()
        })

        it.each<[LogsAlertGroupBy, boolean]>([
            ['service', false],
            ['none', true],
        ])('simulates an alert grouped by %s: %s', async (groupBy, simulates) => {
            mockLogsAlertsSimulateCreate.mockResolvedValue({} as LogsAlertSimulateResponseApi)
            const logic = logsAlertFormLogic({ alert: GROUPED_BY_SERVICE_ALERT })
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.setGroupBy(groupBy)
                logic.actions.simulateAlert()
            }).toFinishAllListeners()

            expect(mockLogsAlertsSimulateCreate).toHaveBeenCalledTimes(simulates ? 1 : 0)
            logic.unmount()
        })
    })

    describe('isEditing selector', () => {
        it('is false when props.alert is null', () => {
            const logic = logsAlertFormLogic({ alert: null })
            logic.mount()

            expect(logic.values.isEditing).toBe(false)

            logic.unmount()
        })

        it('is true when props.alert is provided', () => {
            const logic = logsAlertFormLogic({ alert: MOCK_ALERT })
            logic.mount()

            expect(logic.values.isEditing).toBe(true)

            logic.unmount()
        })
    })

    describe('form defaults', () => {
        it('uses sensible defaults when creating a new alert', () => {
            const logic = logsAlertFormLogic({ alert: null })
            logic.mount()

            expect(logic.values.alertForm).toMatchObject({
                name: '',
                severityLevels: ['trace', 'debug', 'info', 'warn', 'error', 'fatal'],
                serviceNames: [],
                thresholdOperator: 'above',
                thresholdCount: 100,
                windowMinutes: 10,
                evaluationPeriods: 1,
                datapointsToAlarm: 1,
                cooldownMinutes: 0,
                groupBy: 'none',
                maxInstances: 20,
            })

            logic.unmount()
        })
    })
})
