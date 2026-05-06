import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { initKeaTests } from '~/test/init'
import { HogFunctionType } from '~/types'

import { logsAlertsDestinationsCreate, logsAlertsDestinationsDeleteCreate } from 'products/logs/frontend/generated/api'

import { logsAlertNotificationLogic } from '../logsAlertNotificationLogic'
import { buildLogsAlertFilterConfig, LogsAlertDestinationGroup } from '../logsAlertUtils'

jest.mock('lib/api', () => ({
    __esModule: true,
    default: {
        hogFunctions: {
            list: jest.fn(),
        },
    },
}))

jest.mock('products/logs/frontend/generated/api', () => ({
    __esModule: true,
    logsAlertsDestinationsCreate: jest.fn(),
    logsAlertsDestinationsDeleteCreate: jest.fn(),
}))

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: {
        success: jest.fn(),
        error: jest.fn(),
    },
}))

const mockApi = api as jest.Mocked<typeof api>
const mockCreate = logsAlertsDestinationsCreate as jest.MockedFunction<typeof logsAlertsDestinationsCreate>
const mockDelete = logsAlertsDestinationsDeleteCreate as jest.MockedFunction<typeof logsAlertsDestinationsDeleteCreate>

const MOCK_HOG_FUNCTION = {
    id: 'hf-1',
    name: 'Test Notification',
    enabled: true,
    inputs: { channel: { value: 'C123' } },
    filters: {},
} as unknown as HogFunctionType

