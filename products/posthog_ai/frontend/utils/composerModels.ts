import {
    ClaudeRuntimeAdapterEnumApi,
    type ClaudeTaskRunCreateSchemaApi,
    CodexRuntimeAdapterEnumApi,
    type CodexTaskRunCreateSchemaApi,
    ReasoningEffortEnumApi,
    RuntimeAdapterEnumApi,
} from 'products/tasks/frontend/generated/api.schemas'

import { type PermissionMode, toCodexPermissionMode } from './composerModes'

export type ComposerRuntimeAdapter = (typeof RuntimeAdapterEnumApi)[keyof typeof RuntimeAdapterEnumApi]

// The harness each runtime runs, named the way the desktop app names it.
export const RUNTIME_ADAPTER_LABELS: Record<ComposerRuntimeAdapter, string> = {
    [RuntimeAdapterEnumApi.Claude]: 'Claude Code',
    [RuntimeAdapterEnumApi.Codex]: 'Codex',
}

export interface ComposerModelOption {
    value: string
    label: string
    /** The runtime the model has to be launched on — the harness is picked from the model, not chosen separately. */
    runtimeAdapter: ComposerRuntimeAdapter
}

export interface ComposerEffortOption {
    value: ReasoningEffortEnumApi
    label: string
}

// Mirrors the backend's tested catalogs (CLAUDE_REASONING_EFFORTS_BY_MODEL and CODEX_MODELS in
// products/tasks/backend/temporal/process_task/utils.py). Add new models here as they ship.
export const COMPOSER_MODELS: ComposerModelOption[] = [
    { value: 'claude-sonnet-5', label: 'Claude Sonnet 5', runtimeAdapter: RuntimeAdapterEnumApi.Claude },
    { value: 'claude-opus-5', label: 'Claude Opus 5', runtimeAdapter: RuntimeAdapterEnumApi.Claude },
    { value: 'claude-opus-4-8', label: 'Claude Opus 4.8', runtimeAdapter: RuntimeAdapterEnumApi.Claude },
    { value: 'gpt-5.6-luna', label: 'GPT-5.6 Luna', runtimeAdapter: RuntimeAdapterEnumApi.Codex },
    { value: 'gpt-5.6-terra', label: 'GPT-5.6 Terra', runtimeAdapter: RuntimeAdapterEnumApi.Codex },
    { value: 'gpt-5.6-sol', label: 'GPT-5.6 Sol', runtimeAdapter: RuntimeAdapterEnumApi.Codex },
]

export const DEFAULT_COMPOSER_MODEL = 'claude-sonnet-5'
export const DEFAULT_COMPOSER_EFFORT: ReasoningEffortEnumApi = ReasoningEffortEnumApi.High

const EFFORT_LABELS: Record<ReasoningEffortEnumApi, string> = {
    [ReasoningEffortEnumApi.Low]: 'Low',
    [ReasoningEffortEnumApi.Medium]: 'Medium',
    [ReasoningEffortEnumApi.High]: 'High',
    [ReasoningEffortEnumApi.Xhigh]: 'Extra high',
    [ReasoningEffortEnumApi.Max]: 'Max',
    [ReasoningEffortEnumApi.Ultracode]: 'Ultracode',
}

// Mirrors the backend's per-model effort sets (CLAUDE_REASONING_EFFORTS_BY_MODEL and
// CODEX_MAX_REASONING_MODELS in products/tasks/backend/temporal/process_task/utils.py): xhigh/max/ultracode
// are only offered for models that support them.
const EFFORTS_BY_MODEL: Record<string, ReasoningEffortEnumApi[]> = {
    'claude-opus-4-8': [
        ReasoningEffortEnumApi.Low,
        ReasoningEffortEnumApi.Medium,
        ReasoningEffortEnumApi.High,
        ReasoningEffortEnumApi.Xhigh,
        ReasoningEffortEnumApi.Max,
        ReasoningEffortEnumApi.Ultracode,
    ],
    'claude-opus-5': [
        ReasoningEffortEnumApi.Low,
        ReasoningEffortEnumApi.Medium,
        ReasoningEffortEnumApi.High,
        ReasoningEffortEnumApi.Xhigh,
        ReasoningEffortEnumApi.Max,
        ReasoningEffortEnumApi.Ultracode,
    ],
    'claude-sonnet-5': [
        ReasoningEffortEnumApi.Low,
        ReasoningEffortEnumApi.Medium,
        ReasoningEffortEnumApi.High,
        ReasoningEffortEnumApi.Xhigh,
        ReasoningEffortEnumApi.Max,
        ReasoningEffortEnumApi.Ultracode,
    ],
    'gpt-5.6-luna': [
        ReasoningEffortEnumApi.Low,
        ReasoningEffortEnumApi.Medium,
        ReasoningEffortEnumApi.High,
        ReasoningEffortEnumApi.Xhigh,
        ReasoningEffortEnumApi.Max,
    ],
    'gpt-5.6-terra': [
        ReasoningEffortEnumApi.Low,
        ReasoningEffortEnumApi.Medium,
        ReasoningEffortEnumApi.High,
        ReasoningEffortEnumApi.Xhigh,
        ReasoningEffortEnumApi.Max,
    ],
    'gpt-5.6-sol': [
        ReasoningEffortEnumApi.Low,
        ReasoningEffortEnumApi.Medium,
        ReasoningEffortEnumApi.High,
        ReasoningEffortEnumApi.Xhigh,
        ReasoningEffortEnumApi.Max,
    ],
}

