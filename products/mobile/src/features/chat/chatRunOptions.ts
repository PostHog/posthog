import type { ModelChoiceApi, PermissionModeApi, ResolvedAiRunDefaultsApi, RuntimeAdapterApi } from '@/api/tasks'

import {
    DEFAULT_RUN_OPTIONS,
    effectiveRuntimeAdapter,
    isPermissionMode,
    isReasoningEffort,
    modelSummary,
    type PinnedModel,
    type RunOptions,
    resolveModeForRuntimeAdapter,
} from '../handoff/runOptions'
import type { SessionRunConfig } from './session/sessionRun'

/** The hand-off's run options without a branch, because a chat has no repository. */
export type ChatRunOptions = Pick<RunOptions, 'model' | 'permissionMode'>

export const DEFAULT_CHAT_RUN_OPTIONS: ChatRunOptions = {
    model: DEFAULT_RUN_OPTIONS.model,
    permissionMode: DEFAULT_RUN_OPTIONS.permissionMode,
}

/** `runtimeAdapter` is the harness the run lands on, so a mode from the other harness is mapped onto it. */
export type ChatRunOptionsAction =
    | { type: 'model'; model: PinnedModel | 'default'; runtimeAdapter: RuntimeAdapterApi }
    | { type: 'mode'; mode: PermissionModeApi }
    | { type: 'seed'; options: ChatRunOptions }
    | { type: 'reset' }

function sameOptions(a: ChatRunOptions, b: ChatRunOptions): boolean {
    if (a.permissionMode !== b.permissionMode) {
        return false
    }
    if (a.model === 'default' || b.model === 'default') {
        return a.model === b.model
    }
    return (
        a.model.runtimeAdapter === b.model.runtimeAdapter &&
        a.model.model === b.model.model &&
        a.model.reasoningEffort === b.model.reasoningEffort
    )
}

export function chatRunOptionsReducer(state: ChatRunOptions, action: ChatRunOptionsAction): ChatRunOptions {
    switch (action.type) {
        case 'model':
            return {
                model: action.model,
                permissionMode: resolveModeForRuntimeAdapter(action.runtimeAdapter, state.permissionMode),
            }
        case 'mode':
            return state.permissionMode === action.mode ? state : { ...state, permissionMode: action.mode }
        case 'seed':
            return sameOptions(state, action.options) ? state : action.options
        case 'reset':
            return DEFAULT_CHAT_RUN_OPTIONS
    }
}

export function chatRunOptionsFromConfig(config: SessionRunConfig, pinModel: boolean): ChatRunOptions {
    const { runtimeAdapter, model, reasoningEffort, permissionMode } = config
    return {
        model:
            pinModel && runtimeAdapter && model
                ? {
                      runtimeAdapter,
                      model,
                      reasoningEffort: reasoningEffort && isReasoningEffort(reasoningEffort) ? reasoningEffort : null,
                  }
                : 'default',
        permissionMode:
            permissionMode && isPermissionMode(permissionMode)
                ? permissionMode
                : DEFAULT_CHAT_RUN_OPTIONS.permissionMode,
    }
}

/**
 * The harness the next message runs on. `runAdapter` is the open session's harness, which an untouched model keeps
 * because a live run cannot switch harness.
 */
export function chatRuntimeAdapter(
    options: ChatRunOptions,
    defaults: ResolvedAiRunDefaultsApi | undefined,
    runAdapter?: RuntimeAdapterApi | null
): RuntimeAdapterApi {
    if (options.model === 'default' && runAdapter) {
        return runAdapter
    }
    return effectiveRuntimeAdapter({ ...options, branch: '' }, defaults)
}

/** Defaults that arrive after a pick can move the run to the other harness, so this is the mode the run sends. */
export function chatPermissionMode(
    options: ChatRunOptions,
    defaults: ResolvedAiRunDefaultsApi | undefined,
    runAdapter?: RuntimeAdapterApi | null
): PermissionModeApi {
    return resolveModeForRuntimeAdapter(chatRuntimeAdapter(options, defaults, runAdapter), options.permissionMode)
}

/** The composer chip has room for little, so it drops the "Claude" every Claude Code model name starts with. */
export function chipModelLabel(catalogue: readonly ModelChoiceApi[], model: ChatRunOptions['model']): string {
    if (model === 'default') {
        return 'Default'
    }
    return modelSummary(catalogue, model.model, model.reasoningEffort).replace(/^Claude /, '')
}
