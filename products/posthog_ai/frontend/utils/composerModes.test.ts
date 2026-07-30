import { InitialPermissionModeEnumApi } from 'products/tasks/frontend/generated/api.schemas'

import { cycleMode, DEFAULT_COMPOSER_MODE, getModeOption } from './composerModes'

describe('composerModes', () => {
    // The `shift+tab` cycle: advances through every mode and wraps back to the first, so no mode is
    // unreachable and the last one loops around.
    it.each([
        [InitialPermissionModeEnumApi.Auto, InitialPermissionModeEnumApi.BypassPermissions],
        [InitialPermissionModeEnumApi.BypassPermissions, InitialPermissionModeEnumApi.Plan],
        [InitialPermissionModeEnumApi.Plan, InitialPermissionModeEnumApi.Auto],
    ])('cycleMode(%s) → %s', (current, next) => {
        expect(cycleMode(current)).toBe(next)
    })

    it.each([[null], [undefined], ['not-a-mode']])('cycleMode(%s) resets to the default', (current) => {
        expect(cycleMode(current)).toBe(DEFAULT_COMPOSER_MODE)
    })

    // Persisted selections and older runs still carry the retired acceptEdits mode — it must keep
    // resolving to a real option instead of falling back to the bare 'Mode' trigger.
    it('resolves legacy acceptEdits to the auto option', () => {
        expect(getModeOption(InitialPermissionModeEnumApi.AcceptEdits)?.value).toBe(InitialPermissionModeEnumApi.Auto)
        expect(cycleMode(InitialPermissionModeEnumApi.AcceptEdits)).toBe(InitialPermissionModeEnumApi.BypassPermissions)
    })
})
