import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'
import type { UserType } from '~/types'

import { debugLogsLogic } from './debugLogsLogic'

describe('debugLogsLogic', () => {
    let logic: ReturnType<typeof debugLogsLogic.build>

    function setup({ user, isDev }: { user: Partial<UserType>; isDev: boolean }): void {
        userLogic.mount()
        userLogic.actions.loadUserSuccess({
            ...MOCK_DEFAULT_USER,
            is_staff: false,
            is_impersonated: false,
            ...user,
        } as UserType)
        preflightLogic.mount()
        preflightLogic.actions.loadPreflightSuccess({ is_debug: isDev } as any)
        logic = debugLogsLogic()
        logic.mount()
    }

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('defaults to showing debug logs for staff with no stored preference', () => {
        setup({ user: { is_staff: true }, isDev: false })
        expect(logic.values.debugLogsEnabled).toBe(true)
        expect(logic.values.showDebugLogs).toBe(true)
    })

    it.each([
        { name: 'staff, toggle on', user: { is_staff: true }, isDev: false, enabled: true, expected: true },
        { name: 'staff, toggle off', user: { is_staff: true }, isDev: false, enabled: false, expected: false },
        { name: 'local dev, toggle on', user: {}, isDev: true, enabled: true, expected: true },
        { name: 'local dev, toggle off', user: {}, isDev: true, enabled: false, expected: false },
        {
            name: 'impersonation overrides toggle off',
            user: { is_impersonated: true },
            isDev: false,
            enabled: false,
            expected: true,
        },
        { name: 'non-staff, non-dev never sees', user: {}, isDev: false, enabled: true, expected: false },
    ])('showDebugLogs — $name', ({ user, isDev, enabled, expected }) => {
        setup({ user, isDev })
        logic.actions.setDebugLogsEnabled(enabled)
        expect(logic.values.showDebugLogs).toBe(expected)
    })
})