const FALLBACK_EFFORTS: ReasoningEffortEnumApi[] = [
    ReasoningEffortEnumApi.Low,
    ReasoningEffortEnumApi.Medium,
    ReasoningEffortEnumApi.High,
]

export function getEffortsForModel(model: string | null | undefined): ComposerEffortOption[] {
    const efforts = (model && EFFORTS_BY_MODEL[model]) || FALLBACK_EFFORTS
    return efforts.map((value) => ({ value, label: EFFORT_LABELS[value] }))
}

export function getModelLabel(model: string | null | undefined): string {
    return COMPOSER_MODELS.find((option) => option.value === model)?.label ?? model ?? 'Model'
}

// An unknown model resolves to Claude — the historical default, and the runtime every run predating the
// Codex lineup was launched on.
export function getRuntimeAdapterForModel(model: string | null | undefined): ComposerRuntimeAdapter {
    return COMPOSER_MODELS.find((option) => option.value === model)?.runtimeAdapter ?? RuntimeAdapterEnumApi.Claude
}

export function getModelsForRuntimeAdapter(adapter: ComposerRuntimeAdapter): ComposerModelOption[] {
    return COMPOSER_MODELS.filter((option) => option.runtimeAdapter === adapter)
}

export interface ComposerModelGroup {
    adapter: ComposerRuntimeAdapter
    label: string
    models: ComposerModelOption[]
}

/** Split a model list into per-harness sections for the picker, keeping the lineup's order. */
export function groupModelsByRuntimeAdapter(models: ComposerModelOption[]): ComposerModelGroup[] {
    const groups: ComposerModelGroup[] = []
    for (const model of models) {
        const group = groups.find((candidate) => candidate.adapter === model.runtimeAdapter)
        if (group) {
            group.models.push(model)
        } else {
            groups.push({
                adapter: model.runtimeAdapter,
                label: RUNTIME_ADAPTER_LABELS[model.runtimeAdapter],
                models: [model],
            })
        }
    }
    return groups
}

/** The runtime half of a run-create request — the two adapters take different permission-mode vocabularies. */
export type ComposerRuntimeSelection =
    | Pick<ClaudeTaskRunCreateSchemaApi, 'runtime_adapter' | 'model' | 'reasoning_effort' | 'initial_permission_mode'>
    | Pick<CodexTaskRunCreateSchemaApi, 'runtime_adapter' | 'model' | 'reasoning_effort' | 'initial_permission_mode'>

/** Derive the runtime a run launches on from the picked model, clamping effort and mode to what it accepts. */
export function buildRuntimeSelection(
    model: string,
    effort: string | null | undefined,
    mode: PermissionMode
): ComposerRuntimeSelection {
    const reasoningEffort = resolveEffortForModel(effort, model)
    if (getRuntimeAdapterForModel(model) === RuntimeAdapterEnumApi.Codex) {
        return {
            runtime_adapter: CodexRuntimeAdapterEnumApi.Codex,
            model,
            reasoning_effort: reasoningEffort,
            initial_permission_mode: toCodexPermissionMode(mode),
        }
    }
    return {
        runtime_adapter: ClaudeRuntimeAdapterEnumApi.Claude,
        model,
        reasoning_effort: reasoningEffort,
        initial_permission_mode: mode,
    }
}

export function getEffortLabel(effort: string | null | undefined): string {
    return effort ? (EFFORT_LABELS[effort as ReasoningEffortEnumApi] ?? effort) : 'Effort'
}

// Clamp an effort to one the selected model actually supports — the new-run path can inherit an effort from a
// previous run on a different model (e.g. `max` carried over to Sonnet, which only offers low/medium/high), and
// the backend rejects an out-of-range effort. Falls back to the default when valid, else the highest available.
export function resolveEffortForModel(
    effort: string | null | undefined,
    model: string | null | undefined
): ReasoningEffortEnumApi {
    const allowed = getEffortsForModel(model).map((option) => option.value)
    if (effort && allowed.includes(effort as ReasoningEffortEnumApi)) {
        return effort as ReasoningEffortEnumApi
    }
    return allowed.includes(DEFAULT_COMPOSER_EFFORT) ? DEFAULT_COMPOSER_EFFORT : allowed[allowed.length - 1]
}
