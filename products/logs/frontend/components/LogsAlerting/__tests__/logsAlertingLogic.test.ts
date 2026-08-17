import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { lemonToast } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'

import { resolveSnoozeUntil } from 'products/alerts/frontend/utils'
import {
    logsAlertsCreate,
    logsAlertsList,
    logsAlertsPartialUpdate,
    logsAlertsResetCreate,
} from 'products/logs/frontend/generated/api'
import {
    LogsAlertConfigurationApi,
    LogsAlertConfigurationStateEnumApi,
} from 'products/logs/frontend/generated/api.schemas'

import { logsAlertingLogic } from '../logsAlertingLogic'

jest.mock('products/logs/frontend/generated/api', () => ({
    __esModule: true,
    logsAlertsCreate: jest.fn(),
    logsAlertsDestroy: jest.fn(),
    logsAlertsList: jest.fn().mockResolvedValue({ results: [] }),
    logsAlertsPartialUpdate: jest.fn(),
    logsAlertsResetCreate: jest.fn(),
}))

jest.mock('@posthog/lemon-ui', () => ({
    ...jest.requireActual('@posthog/lemon-ui'),
    lemonToast: {
        success: jest.fn(),
        error: jest.fn(),
    },
}))

const mockReset = logsAlertsResetCreate as jest.MockedFunction<typeof logsAlertsResetCreate>
const mockList = logsAlertsList as jest.MockedFunction<typeof logsAlertsList>
const mockCreate = logsAlertsCreate as jest.MockedFunction<typeof logsAlertsCreate>
const mockPartialUpdate = logsAlertsPartialUpdate as jest.MockedFunction<typeof logsAlertsPartialUpdate>

const MOCK_ALERT: LogsAlertConfigurationApi = {
    id: 'alert-1',
    name: 'Errors',
    enabled: true,
    filters: { severityLevels: ['error'] },
    threshold_count: 100,
    threshold_operator: 'above',
    window_minutes: 5,
    evaluation_periods: 1,
    datapoints_to_alarm: 1,
    cooldown_minutes: 0,
    snooze_until: null,
    check_interval_minutes: 5,
    state: LogsAlertConfigurationStateEnumApi.NotFiring,
    next_check_at: null,
    last_notified_at: null,
    last_checked_at: null,
    consecutive_failures: 0,
    last_error_message: null,
    state_timeline: [],
    destination_types: [],
    first_enabled_at: null,
    created_at: '2026-08-12T12:00:00.000Z',
    created_by: {
        id: 1,
        uuid: 'user-1',
        email: 'test@example.com',
        hedgehog_config: null,
    },
    updated_at: null,
}

function createMockAlert(overrides: Partial<LogsAlertConfigurationApi> = {}): LogsAlertConfigurationApi {
    return { ...MOCK_ALERT, ...overrides }
}

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
    let resolve!: (value: T) => void
    const promise = new Promise<T>((resolvePromise) => {
        resolve = resolvePromise
    })
    return { promise, resolve }
}

