import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { logsAlertFormLogic } from 'products/logs/frontend/components/LogsAlerting/logsAlertFormLogic'
import { logsAlertingLogic } from 'products/logs/frontend/components/LogsAlerting/logsAlertingLogic'
import {
    LogsAlertConfigurationApi,
    LogsAlertConfigurationStateEnumApi,
} from 'products/logs/frontend/generated/api.schemas'

import { logsAlertDetailSceneLogic } from '../logsAlertDetailSceneLogic'

jest.mock('lib/api', () => ({
    __esModule: true,
    default: {
        hogFunctions: {
            list: jest.fn().mockResolvedValue({ results: [] }),
        },
        // integrations.list is reached by integrationsLogic via the notification-logic
        // connect chain — silence the loader so it doesn't spew console.error noise.
        integrations: {
            list: jest.fn().mockResolvedValue({ results: [] }),
        },
        logs: {
            sparkline: jest.fn().mockResolvedValue([]),
        },
    },
}))

const MOCK_ALERT_ID = 'alert-uuid-1'

const MOCK_ALERT: LogsAlertConfigurationApi = {
    id: MOCK_ALERT_ID,
    name: 'Test Alert',
    enabled: false,
    filters: { severityLevels: ['error'] },
    threshold_count: 50,
    threshold_operator: 'above',
    window_minutes: 5,
    evaluation_periods: 1,
    datapoints_to_alarm: 1,
    cooldown_minutes: 0,
    state: LogsAlertConfigurationStateEnumApi.NotFiring,
    check_interval_minutes: 5,
    next_check_at: null,
    last_notified_at: null,
    last_checked_at: null,
    consecutive_failures: 0,
    last_error_message: null,
    // Non-empty so runPreEnableChecks short-circuits past the "no destinations" warning.
    destination_types: ['slack'],
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

jest.mock('products/logs/frontend/generated/api', () => ({
    __esModule: true,
    logsAlertsRetrieve: jest.fn(),
    logsAlertsPartialUpdate: jest.fn(),
    logsAlertsCreate: jest.fn(),
    logsAlertsDestroy: jest.fn(),
    logsAlertsResetCreate: jest.fn(),
    logsAlertsList: jest.fn().mockResolvedValue({ results: [], count: 0 }),
    logsAlertsEventsList: jest.fn().mockResolvedValue({ results: [], next: null, count: 0 }),
    logsAlertsSimulateCreate: jest.fn(),
    logsAlertsDestinationsCreate: jest.fn(),
    logsAlertsDestinationsDeleteCreate: jest.fn(),
}))

jest.mock('@posthog/lemon-ui', () => ({
    ...jest.requireActual('@posthog/lemon-ui'),
    LemonDialog: { open: jest.fn() },
    lemonToast: { success: jest.fn(), error: jest.fn() },
}))

const mockedApi = require('products/logs/frontend/generated/api')

describe('logsAlertDetailSceneLogic — save-then-enable chain', () => {
    let alertingLogic: ReturnType<typeof logsAlertingLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()

        mockedApi.logsAlertsRetrieve.mockResolvedValue(MOCK_ALERT)
        mockedApi.logsAlertsPartialUpdate.mockResolvedValue({ ...MOCK_ALERT, enabled: true })
        mockedApi.logsAlertsList.mockResolvedValue({ results: [], count: 0 })
        mockedApi.logsAlertsEventsList.mockResolvedValue({ results: [], next: null, count: 0 })

        alertingLogic = logsAlertingLogic.build()
        alertingLogic.mount()
    })

    afterEach(() => {
        alertingLogic?.unmount()
    })

    async function mountSceneLogic(): Promise<ReturnType<typeof logsAlertDetailSceneLogic.build>> {
        const logic = logsAlertDetailSceneLogic({ id: MOCK_ALERT_ID })
        logic.mount()
        // Wait for loadAlert + chained loaders/listeners triggered on mount.
        await expectLogic(logic).toFinishAllListeners()
        return logic
    }

    it('marks pending and submits form when form is dirty', async () => {
        const logic = await mountSceneLogic()
        const formLogic = logsAlertFormLogic({ alert: { id: MOCK_ALERT_ID } as LogsAlertConfigurationApi })

        formLogic.actions.setAlertFormValue('name', 'Renamed alert')

        await expectLogic(logic, () => {
            logic.actions.enableAlert()
        }).toDispatchActions(['enableAlert', 'markPendingEnable', 'submitAlertForm'])

        logic.unmount()
    })

    it('calls applyEnabledChange(true) after submitAlertFormSuccess when pending', async () => {
        const logic = await mountSceneLogic()

        await expectLogic(logic, () => {
            logic.actions.markPendingEnable()
        })
            .toDispatchActions(['markPendingEnable'])
            .toMatchValues({ pendingEnableAfterSave: true })

        await expectLogic(logic, () => {
            logic.actions.submitAlertFormSuccess({} as any)
        }).toDispatchActions(['submitAlertFormSuccess', logic.actionCreators.applyEnabledChange(true)])

        // Reducer flips back to false once applyEnabledChange fires.
        expect(logic.values.pendingEnableAfterSave).toBe(false)

        logic.unmount()
    })

    it('does not call applyEnabledChange when submitAlertFormSuccess fires without pending', async () => {
        const logic = await mountSceneLogic()

        // pendingEnableAfterSave starts false — confirm the listener no-ops.
        expect(logic.values.pendingEnableAfterSave).toBe(false)

        await expectLogic(logic, () => {
            logic.actions.submitAlertFormSuccess({} as any)
        })
            .toDispatchActions(['submitAlertFormSuccess', 'loadAlert'])
            .toNotHaveDispatchedActions(['applyEnabledChange'])

        logic.unmount()
    })
})
