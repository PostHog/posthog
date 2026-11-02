import { initKeaTests } from '~/test/init'

import { taskTurnNotificationLogic } from './taskTurnNotificationLogic'
import { toolStreamEventsLogic } from './toolStreamEventsLogic'

describe('taskTurnNotificationLogic', () => {
    let logic: ReturnType<typeof taskTurnNotificationLogic.build>
    const notificationMock = jest.fn()
    let playMock: jest.SpyInstance

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        playMock = jest.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined)
        notificationMock.mockClear()
        Object.defineProperty(window, 'Notification', {
            configurable: true,
            value: Object.assign(notificationMock, {
                permission: 'granted',
                requestPermission: jest.fn().mockResolvedValue('granted'),
            }),
        })
        logic = taskTurnNotificationLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    test.each([
        { name: 'away with sound and notification', hidden: true, sound: 'meep', browser: true, played: 1, shown: 1 },
        { name: 'watching the tab', hidden: false, sound: 'meep', browser: true, played: 0, shown: 0 },
        { name: 'away with everything off', hidden: true, sound: 'none', browser: false, played: 0, shown: 0 },
    ] as const)('alerts on a live turn end: $name', ({ hidden, sound, browser, played, shown }) => {
        jest.spyOn(document, 'visibilityState', 'get').mockReturnValue(hidden ? 'hidden' : 'visible')
        jest.spyOn(document, 'hasFocus').mockReturnValue(!hidden)
        logic.actions.setSound(sound)
        logic.actions.setBrowserNotificationsEnabled(browser)
        playMock.mockClear()

        toolStreamEventsLogic.actions.emitTurnCompleteEvent({ streamKey: 'run-1', taskId: 'task-1' })

        expect(playMock).toHaveBeenCalledTimes(played)
        expect(notificationMock).toHaveBeenCalledTimes(shown)
    })
})
