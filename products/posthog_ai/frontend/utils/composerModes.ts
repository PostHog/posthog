import { InitialPermissionModeEnumApi } from 'products/tasks/frontend/generated/api.schemas'

/** The permission modes exposed by the PostHog AI composer. */
export type PermissionMode =
    | typeof InitialPermissionModeEnumApi.Auto
    | typeof InitialPermissionModeEnumApi.BypassPermissions
    | typeof InitialPermissionModeEnumApi.Plan

export interface ComposerModeOption {
    value: PermissionMode
    label: string
    description: string
}

export const DEFAULT_COMPOSER_MODE: PermissionMode = InitialPermissionModeEnumApi.Auto

// Ordered for the Shift+Tab cycle and the picker.
export const MODE_OPTIONS: ComposerModeOption[] = [
    {
        value: InitialPermissionModeEnumApi.Auto,
        label: 'Auto',
        description:
            'Accepts file edits and shell commands automatically. Always asks before PostHog tools that change live data. Creating or publishing content asks only while you watch the run.',
    },
    {
        value: InitialPermissionModeEnumApi.BypassPermissions,
        label: 'Full auto',
        description: 'Never asks. The agent can change or delete live data on its own.',
    },
    {
        value: InitialPermissionModeEnumApi.Plan,
        label: 'Plan',
        description: 'Plans the work first. Nothing runs until you approve the plan.',
    },
]

// Modes retired from the picker resolve to their closest current equivalent, so persisted
// selections and runs started before the retirement keep resolving to a real option.
const LEGACY_MODE_ALIASES: Record<string, PermissionMode> = {
    [InitialPermissionModeEnumApi.AcceptEdits]: InitialPermissionModeEnumApi.Auto,
}

export function getModeOption(mode: string | null | undefined): ComposerModeOption | undefined {
    if (mode == null) {
        return undefined
    }
    const normalized = LEGACY_MODE_ALIASES[mode] ?? mode
    return MODE_OPTIONS.find((option) => option.value === normalized)
}

export function getModeLabel(mode: string | null | undefined): string {
    return getModeOption(mode)?.label ?? 'Mode'
}

// Advance to the next mode, wrapping around. Port of `/code`'s `cycleModeOption`. An unknown `current`
// (null/undefined or a value not in the set) resets to the default so the cycle stays predictable.
export function cycleMode(current: string | null | undefined): PermissionMode {
    const order = MODE_OPTIONS.map((option) => option.value)
    const index = order.indexOf((getModeOption(current)?.value ?? current) as PermissionMode)
    if (index === -1) {
        return DEFAULT_COMPOSER_MODE
    }
    return order[(index + 1) % order.length]
}
