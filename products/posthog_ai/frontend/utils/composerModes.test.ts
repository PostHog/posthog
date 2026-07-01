import { InitialPermissionModeEnumApi } from 'products/tasks/frontend/generated/api.schemas'

import { cycleMode, DEFAULT_COMPOSER_MODE } from './composerModes'

describe('composerModes', () => {
    // The `shift+tab` cycle: advances through every mode and wraps back to the first, so no mode is
    // unreachable and the last one loops around.
    it.each([
        [InitialPermissionModeEnumApi.Auto, InitialPermissionModeEnumApi.Default],
        [InitialPermissionModeEnumApi.Default, InitialPermissionModeEnumApi.AcceptEdits],
        [InitialPermissionModeEnumApi.AcceptEdits, InitialPermissionModeEnumApi.Plan],
        [InitialPermissionModeEnumApi.Plan, InitialPermissionModeEnumApi.BypassPermissions],
        [InitialPermissionModeEnumApi.BypassPermissions, InitialPermissionModeEnumApi.Auto],
    ])('cycleMode(%s) → %s', (current, next) => {
        expect(cycleMode(current)).toBe(next)
    })

    it.each([[null], [undefined], ['not-a-mode']])('cycleMode(%s) resets to the default', (current) => {
        expect(cycleMode(current)).toBe(DEFAULT_COMPOSER_MODE)
    })
})
