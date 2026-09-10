import {
    CodexTaskRunCreateSchemaInitialPermissionModeEnumApi as CodexMode,
    InitialPermissionModeEnumApi as ClaudeMode,
    RuntimeAdapterEnumApi,
} from 'products/tasks/frontend/generated/api.schemas'

import {
    cycleMode,
    getDefaultModeForRuntimeAdapter,
    getModesForRuntimeAdapter,
    resolveModeForRuntimeAdapter,
} from './composerModes'

describe('composerModes', () => {
    // Each runtime validates against its own vocabulary, so the picker must offer that runtime's modes —
    // sending Claude's `bypassPermissions` to Codex, or Codex's `read-only` to Claude, is rejected.
    it.each([
        [RuntimeAdapterEnumApi.Claude, ClaudeMode.AcceptEdits, true],
        [RuntimeAdapterEnumApi.Claude, CodexMode.ReadOnly, false],
        [RuntimeAdapterEnumApi.Codex, CodexMode.ReadOnly, true],
        [RuntimeAdapterEnumApi.Codex, ClaudeMode.AcceptEdits, false],
    ])('%s offers %s: %s', (adapter, mode, offered) => {
        expect(getModesForRuntimeAdapter(adapter).includes(mode)).toBe(offered)
    })

    // Never-ask modes stay out of the picker while the web surface has no equivalent of desktop's
    // `allowBypassPermissions` setting — but each runtime still accepts one, so a run already launched on
    // it keeps resolving instead of degrading.
    it.each([
        [RuntimeAdapterEnumApi.Claude, ClaudeMode.BypassPermissions],
        [RuntimeAdapterEnumApi.Codex, CodexMode.FullAccess],
    ])('%s gates %s out of the picker but still accepts it', (adapter, mode) => {
        expect(getModesForRuntimeAdapter(adapter)).not.toContain(mode)
        expect(resolveModeForRuntimeAdapter(adapter, mode)).toBe(mode)
    })

    // A mode carried across harnesses — switching model, or opening a run started from another surface —
    // must land on the nearest ceiling rather than silently loosening what the agent may do.
    it.each([
        [RuntimeAdapterEnumApi.Codex, ClaudeMode.BypassPermissions, CodexMode.FullAccess],
        [RuntimeAdapterEnumApi.Codex, ClaudeMode.AcceptEdits, CodexMode.Auto],
        [RuntimeAdapterEnumApi.Codex, ClaudeMode.Default, CodexMode.Auto],
        [RuntimeAdapterEnumApi.Claude, CodexMode.ReadOnly, ClaudeMode.Plan],
        [RuntimeAdapterEnumApi.Claude, CodexMode.FullAccess, ClaudeMode.BypassPermissions],
        // Shared on both, so it passes straight through.
        [RuntimeAdapterEnumApi.Codex, ClaudeMode.Plan, ClaudeMode.Plan],
    ])('%s coerces %s → %s', (adapter, mode, expected) => {
        expect(resolveModeForRuntimeAdapter(adapter, mode)).toBe(expected)
    })

    // Both runtimes open on Auto.
    it.each([
        [RuntimeAdapterEnumApi.Claude, ClaudeMode.Auto],
        [RuntimeAdapterEnumApi.Codex, CodexMode.Auto],
    ])('%s defaults to %s', (adapter, expected) => {
        expect(getDefaultModeForRuntimeAdapter(adapter)).toBe(expected)
    })

    // The `shift+tab` cycle stays inside the run's own runtime and wraps, so no mode is unreachable and
    // the cycle can never hand the runtime a mode it rejects.
    it('cycles within the runtime and wraps around', () => {
        const codexModes = getModesForRuntimeAdapter(RuntimeAdapterEnumApi.Codex)
        const seen = codexModes.map((_, i) =>
            codexModes.reduce((mode) => mode, cycleMode(RuntimeAdapterEnumApi.Codex, codexModes[i]))
        )
        expect(seen).toEqual([...codexModes.slice(1), codexModes[0]])
    })

    // An unknown or absent mode is coerced onto the runtime first, so the cycle starts somewhere real.
    it.each([[null], [undefined], ['not-a-mode']])('cycleMode(codex, %s) still yields a codex mode', (current) => {
        expect(getModesForRuntimeAdapter(RuntimeAdapterEnumApi.Codex)).toContain(
            cycleMode(RuntimeAdapterEnumApi.Codex, current)
        )
    })
})
