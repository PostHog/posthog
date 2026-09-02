import {
    ClaudeRuntimeAdapterEnumApi,
    CodexRuntimeAdapterEnumApi,
    CodexTaskRunCreateSchemaInitialPermissionModeEnumApi,
    InitialPermissionModeEnumApi,
    ModelChoiceApi,
    ReasoningEffortEnumApi,
    RuntimeAdapterEnumApi,
    TaskRunCreateRequestSchemaApi,
} from 'products/tasks/frontend/generated/api.schemas'

import { type PermissionMode, resolveModeForRuntimeAdapter } from './composerModes'

export interface ComposerEffortOption {
    value: ReasoningEffortEnumApi
    label: string
}

// What a thinking model supports at minimum. Only reached for a model the catalogue hasn't described yet — while the
// first fetch is in flight, or for a run started on a model since retired from the gateway.
const FALLBACK_EFFORTS: ReasoningEffortEnumApi[] = [
    ReasoningEffortEnumApi.Low,
    ReasoningEffortEnumApi.Medium,
    ReasoningEffortEnumApi.High,
]

// Used only when the tasks API can't answer: an unreachable LLM gateway makes the catalogue endpoint return an empty
// list, and an empty model dropdown is worse than a stale one. The live catalogue is the source of truth — see
// `modelCatalogueLogic`. Claude-only: without the catalogue we can't know a Codex model exists, and Claude is the default.
export const FALLBACK_MODEL_CHOICES: ModelChoiceApi[] = [
    {
        runtime_adapter: RuntimeAdapterEnumApi.Claude,
        model: 'claude-sonnet-5',
        display_name: 'Claude Sonnet 5',
        supported_efforts: FALLBACK_EFFORTS,
    },
    {
        runtime_adapter: RuntimeAdapterEnumApi.Claude,
        model: 'claude-opus-5',
        display_name: 'Claude Opus 5',
        supported_efforts: FALLBACK_EFFORTS,
    },
]

export const DEFAULT_COMPOSER_MODEL = 'claude-sonnet-5'
export const DEFAULT_COMPOSER_EFFORT: ReasoningEffortEnumApi = ReasoningEffortEnumApi.High

const EFFORT_LABELS: Record<string, string> = {
    [ReasoningEffortEnumApi.Low]: 'Low',
    [ReasoningEffortEnumApi.Medium]: 'Medium',
    [ReasoningEffortEnumApi.High]: 'High',
    [ReasoningEffortEnumApi.Xhigh]: 'Extra high',
    [ReasoningEffortEnumApi.Max]: 'Max',
    [ReasoningEffortEnumApi.Ultracode]: 'Ultracode',
}

export function getEffortsForModel(
    catalogue: ModelChoiceApi[],
    model: string | null | undefined
): ComposerEffortOption[] {
    const efforts = catalogue.find((option) => option.model === model)?.supported_efforts ?? FALLBACK_EFFORTS
    return efforts.map((value) => ({ value, label: EFFORT_LABELS[value] ?? value }))
}

// Which runtime drives this model. The adapter is a property of the model, not an independent choice, so
// deriving it is what keeps a `(runtime_adapter, model)` pair from ever disagreeing. Defaults to `claude` for a
// model the catalogue hasn't described — the fallback lineup is Claude-only.
export function getRuntimeAdapterForModel(
    catalogue: ModelChoiceApi[],
    model: string | null | undefined
): RuntimeAdapterEnumApi {
    return catalogue.find((option) => option.model === model)?.runtime_adapter ?? RuntimeAdapterEnumApi.Claude
}

// The harnesses the catalogue actually offers, in the order the models arrive. Derived rather than enumerated, so a
// runtime the gateway stops serving disappears from the picker on its own.
export function listRuntimeAdapters(catalogue: ModelChoiceApi[]): RuntimeAdapterEnumApi[] {
    return [...new Set(catalogue.map((option) => option.runtime_adapter))]
}

export function modelsForRuntimeAdapter(
    catalogue: ModelChoiceApi[],
    runtimeAdapter: RuntimeAdapterEnumApi
): ModelChoiceApi[] {
    return catalogue.filter((option) => option.runtime_adapter === runtimeAdapter)
}

/** One stop on the Faster/Smarter slider: a model paired with the effort it runs at. */
export interface CapabilityNotch {
    model: string
    effort: ReasoningEffortEnumApi
}

