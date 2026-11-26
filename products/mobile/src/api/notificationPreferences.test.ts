import { apiJson } from './client'
import {
    DEFAULT_NOTIFICATION_PREFERENCES,
    getNotificationPreferences,
    setNotificationPreference,
} from './notificationPreferences'

jest.mock('./client', () => ({ apiJson: jest.fn() }))

describe('account notification preferences', () => {
    beforeEach(() => jest.resetAllMocks())

    test('older accounts default to receiving mobile notifications', async () => {
        jest.mocked(apiJson).mockResolvedValue({ notification_settings: {} })
        expect(await getNotificationPreferences()).toEqual(DEFAULT_NOTIFICATION_PREFERENCES)
    })

    test.each([false, true])('keeps legacy opt-outs while honoring an explicit Chat setting: %s', async (chat) => {
        jest.mocked(apiJson).mockResolvedValue({
            notification_settings: { mobile_push_tasks_enabled: false, mobile_push_chat_enabled: chat },
        })
        expect(await getNotificationPreferences()).toEqual({
            ...DEFAULT_NOTIFICATION_PREFERENCES,
            mobile_push_tasks_enabled: false,
            mobile_push_chat_enabled: chat,
            mobile_push_loops_enabled: false,
        })
    })

    test('updates only the changed account preference and reads the saved response', async () => {
        jest.mocked(apiJson).mockResolvedValue({ notification_settings: { mobile_push_tasks_enabled: false } })
        expect(await setNotificationPreference('mobile_push_tasks_enabled', false)).toEqual({
            ...DEFAULT_NOTIFICATION_PREFERENCES,
            mobile_push_tasks_enabled: false,
            mobile_push_chat_enabled: false,
            mobile_push_loops_enabled: false,
        })
        expect(apiJson).toHaveBeenCalledWith('/api/users/@me/', {
            method: 'PATCH',
            json: { notification_settings: { mobile_push_tasks_enabled: false } },
        })
    })
})
