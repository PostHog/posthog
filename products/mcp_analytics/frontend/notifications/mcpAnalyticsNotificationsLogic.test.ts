import { expectLogic } from 'kea-test-utils'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'

import { initKeaTests } from '~/test/init'
import { HogFunctionType } from '~/types'

import { getMCPNotificationUseCase, mcpAnalyticsNotificationsLogic } from './mcpAnalyticsNotificationsLogic'

jest.mock('lib/utils/deleteWithUndo', () => ({
    deleteWithUndo: jest.fn(),
}))

const mockedDeleteWithUndo = jest.mocked(deleteWithUndo)

function makeNotification(id: string, overrides: Partial<HogFunctionType> = {}): HogFunctionType {
    return {
        id,
        name: `Notification ${id}`,
        enabled: false,
        deleted: false,
        filters: { events: [{ id: '$mcp_tool_call', type: 'events' }] },
        inputs: {},
        icon_url: null,
        ...overrides,
    } as HogFunctionType
}

function createDeferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
    let resolve!: (value: T) => void
    const promise = new Promise<T>((promiseResolve) => {
        resolve = promiseResolve
    })
    return { promise, resolve }
}

describe('mcpAnalyticsNotificationsLogic', () => {
    let logic: ReturnType<typeof mcpAnalyticsNotificationsLogic.build>
    let listSpy: jest.SpyInstance

    beforeEach(async () => {
        initKeaTests()
        listSpy = jest.spyOn(api.hogFunctions, 'list').mockResolvedValue({
            count: 2,
            next: null,
            previous: null,
            results: [],
        })
        jest.spyOn(api.hogFunctions, 'update').mockResolvedValue(makeNotification('updated'))
        jest.spyOn(lemonToast, 'warning').mockImplementation(() => 'toast-id')
        mockedDeleteWithUndo.mockReset().mockResolvedValue()

        logic = mcpAnalyticsNotificationsLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    test.each([
        ['$mcp_missing_capability', 'missing-capability'],
        ['$mcp_tool_call', 'tool-error'],
        ['$pageview', null],
    ])('classifies the %s event as %s', (eventId, expected) => {
        expect(
            getMCPNotificationUseCase({
                filters: { events: [{ id: eventId, type: 'events' }] },
            })
        ).toBe(expected)
    })

    it('loads only a lightweight count when mounted', () => {
        expect(logic.values.notificationCount).toBe(2)
        expect(listSpy).toHaveBeenCalledTimes(1)
        expect(listSpy).toHaveBeenCalledWith(
            expect.objectContaining({
                limit: 1,
                types: ['destination'],
            })
        )
        expect(listSpy.mock.calls[0][0]).not.toHaveProperty('full')
    })

    it('keeps the fetched rows and warns when the list is truncated', async () => {
        const notifications = [makeNotification('a'), makeNotification('b')]
        listSpy.mockReset().mockResolvedValue({
            count: 501,
            next: 'http://localhost/api/projects/1/hog_functions/?limit=500&offset=500',
            previous: null,
            results: notifications,
        })

        logic.actions.loadNotificationCountSuccess(501)

        await expectLogic(logic, () => logic.actions.loadNotifications())
            .toFinishAllListeners()
            .toMatchValues({
                notificationCount: 501,
                notifications,
                notificationsFailed: false,
                notificationsTruncated: true,
            })

        expect(listSpy).toHaveBeenCalledWith(expect.objectContaining({ full: true, limit: 500 }))
        expect(lemonToast.warning).toHaveBeenCalledWith(expect.stringContaining('first 500'))
    })

    it('blocks a second toggle and reconciles the first with the server response', async () => {
        const notification = makeNotification('toggle')
        const serverNotification = makeNotification('toggle', { enabled: false, name: 'Server name' })
        const updateDeferred = createDeferred<HogFunctionType>()
        const updateSpy = jest.spyOn(api.hogFunctions, 'update').mockReturnValue(updateDeferred.promise)
        logic.actions.loadNotificationsSuccess([notification])

        logic.actions.toggleNotificationEnabled(notification.id, true)

        expect(logic.values.pendingToggleIds).toEqual({ [notification.id]: true })
        expect(logic.values.notifications[0].enabled).toBe(true)

        logic.actions.toggleNotificationEnabled(notification.id, false)
        expect(updateSpy).toHaveBeenCalledTimes(1)

        updateDeferred.resolve(serverNotification)
        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({
                notifications: [serverNotification],
                pendingToggleIds: {},
            })
    })

    it('reloads server truth when an optimistic delete fails', async () => {
        const deletedNotification = makeNotification('delete')
        const concurrentlyUpdatedNotification = makeNotification('keep', { enabled: true })
        const serverNotification = makeNotification('server')
        const deleteDeferred = createDeferred<void>()
        mockedDeleteWithUndo.mockReturnValue(deleteDeferred.promise)
        listSpy.mockReset().mockResolvedValue({
            count: 2,
            next: null,
            previous: null,
            results: [concurrentlyUpdatedNotification, serverNotification],
        })
        logic.actions.loadNotificationsSuccess([deletedNotification, makeNotification('keep')])

        logic.actions.deleteNotification(deletedNotification)
        expect(logic.values.notifications).toEqual([makeNotification('keep')])

        logic.actions.loadNotificationsSuccess([concurrentlyUpdatedNotification])
        deleteDeferred.resolve()

        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({
                notifications: [concurrentlyUpdatedNotification, serverNotification],
            })
        expect(listSpy).toHaveBeenCalledWith(expect.objectContaining({ full: true }))
    })
})
