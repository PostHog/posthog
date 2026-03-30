import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'

import { initKeaTests } from '~/test/init'
import { HogFunctionType } from '~/types'

import { logsAlertNotificationLogic } from '../logsAlertNotificationLogic'
import { buildLogsAlertFilterConfig } from '../logsAlertUtils'

jest.mock('lib/api', () => ({
    __esModule: true,
    default: {
        hogFunctions: {
            list: jest.fn(),
            create: jest.fn(),
        },
    },
}))

jest.mock('lib/utils/deleteWithUndo', () => ({
    deleteWithUndo: jest.fn(),
}))

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: {
        success: jest.fn(),
        error: jest.fn(),
    },
}))

const mockApi = api as jest.Mocked<typeof api>
const mockDeleteWithUndo = deleteWithUndo as jest.MockedFunction<typeof deleteWithUndo>

const MOCK_HOG_FUNCTION = {
    id: 'hf-1',
    name: 'Test Notification',
    enabled: true,
    inputs: { channel: { value: 'C123' } },
} as unknown as HogFunctionType

describe('logsAlertNotificationLogic', () => {
    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
        ;(mockApi.hogFunctions.list as jest.Mock).mockResolvedValue({ results: [] })
    })

    describe('pending notifications', () => {
        it('adds a pending notification', async () => {
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

            logic.actions.addPendingNotification({
                type: 'webhook',
                webhookUrl: 'https://a.com',
            })
            logic.actions.addPendingNotification({
                type: 'webhook',
                webhookUrl: 'https://b.com',
            })

            logic.actions.removePendingNotification(0)

            expect(logic.values.pendingNotifications).toHaveLength(1)
            expect(logic.values.pendingNotifications[0]).toMatchObject({
                webhookUrl: 'https://b.com',
            })

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

        it('loads hog functions filtered by alert id', async () => {
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
            expect(logic.values.existingHogFunctions).toEqual([MOCK_HOG_FUNCTION])

            logic.unmount()
        })
    })

    describe('createPendingHogFunctions', () => {
        it('skips when no pending notifications', async () => {
            const logic = logsAlertNotificationLogic({ alertId: undefined })
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.createPendingHogFunctions('alert-1', 'My Alert')
            }).toFinishAllListeners()

            expect(mockApi.hogFunctions.create).not.toHaveBeenCalled()

            logic.unmount()
        })

        it('creates hog functions for each pending notification', async () => {
            ;(mockApi.hogFunctions.create as jest.Mock).mockResolvedValue(MOCK_HOG_FUNCTION)

            const logic = logsAlertNotificationLogic({ alertId: undefined })
            logic.mount()

            logic.actions.addPendingNotification({ type: 'webhook', webhookUrl: 'https://a.com' })
            logic.actions.addPendingNotification({ type: 'webhook', webhookUrl: 'https://b.com' })

            await expectLogic(logic, () => {
                logic.actions.createPendingHogFunctions('alert-1', 'My Alert')
            }).toFinishAllListeners()

            expect(mockApi.hogFunctions.create).toHaveBeenCalledTimes(2)
            expect(lemonToast.success).toHaveBeenCalledWith('2 notification destination(s) created.')
            expect(logic.values.pendingNotifications).toHaveLength(0)

            logic.unmount()
        })

        it('retains failed notifications on partial failure', async () => {
            ;(mockApi.hogFunctions.create as jest.Mock)
                .mockResolvedValueOnce(MOCK_HOG_FUNCTION)
                .mockRejectedValueOnce(new Error('API error'))

            const logic = logsAlertNotificationLogic({ alertId: undefined })
            logic.mount()

            logic.actions.addPendingNotification({ type: 'webhook', webhookUrl: 'https://ok.com' })
            logic.actions.addPendingNotification({ type: 'webhook', webhookUrl: 'https://fail.com' })

            await expectLogic(logic, () => {
                logic.actions.createPendingHogFunctions('alert-1', 'My Alert')
            }).toFinishAllListeners()

            expect(lemonToast.error).toHaveBeenCalledWith(expect.stringContaining('1 notification(s) failed to create'))
            expect(logic.values.pendingNotifications).toHaveLength(1)
            expect(logic.values.pendingNotifications[0]).toMatchObject({
                webhookUrl: 'https://fail.com',
            })

            logic.unmount()
        })
    })

    describe('deleteExistingHogFunction', () => {
        it('optimistically removes from state and calls deleteWithUndo', async () => {
            ;(mockApi.hogFunctions.list as jest.Mock).mockResolvedValue({
                results: [MOCK_HOG_FUNCTION],
            })
            ;(mockDeleteWithUndo as jest.Mock).mockResolvedValue(undefined)

            const logic = logsAlertNotificationLogic({ alertId: 'alert-1' })
            logic.mount()

            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.existingHogFunctions).toHaveLength(1)

            logic.actions.deleteExistingHogFunction(MOCK_HOG_FUNCTION)

            // Optimistic removal happens immediately via reducer
            expect(logic.values.existingHogFunctions).toHaveLength(0)

            await expectLogic(logic).toFinishAllListeners()
            expect(mockDeleteWithUndo).toHaveBeenCalledWith(
                expect.objectContaining({
                    object: { id: MOCK_HOG_FUNCTION.id, name: MOCK_HOG_FUNCTION.name },
                })
            )

            logic.unmount()
        })
    })
})
