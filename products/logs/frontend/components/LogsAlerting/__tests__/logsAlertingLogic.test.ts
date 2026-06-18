import { expectLogic } from 'kea-test-utils'

import { lemonToast } from '@posthog/lemon-ui'

import { initKeaTests } from '~/test/init'

import { logsAlertsList, logsAlertsResetCreate } from 'products/logs/frontend/generated/api'

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

describe('logsAlertingLogic', () => {
    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
        mockList.mockResolvedValue({ results: [] } as any)
    })

    describe('resetAlert', () => {
        it('calls the reset endpoint, reloads the list, and surfaces a success toast', async () => {
            mockReset.mockResolvedValue(undefined as any)

            const logic = logsAlertingLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            mockList.mockClear()

            await expectLogic(logic, () => {
                logic.actions.resetAlert('alert-1')
            }).toFinishAllListeners()

            expect(mockReset).toHaveBeenCalledWith(expect.any(String), 'alert-1')
            expect(lemonToast.success).toHaveBeenCalledWith(expect.stringContaining('Alert reset'))
            // loadAlerts runs on mount + after the successful reset.
            expect(mockList).toHaveBeenCalledTimes(1)

            logic.unmount()
        })

        it('updates editingAlert optimistically when the reset target matches the open modal', async () => {
            const editing = { id: 'alert-1', name: 'broken', state: 'broken' } as any
            const updated = { id: 'alert-1', name: 'broken', state: 'ok' } as any
            mockReset.mockResolvedValue(updated)

            const logic = logsAlertingLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            logic.actions.setEditingAlert(editing)

            await expectLogic(logic, () => {
                logic.actions.resetAlert('alert-1')
            })
                .toFinishAllListeners()
                .toMatchValues({ editingAlert: updated })

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

    describe('createAlertAndOpen', () => {
        it('posts an empty draft and routes to detail', async () => {
            const mockCreate = require('products/logs/frontend/generated/api').logsAlertsCreate as jest.Mock
            mockCreate.mockResolvedValueOnce({ id: 'new-alert-id', name: 'Untitled alert' })
            const { router } = require('kea-router')
            const pushSpy = jest.spyOn(router.actions, 'push')

            const logic = logsAlertingLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.createAlertAndOpen()
            }).toFinishAllListeners()

            expect(mockCreate).toHaveBeenCalledWith(expect.any(String), { enabled: false })
            expect(pushSpy).toHaveBeenCalledWith('/logs/alerts/new-alert-id')

            pushSpy.mockRestore()
            logic.unmount()
        })

        it('shows an error toast on create failure', async () => {
            const mockCreate = require('products/logs/frontend/generated/api').logsAlertsCreate as jest.Mock
            mockCreate.mockRejectedValueOnce({ detail: 'Maximum number of alerts reached' })

            const logic = logsAlertingLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.createAlertAndOpen()
            }).toFinishAllListeners()

            expect(lemonToast.error).toHaveBeenCalledWith('Maximum number of alerts reached')
            logic.unmount()
        })
    })
})
