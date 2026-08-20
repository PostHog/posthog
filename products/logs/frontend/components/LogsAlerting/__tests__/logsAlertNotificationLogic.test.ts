import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { initKeaTests } from '~/test/init'

import {
    logsAlertsDestinationsCreate,
    logsAlertsDestinationsDeleteCreate,
    logsAlertsDestinationsList,
} from 'products/logs/frontend/generated/api'
import { LogsAlertDestinationConfigApi } from 'products/logs/frontend/generated/api.schemas'

import { logsAlertNotificationLogic } from '../logsAlertNotificationLogic'

jest.mock('products/logs/frontend/generated/api', () => ({
    __esModule: true,
    logsAlertsDestinationsCreate: jest.fn(),
    logsAlertsDestinationsDeleteCreate: jest.fn(),
    logsAlertsDestinationsList: jest.fn(),
}))

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: {
        success: jest.fn(),
        error: jest.fn(),
    },
}))

const mockCreate = logsAlertsDestinationsCreate as jest.MockedFunction<typeof logsAlertsDestinationsCreate>
const mockDelete = logsAlertsDestinationsDeleteCreate as jest.MockedFunction<typeof logsAlertsDestinationsDeleteCreate>
const mockList = logsAlertsDestinationsList as jest.MockedFunction<typeof logsAlertsDestinationsList>

const MOCK_DESTINATION: LogsAlertDestinationConfigApi = {
    hog_function_ids: ['hf-1', 'hf-2'],
    type: 'slack',
    enabled: true,
    slack_workspace_id: 1,
    slack_channel_id: 'C123',
}

function onePage(results: LogsAlertDestinationConfigApi[]): ReturnType<typeof logsAlertsDestinationsList> {
    return Promise.resolve({ count: results.length, next: null, previous: null, results })
}

describe('logsAlertNotificationLogic', () => {
    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
        mockList.mockReturnValue(onePage([]))
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

    describe('loadExistingDestinations', () => {
        it('returns empty array when no alertId', async () => {
            const logic = logsAlertNotificationLogic({ alertId: undefined })
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.loadExistingDestinations()
            }).toFinishAllListeners()

            expect(logic.values.existingDestinations).toEqual([])
            expect(mockList).not.toHaveBeenCalled()

            logic.unmount()
        })

        it("loads the alert's destinations from the alert endpoint", async () => {
            mockList.mockReturnValue(onePage([MOCK_DESTINATION]))

            const logic = logsAlertNotificationLogic({ alertId: 'alert-1' })
            logic.mount()

            await expectLogic(logic).toFinishAllListeners()

            expect(mockList).toHaveBeenCalledWith(expect.any(String), 'alert-1', { limit: 100, offset: 0 })
            expect(logic.values.existingDestinations).toEqual([MOCK_DESTINATION])

            logic.unmount()
        })

        it('keeps two Slack destinations that share a channel id in different workspaces apart', async () => {
            const workspaceOne = { ...MOCK_DESTINATION, hog_function_ids: ['hf-1'], slack_workspace_id: 1 }
            const workspaceTwo = { ...MOCK_DESTINATION, hog_function_ids: ['hf-2'], slack_workspace_id: 2 }
            mockList.mockReturnValue(onePage([workspaceOne, workspaceTwo]))

            const logic = logsAlertNotificationLogic({ alertId: 'alert-1' })
            logic.mount()

            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.existingDestinations).toEqual([workspaceOne, workspaceTwo])

            logic.unmount()
        })

        it('reads every page so a long destination list is not truncated', async () => {
            const firstPage = Array.from({ length: 100 }, (_, index) => ({
                ...MOCK_DESTINATION,
                hog_function_ids: [`hf-${index}`],
            }))
            mockList
                .mockReturnValueOnce(Promise.resolve({ count: 101, next: 'next', previous: null, results: firstPage }))
                .mockReturnValueOnce(
                    Promise.resolve({ count: 101, next: null, previous: 'prev', results: [MOCK_DESTINATION] })
                )

            const logic = logsAlertNotificationLogic({ alertId: 'alert-1' })
            logic.mount()

            await expectLogic(logic).toFinishAllListeners()

            expect(mockList).toHaveBeenNthCalledWith(2, expect.any(String), 'alert-1', { limit: 100, offset: 100 })
            expect(logic.values.existingDestinations).toHaveLength(101)

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
        it('sends the listed destination’s whole group of HogFunction ids in one atomic call', async () => {
            mockList.mockReturnValue(onePage([MOCK_DESTINATION]))
            mockDelete.mockResolvedValue(undefined as any)

            const logic = logsAlertNotificationLogic({ alertId: 'alert-1' })
            logic.mount()

            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.existingDestinations).toHaveLength(1)

            logic.actions.deleteExistingDestination(logic.values.existingDestinations[0], 'Slack #alerts')
            await expectLogic(logic).toFinishAllListeners()

            expect(mockDelete).toHaveBeenCalledWith(expect.any(String), 'alert-1', {
                hog_function_ids: ['hf-1', 'hf-2'],
            })
            expect(lemonToast.success).toHaveBeenCalledWith('Removed Slack #alerts')
            expect(mockList).toHaveBeenCalledTimes(2)

            logic.unmount()
        })

        it('reloads from the server on delete failure so the list reflects actual state', async () => {
            mockList.mockReturnValue(onePage([MOCK_DESTINATION]))
            mockDelete.mockRejectedValue(new Error('network'))

            const logic = logsAlertNotificationLogic({ alertId: 'alert-1' })
            logic.mount()

            await expectLogic(logic).toFinishAllListeners()

            logic.actions.deleteExistingDestination(MOCK_DESTINATION, 'Slack #alerts')
            await expectLogic(logic).toFinishAllListeners()

            expect(lemonToast.error).toHaveBeenCalledWith(expect.stringContaining('Failed to remove Slack #alerts'))
            // List loader fired twice: once on mount, once after the error
            expect(mockList).toHaveBeenCalledTimes(2)

            logic.unmount()
        })
    })
})