describe('logsAlertNotificationLogic', () => {
    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
        ;(mockApi.hogFunctions.list as jest.Mock).mockResolvedValue({ results: [] })
    })

    describe('pending notifications', () => {
        it('adds a pending notification', () => {
            const logic = logsAlertNotificationLogic({ alertId: undefined })
            logic.mount()

            logic.actions.addPendingNotification({
                type: 'slack',
                slackWorkspaceId: 1,
                slackChannelId: 'C123',
                slackChannelName: 'alerts',
            })

            expect(logic.values.pendingNotifications).toHaveLength(1)
            expect(logic.values.pendingNotifications[0]).toMatchObject({
                type: 'slack',
                slackChannelId: 'C123',
            })

            logic.unmount()
        })

        it('removes a pending notification by index', () => {
            const logic = logsAlertNotificationLogic({ alertId: undefined })
            logic.mount()

            logic.actions.addPendingNotification({ type: 'webhook', webhookUrl: 'https://a.com' })
            logic.actions.addPendingNotification({ type: 'webhook', webhookUrl: 'https://b.com' })

            logic.actions.removePendingNotification(0)

            expect(logic.values.pendingNotifications).toHaveLength(1)
            expect(logic.values.pendingNotifications[0]).toMatchObject({ webhookUrl: 'https://b.com' })

            logic.unmount()
        })

        it('clears all pending notifications', () => {
            const logic = logsAlertNotificationLogic({ alertId: undefined })
            logic.mount()

            logic.actions.addPendingNotification({ type: 'webhook', webhookUrl: 'https://a.com' })
            logic.actions.addPendingNotification({ type: 'webhook', webhookUrl: 'https://b.com' })

            logic.actions.clearPendingNotifications()

            expect(logic.values.pendingNotifications).toHaveLength(0)

            logic.unmount()
        })
    })

    describe('loadExistingHogFunctions', () => {
        it('returns empty array when no alertId', async () => {
            const logic = logsAlertNotificationLogic({ alertId: undefined })
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.loadExistingHogFunctions()
            }).toFinishAllListeners()

            expect(logic.values.existingHogFunctions).toEqual([])
            expect(mockApi.hogFunctions.list).not.toHaveBeenCalled()

            logic.unmount()
        })

        it('loads hog functions filtered by alert id only (not by event)', async () => {
            ;(mockApi.hogFunctions.list as jest.Mock).mockResolvedValue({
                results: [MOCK_HOG_FUNCTION],
            })

            const logic = logsAlertNotificationLogic({ alertId: 'alert-1' })
            logic.mount()

            await expectLogic(logic).toFinishAllListeners()

            expect(mockApi.hogFunctions.list).toHaveBeenCalledWith({
                types: ['internal_destination'],
                filter_groups: [buildLogsAlertFilterConfig('alert-1')],
                full: true,
            })
            // The filter must not include events — otherwise per-event HogFunctions
            // created by the backend fan-out won't match the JSONB @> query.
            expect(mockApi.hogFunctions.list).toHaveBeenCalledWith(
                expect.objectContaining({
                    filter_groups: [expect.not.objectContaining({ events: expect.anything() })],
                })
            )
            expect(logic.values.existingHogFunctions).toEqual([MOCK_HOG_FUNCTION])

            logic.unmount()
        })
    })

    describe('createPendingHogFunctions', () => {
        it('skips when no pending notifications', async () => {
            const logic = logsAlertNotificationLogic({ alertId: undefined })
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.createPendingHogFunctions('alert-1')
            }).toFinishAllListeners()

            expect(mockCreate).not.toHaveBeenCalled()

            logic.unmount()
        })

        it('sends one bundle-create call per pending notification (backend fans out per event)', async () => {
            mockCreate.mockResolvedValue({ hog_function_ids: ['hf-1', 'hf-2'] } as any)

            const logic = logsAlertNotificationLogic({ alertId: undefined })
            logic.mount()

            logic.actions.addPendingNotification({ type: 'webhook', webhookUrl: 'https://a.com' })
            logic.actions.addPendingNotification({
                type: 'slack',
                slackWorkspaceId: 42,
                slackChannelId: 'C456',
                slackChannelName: 'alerts',
            })

            await expectLogic(logic, () => {
                logic.actions.createPendingHogFunctions('alert-1')
            }).toFinishAllListeners()

            expect(mockCreate).toHaveBeenCalledTimes(2)
            expect(mockCreate).toHaveBeenCalledWith(expect.any(String), 'alert-1', {
                type: 'webhook',
                webhook_url: 'https://a.com',
            })
            expect(mockCreate).toHaveBeenCalledWith(expect.any(String), 'alert-1', {
                type: 'slack',
                slack_workspace_id: 42,
                slack_channel_id: 'C456',
                slack_channel_name: 'alerts',
            })
            expect(lemonToast.success).toHaveBeenCalledWith('2 notification destination(s) created.')
            expect(logic.values.pendingNotifications).toHaveLength(0)

            logic.unmount()
        })

        it('retains only the failed notifications so the user can retry them', async () => {
            mockCreate
                .mockResolvedValueOnce({ hog_function_ids: ['hf-ok'] } as any)
                .mockRejectedValueOnce(new Error('API error'))

            const logic = logsAlertNotificationLogic({ alertId: undefined })
            logic.mount()

            logic.actions.addPendingNotification({ type: 'webhook', webhookUrl: 'https://ok.com' })
            logic.actions.addPendingNotification({ type: 'webhook', webhookUrl: 'https://fail.com' })

            await expectLogic(logic, () => {
                logic.actions.createPendingHogFunctions('alert-1')
            }).toFinishAllListeners()

            expect(lemonToast.error).toHaveBeenCalledWith(expect.stringContaining('1 notification(s) failed to create'))
            expect(logic.values.pendingNotifications).toHaveLength(1)
            expect(logic.values.pendingNotifications[0]).toMatchObject({ webhookUrl: 'https://fail.com' })

            logic.unmount()
        })
    })

    describe('deleteExistingDestination', () => {
        it('sends the whole group of HogFunction ids in a single atomic delete call', async () => {
            ;(mockApi.hogFunctions.list as jest.Mock).mockResolvedValue({
                results: [MOCK_HOG_FUNCTION],
            })
            mockDelete.mockResolvedValue(undefined as any)

            const logic = logsAlertNotificationLogic({ alertId: 'alert-1' })
            logic.mount()

            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.existingHogFunctions).toHaveLength(1)

            const group: LogsAlertDestinationGroup = {
                key: 'slack:C123',
                type: 'slack',
                label: 'Slack #alerts',
                hogFunctions: [MOCK_HOG_FUNCTION, { ...MOCK_HOG_FUNCTION, id: 'hf-2' }],
                enabled: true,
            }

            logic.actions.deleteExistingDestination(group)
            await expectLogic(logic).toFinishAllListeners()

            expect(mockDelete).toHaveBeenCalledWith(expect.any(String), 'alert-1', {
                hog_function_ids: ['hf-1', 'hf-2'],
            })
            expect(lemonToast.success).toHaveBeenCalledWith('Removed Slack #alerts')
            expect(mockApi.hogFunctions.list).toHaveBeenCalledTimes(2)

            logic.unmount()
        })

        it('reloads from the server on delete failure so the list reflects actual state', async () => {
            ;(mockApi.hogFunctions.list as jest.Mock).mockResolvedValue({
                results: [MOCK_HOG_FUNCTION],
            })
            mockDelete.mockRejectedValue(new Error('network'))

            const logic = logsAlertNotificationLogic({ alertId: 'alert-1' })
            logic.mount()

            await expectLogic(logic).toFinishAllListeners()

            const group: LogsAlertDestinationGroup = {
                key: 'slack:C123',
                type: 'slack',
                label: 'Slack #alerts',
                hogFunctions: [MOCK_HOG_FUNCTION],
                enabled: true,
            }

            logic.actions.deleteExistingDestination(group)
            await expectLogic(logic).toFinishAllListeners()

            expect(lemonToast.error).toHaveBeenCalledWith(expect.stringContaining('Failed to remove Slack #alerts'))
            // List loader fired twice: once on mount, once after the error
            expect(mockApi.hogFunctions.list).toHaveBeenCalledTimes(2)

            logic.unmount()
        })
    })
})