// The curated Faster → Smarter progression per harness, kept in step with the desktop app's ladder in
// `products/desktop/packages/agent/src/adapters/reasoning-effort.ts` so both surfaces offer the same rungs.
const CAPABILITY_LADDERS: Record<RuntimeAdapterEnumApi, CapabilityNotch[]> = {
    [RuntimeAdapterEnumApi.Claude]: [
        { model: 'claude-sonnet-5', effort: ReasoningEffortEnumApi.Medium },
        { model: 'claude-sonnet-5', effort: ReasoningEffortEnumApi.High },
        { model: 'claude-opus-5', effort: ReasoningEffortEnumApi.Medium },
        { model: 'claude-opus-5', effort: ReasoningEffortEnumApi.Xhigh },
        { model: 'claude-fable-5', effort: ReasoningEffortEnumApi.Max },
    ],
    [RuntimeAdapterEnumApi.Codex]: [
        { model: 'gpt-5.6-terra', effort: ReasoningEffortEnumApi.Low },
        { model: 'gpt-5.6-sol', effort: ReasoningEffortEnumApi.Low },
        { model: 'gpt-5.6-sol', effort: ReasoningEffortEnumApi.Medium },
        { model: 'gpt-5.6-sol', effort: ReasoningEffortEnumApi.High },
        { model: 'gpt-5.6-sol', effort: ReasoningEffortEnumApi.Xhigh },
    ],
}

/**
 * The ladder rungs the live catalogue actually serves. A notch naming a model the gateway no longer offers — or an
 * effort that model no longer accepts — drops out rather than becoming a stop that fails on send. The picker falls
 * back to its plain effort list when fewer than two rungs survive.
 */
export function getCapabilityLadder(
    catalogue: ModelChoiceApi[],
    runtimeAdapter: RuntimeAdapterEnumApi
): CapabilityNotch[] {
    return (CAPABILITY_LADDERS[runtimeAdapter] ?? []).filter((notch) =>
        catalogue.some((option) => option.model === notch.model && option.supported_efforts.includes(notch.effort))
    )
}

const RUNTIME_ADAPTER_LABELS: Record<RuntimeAdapterEnumApi, string> = {
    [RuntimeAdapterEnumApi.Claude]: 'Claude',
    [RuntimeAdapterEnumApi.Codex]: 'Codex',
}

export function getRuntimeAdapterLabel(runtimeAdapter: string): string {
    return RUNTIME_ADAPTER_LABELS[runtimeAdapter as RuntimeAdapterEnumApi] ?? runtimeAdapter
}

export function getModelLabel(catalogue: ModelChoiceApi[], model: string | null | undefined): string {
    return catalogue.find((option) => option.model === model)?.display_name ?? model ?? 'Model'
}

export function getEffortLabel(effort: string | null | undefined): string {
    return effort ? (EFFORT_LABELS[effort] ?? effort) : 'Effort'
}

// Clamp an effort to one the selected model actually supports — the new-run path can inherit an effort from a
// previous run on a different model (e.g. `max` carried over to a model that only offers low/medium/high), and the
// backend rejects an out-of-range effort. Falls back to the default when valid, else the highest available.
export function resolveEffortForModel(
    catalogue: ModelChoiceApi[],
    effort: string | null | undefined,
    model: string | null | undefined
): ReasoningEffortEnumApi {
    const allowed = getEffortsForModel(catalogue, model).map((option) => option.value)
    // A model with no effort control reports none; the picker hides the row, and `buildRunCreateRequest`
    // omits the field entirely. This value is only ever a display fallback.
    if (!allowed.length) {
        return DEFAULT_COMPOSER_EFFORT
    }
    if (effort && allowed.includes(effort as ReasoningEffortEnumApi)) {
        return effort as ReasoningEffortEnumApi
    }
    return allowed.includes(DEFAULT_COMPOSER_EFFORT) ? DEFAULT_COMPOSER_EFFORT : allowed[allowed.length - 1]
}

/**
 * Build a run-create request for the picked model.
 *
 * The request schema is discriminated on `runtime_adapter`, and each runtime names its permission modes
 * differently — so which runtime a model belongs to has to be decided in one place rather than assumed at each
 * call site. Everything else the caller needs (branch, resume id, message) rides along in `rest`.
 */
export function buildRunCreateRequest(
    catalogue: ModelChoiceApi[],
    model: string,
    reasoningEffort: ReasoningEffortEnumApi,
    permissionMode: PermissionMode,
    rest: Partial<TaskRunCreateRequestSchemaApi>
): TaskRunCreateRequestSchemaApi {
    // A model with no effort control rejects any effort at all — `get_reasoning_effort_error` answers
    // "Supported values: none" — so the field is left off rather than sent with a display fallback.
    const effort = getEffortsForModel(catalogue, model).length ? reasoningEffort : undefined

    if (getRuntimeAdapterForModel(catalogue, model) === CodexRuntimeAdapterEnumApi.Codex) {
        return {
            ...rest,
            runtime_adapter: CodexRuntimeAdapterEnumApi.Codex,
            model,
            reasoning_effort: effort,
            initial_permission_mode: resolveModeForRuntimeAdapter(
                CodexRuntimeAdapterEnumApi.Codex,
                permissionMode
            ) as CodexTaskRunCreateSchemaInitialPermissionModeEnumApi,
        }
    }
    return {
        ...rest,
        runtime_adapter: ClaudeRuntimeAdapterEnumApi.Claude,
        model,
        reasoning_effort: effort,
        initial_permission_mode: resolveModeForRuntimeAdapter(
            ClaudeRuntimeAdapterEnumApi.Claude,
            permissionMode
        ) as InitialPermissionModeEnumApi,
    }
}