describe('logsAlertingLogic', () => {
    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
        mockList.mockResolvedValue({ count: 0, results: [] })
    })

    describe('createdByFilter', () => {
        it('reloads alerts with the selected creator UUID', async () => {
            const logic = logsAlertingLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            mockList.mockClear()

            await expectLogic(logic, () => {
                logic.actions.setCreatedByFilter('019abcde-1234-7000-8000-000000000001')
            }).toFinishAllListeners()

            expect(mockList).toHaveBeenCalledWith(expect.any(String), {
                limit: 500,
                created_by: '019abcde-1234-7000-8000-000000000001',
            })

            logic.unmount()
        })

        it('clears the selected creator when the project changes', async () => {
            const logic = logsAlertingLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.setCreatedByFilter('019abcde-1234-7000-8000-000000000001')
            }).toFinishAllListeners()
            mockList.mockClear()

            const nextTeamId = MOCK_DEFAULT_TEAM.id + 1
            await expectLogic(logic, () => {
                teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, id: nextTeamId })
            })
                .toFinishAllListeners()
                .toMatchValues({ createdByFilter: null })

            expect(mockList).toHaveBeenCalledWith(String(nextTeamId), { limit: 500 })

            logic.unmount()
        })

        it('discards alerts returned for the previous project', async () => {
            const logic = logsAlertingLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            const previousProjectResponse = deferred<Awaited<ReturnType<typeof logsAlertsList>>>()
            const currentProjectAlerts = [createMockAlert({ id: 'current-project-alert' })]
            const nextTeamId = MOCK_DEFAULT_TEAM.id + 1
            mockList.mockImplementation((projectId) => {
                if (projectId === String(MOCK_DEFAULT_TEAM.id)) {
                    return previousProjectResponse.promise
                }
                return Promise.resolve({ count: currentProjectAlerts.length, results: currentProjectAlerts })
            })
            await expectLogic(logic, () => {
                logic.actions.setCreatedByFilter('019abcde-1234-7000-8000-000000000001')
            }).toDispatchActions(['loadAlerts'])

            await expectLogic(logic, () => {
                teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, id: nextTeamId })
            }).toDispatchActions(['loadAlerts', 'loadAlertsSuccess'])
            expect(logic.values.alerts).toEqual(currentProjectAlerts)

            previousProjectResponse.resolve({
                count: 1,
                results: [createMockAlert({ id: 'previous-project-alert' })],
            })
            await Promise.resolve()
            await Promise.resolve()

            expect(logic.values.alerts).toEqual(currentProjectAlerts)

            logic.unmount()
        })
    })

    describe('resetAlert', () => {
        it('calls the reset endpoint, reloads the list, and surfaces a success toast', async () => {
            mockReset.mockResolvedValue(MOCK_ALERT)

            const logic = logsAlertingLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            mockList.mockClear()

            await expectLogic(logic, () => {
                logic.actions.resetAlert('alert-1')
            }).toFinishAllListeners()

            expect(mockReset).toHaveBeenCalledWith(expect.any(String), 'alert-1')
            expect(lemonToast.success).toHaveBeenCalledWith(expect.stringContaining('Alert reset'))
            expect(mockList).toHaveBeenCalledTimes(1)

            logic.unmount()
        })

        it('surfaces an error toast and does not reload on failure', async () => {
            mockReset.mockRejectedValue(new Error('boom'))

            const logic = logsAlertingLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            mockList.mockClear()

            await expectLogic(logic, () => {
                logic.actions.resetAlert('alert-1')
            }).toFinishAllListeners()

            expect(lemonToast.error).toHaveBeenCalledWith('Failed to reset alert')
            expect(mockList).not.toHaveBeenCalled()

            logic.unmount()
        })
    })

    describe('create alert modal', () => {
        it('opens without creating an empty draft', async () => {
            const logic = logsAlertingLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.openCreateAlertModal()
            }).toMatchValues({ isCreateAlertModalOpen: true })

            expect(mockCreate).not.toHaveBeenCalled()

            logic.unmount()
        })
    })

    describe('edit alert modal', () => {
        it('opens for the selected alert and clears it on close', async () => {
            const logic = logsAlertingLogic()
            const alert = createMockAlert()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.openEditAlertModal(alert)
            }).toMatchValues({ editingAlert: alert })

            await expectLogic(logic, () => {
                logic.actions.closeEditAlertModal()
            }).toMatchValues({ editingAlert: null })

            logic.unmount()
        })

        it('updates the open editor after disabling an alert', async () => {
            const logic = logsAlertingLogic()
            const alert = createMockAlert()
            const updatedAlert = { ...alert, enabled: false }
            mockPartialUpdate.mockResolvedValue(updatedAlert)
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.openEditAlertModal(alert)
            await expectLogic(logic, () => {
                logic.actions.toggleAlertEnabled(alert)
            })
                .toFinishAllListeners()
                .toMatchValues({ editingAlert: updatedAlert })

            expect(mockPartialUpdate).toHaveBeenCalledWith(expect.any(String), alert.id, {
                enabled: false,
                snooze_until: null,
            })

            logic.unmount()
        })

        it('updates the open editor after snoozing an alert', async () => {
            const logic = logsAlertingLogic()
            const alert = createMockAlert()
            const updatedAlert = { ...alert, snooze_until: '2026-08-13T12:00:00.000Z' }
            mockPartialUpdate.mockResolvedValue(updatedAlert)
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.openEditAlertModal(alert)
            await expectLogic(logic, () => {
                logic.actions.snoozeAlertUntil(alert.id, '+1d')
            })
                .toFinishAllListeners()
                .toMatchValues({ editingAlert: updatedAlert })

            logic.unmount()
        })

        it('does not open the editor after snoozing from the alert list', async () => {
            const logic = logsAlertingLogic()
            const alert = createMockAlert()
            mockPartialUpdate.mockResolvedValue({ ...alert, snooze_until: '2026-08-13T12:00:00.000Z' })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.snoozeAlertUntil(alert.id, '+1d')
            })
                .toFinishAllListeners()
                .toMatchValues({ editingAlert: null })

            logic.unmount()
        })

        it('updates the open editor after unsnoozing an alert', async () => {
            const logic = logsAlertingLogic()
            const alert = createMockAlert({ snooze_until: '2026-08-13T12:00:00.000Z' })
            const updatedAlert = { ...alert, snooze_until: null }
            mockPartialUpdate.mockResolvedValue(updatedAlert)
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.openEditAlertModal(alert)
            await expectLogic(logic, () => {
                logic.actions.unsnoozeAlert(alert.id)
            })
                .toFinishAllListeners()
                .toMatchValues({ editingAlert: updatedAlert })

            logic.unmount()
        })
    })

    describe('resolveSnoozeUntil', () => {
        it.each([
            ['+30m', '2026-08-12T12:30:00.000Z'],
            ['+1d', '2026-08-13T12:00:00.000Z'],
            ['+1w', '2026-08-19T12:00:00.000Z'],
            ['+1M', '2026-09-12T12:00:00.000Z'],
            ['+1y', '2027-08-12T12:00:00.000Z'],
        ])('converts %s into an ISO datetime', (value: string, expected: string) => {
            jest.useFakeTimers().setSystemTime(new Date('2026-08-12T12:00:00.000Z'))

            expect(resolveSnoozeUntil(value)).toBe(expected)

            jest.useRealTimers()
        })

        it('preserves a custom datetime', () => {
            expect(resolveSnoozeUntil('2026-08-13T14:30:00.000Z')).toBe('2026-08-13T14:30:00.000Z')
        })
    })
})
