import {
    CodexTaskRunCreateSchemaInitialPermissionModeEnumApi,
    InitialPermissionModeEnumApi,
    RuntimeAdapterEnumApi,
} from 'products/tasks/frontend/generated/api.schemas'

/**
 * A permission mode in either runtime's vocabulary. Claude and Codex name these differently and each
 * validates against its own set, so the picker offers the modes of the harness the run will use rather
 * than one blended list. Mirrors the desktop app's `ExecutionMode`.
 */
export type PermissionMode = InitialPermissionModeEnumApi | CodexTaskRunCreateSchemaInitialPermissionModeEnumApi

export interface ComposerModeOption {
    value: PermissionMode
    label: string
    description: string
}

/** Every mode either runtime offers, described once. `plan` and `auto` are shared. */
export const MODE_OPTIONS: ComposerModeOption[] = [
    {
        value: InitialPermissionModeEnumApi.Default,
        label: 'Default',
        description: 'Asks before anything that changes files, runs commands, or touches live data.',
    },
    {
        value: InitialPermissionModeEnumApi.AcceptEdits,
        label: 'Accept edits',
        description: 'Accepts file edits automatically. Still asks before shell commands and live data.',
    },
    {
        value: InitialPermissionModeEnumApi.Plan,
        label: 'Plan',
        description: 'Plans the work first. Nothing runs until you approve the plan.',
    },
    {
        value: CodexTaskRunCreateSchemaInitialPermissionModeEnumApi.ReadOnly,
        label: 'Read only',
        description: 'Inspects the repo and answers, but changes nothing.',
    },
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
        value: CodexTaskRunCreateSchemaInitialPermissionModeEnumApi.FullAccess,
        label: 'Full access',
        description: 'Never asks. The agent can change or delete live data on its own.',
    },
]

// Each runtime's own modes, in the order its picker shows them — the same sets and order the desktop app
// uses, so a mode means the same thing and sits in the same place on both surfaces.
const CLAUDE_MODES: PermissionMode[] = [
    InitialPermissionModeEnumApi.Default,
    InitialPermissionModeEnumApi.AcceptEdits,
    InitialPermissionModeEnumApi.Plan,
    InitialPermissionModeEnumApi.BypassPermissions,
    InitialPermissionModeEnumApi.Auto,
]

const CODEX_MODES: PermissionMode[] = [
    CodexTaskRunCreateSchemaInitialPermissionModeEnumApi.Plan,
    CodexTaskRunCreateSchemaInitialPermissionModeEnumApi.ReadOnly,
    CodexTaskRunCreateSchemaInitialPermissionModeEnumApi.Auto,
    CodexTaskRunCreateSchemaInitialPermissionModeEnumApi.FullAccess,
]

// Hidden from the picker, exactly as the desktop app hides them: its `allowBypassPermissions` setting
// defaults to off and filters these two out of the menu (ModeSelector.tsx). Uncomment them here once the
// web surface has the equivalent setting. They stay in the vocabularies above on purpose — a run already
// launched on one must still render its label and coerce across runtimes, it just can't be picked.
const GATED_MODES: PermissionMode[] = [
    InitialPermissionModeEnumApi.BypassPermissions,
    CodexTaskRunCreateSchemaInitialPermissionModeEnumApi.FullAccess,
]

/** The modes the picker offers for a runtime — its vocabulary minus anything gated. */
export function getModesForRuntimeAdapter(runtimeAdapter: string): PermissionMode[] {
    return getRuntimeModeVocabulary(runtimeAdapter).filter((mode) => !GATED_MODES.includes(mode))
}

/** Every mode a runtime accepts, gated or not — what coercion and label lookup resolve against. */
export function getRuntimeModeVocabulary(runtimeAdapter: string): PermissionMode[] {
    return runtimeAdapter === RuntimeAdapterEnumApi.Codex ? CODEX_MODES : CLAUDE_MODES
}

/** Both runtimes open on Auto — the agent gets to work instead of waiting on a plan approval. */
export function getDefaultModeForRuntimeAdapter(runtimeAdapter: string): PermissionMode {
    return runtimeAdapter === RuntimeAdapterEnumApi.Codex
        ? CodexTaskRunCreateSchemaInitialPermissionModeEnumApi.Auto
        : InitialPermissionModeEnumApi.Auto
}

export const DEFAULT_COMPOSER_MODE: PermissionMode = getDefaultModeForRuntimeAdapter(RuntimeAdapterEnumApi.Claude)

// A mode that only exists on the other runtime maps to the nearest ceiling on this one, so switching
// harness — or opening a run started from another surface — never silently loosens what the agent may do.
const CODEX_FALLBACKS: Record<string, PermissionMode> = {
    [InitialPermissionModeEnumApi.Default]: CodexTaskRunCreateSchemaInitialPermissionModeEnumApi.Auto,
    [InitialPermissionModeEnumApi.AcceptEdits]: CodexTaskRunCreateSchemaInitialPermissionModeEnumApi.Auto,
    [InitialPermissionModeEnumApi.BypassPermissions]: CodexTaskRunCreateSchemaInitialPermissionModeEnumApi.FullAccess,
}

const CLAUDE_FALLBACKS: Record<string, PermissionMode> = {
    [CodexTaskRunCreateSchemaInitialPermissionModeEnumApi.ReadOnly]: InitialPermissionModeEnumApi.Plan,
    [CodexTaskRunCreateSchemaInitialPermissionModeEnumApi.FullAccess]: InitialPermissionModeEnumApi.BypassPermissions,
}

/** Coerce a mode into the vocabulary the given runtime validates against. */
export function resolveModeForRuntimeAdapter(runtimeAdapter: string, mode: PermissionMode): PermissionMode {
    const native = getRuntimeModeVocabulary(runtimeAdapter)
    if (native.includes(mode)) {
        return mode
    }
    if (runtimeAdapter === RuntimeAdapterEnumApi.Codex) {
        return CODEX_FALLBACKS[mode] ?? CodexTaskRunCreateSchemaInitialPermissionModeEnumApi.Auto
    }
    return CLAUDE_FALLBACKS[mode] ?? InitialPermissionModeEnumApi.Default
}

export function getModeOption(mode: string | null | undefined): ComposerModeOption | undefined {
    return mode == null ? undefined : MODE_OPTIONS.find((option) => option.value === mode)
}

export function getModeLabel(mode: string | null | undefined): string {
    return getModeOption(mode)?.label ?? 'Mode'
}

// Advance to the next mode of the run's own runtime, wrapping around. Port of `/code`'s `cycleModeOption`.
// A mode the runtime doesn't offer — carried from the other harness, or from a run started elsewhere — is
// coerced onto this runtime first, so the cycle always starts from something the runtime accepts.
export function cycleMode(runtimeAdapter: string, current: string | null | undefined): PermissionMode {
    const order = getModesForRuntimeAdapter(runtimeAdapter)
    const from = resolveModeForRuntimeAdapter(runtimeAdapter, (current ?? '') as PermissionMode)
    const index = order.indexOf(from)
    return index === -1 ? order[0] : order[(index + 1) % order.length]
}
