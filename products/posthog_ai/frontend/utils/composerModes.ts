import { InitialPermissionModeEnumApi } from 'products/tasks/frontend/generated/api.schemas'

/** The agent-server permission mode — mirrors `/code`'s execution modes one-to-one. */
export type PermissionMode = InitialPermissionModeEnumApi

export interface ComposerModeOption {
    value: PermissionMode
    label: string
    description: string
}

export const DEFAULT_COMPOSER_MODE: PermissionMode = InitialPermissionModeEnumApi.Auto

// Ordered for the `shift+tab` cycle and the dropdown; mirrors `/code`'s `availableModes`.
export const MODE_OPTIONS: ComposerModeOption[] = [
    {
        value: InitialPermissionModeEnumApi.Auto,
        label: 'Auto',
        description: 'Approve or deny permission prompts automatically',
    },
    { value: InitialPermissionModeEnumApi.Default, label: 'Default', description: 'Prompt before edits and commands' },
    {
        value: InitialPermissionModeEnumApi.AcceptEdits,
        label: 'Accept edits',
        description: 'Auto-accept file edits; still prompt for commands',
    },
    {
        value: InitialPermissionModeEnumApi.Plan,
        label: 'Plan',
        description: 'Read-only planning — the agent proposes a plan before acting',
    },
    {
        value: InitialPermissionModeEnumApi.BypassPermissions,
        label: 'Bypass permissions',
        description: 'Auto-accept everything — no prompts',
    },
]

export function getModeOption(mode: string | null | undefined): ComposerModeOption | undefined {
    return MODE_OPTIONS.find((option) => option.value === mode)
}

export function getModeLabel(mode: string | null | undefined): string {
    return getModeOption(mode)?.label ?? 'Mode'
}

// Advance to the next mode, wrapping around. Port of `/code`'s `cycleModeOption`. An unknown `current`
// (null/undefined or a value not in the set) resets to the default so the cycle stays predictable.
export function cycleMode(current: string | null | undefined): PermissionMode {
    const order = MODE_OPTIONS.map((option) => option.value)
    const index = order.indexOf(current as PermissionMode)
    if (index === -1) {
        return DEFAULT_COMPOSER_MODE
    }
    return order[(index + 1) % order.length]
}
