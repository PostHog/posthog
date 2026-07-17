import { InitialPermissionModeEnumApi } from 'products/tasks/frontend/generated/api.schemas'

/** The permission modes exposed by the PostHog AI composer. */
export type PermissionMode =
    | typeof InitialPermissionModeEnumApi.BypassPermissions
    | typeof InitialPermissionModeEnumApi.AcceptEdits
    | typeof InitialPermissionModeEnumApi.Plan

export interface ComposerModeOption {
    value: PermissionMode
    label: string
    description: string
}

export const DEFAULT_COMPOSER_MODE: PermissionMode = InitialPermissionModeEnumApi.BypassPermissions

// Ordered for the Shift+Tab cycle and the picker.
export const MODE_OPTIONS: ComposerModeOption[] = [
    {
        value: InitialPermissionModeEnumApi.BypassPermissions,
        label: 'Auto',
        description:
            'Bypasses all permissions. Safe in the sandbox, but the agent can modify or delete data without asking.',
    },
    {
        value: InitialPermissionModeEnumApi.AcceptEdits,
        label: 'Accept edits',
        description:
            'Accepts file edits automatically. Bash commands and PostHog MCP tools that update or delete data still require approval.',
    },
    {
        value: InitialPermissionModeEnumApi.Plan,
        label: 'Plan',
        description:
            'Recommended for complex work such as research or implementation. Create a plan now, then execute it later.',
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
