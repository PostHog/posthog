import { ReasoningEffortEnumApi } from 'products/tasks/frontend/generated/api.schemas'

export interface ComposerModelOption {
    value: string
    label: string
}

export interface ComposerEffortOption {
    value: ReasoningEffortEnumApi
    label: string
}

// Claude-only lineup — the task tracker always launches the `claude` runtime adapter, so Codex/GPT models are
// intentionally absent. Add new Claude models here as they ship.
export const COMPOSER_MODELS: ComposerModelOption[] = [
    { value: 'claude-opus-4-8', label: 'Claude Opus 4.8' },
    { value: 'claude-sonnet-4-6', label: 'Claude Sonnet 4.6' },
]

export const DEFAULT_COMPOSER_MODEL = 'claude-opus-4-8'
export const DEFAULT_COMPOSER_EFFORT: ReasoningEffortEnumApi = ReasoningEffortEnumApi.High

const EFFORT_LABELS: Record<ReasoningEffortEnumApi, string> = {
    [ReasoningEffortEnumApi.Low]: 'Low',
    [ReasoningEffortEnumApi.Medium]: 'Medium',
    [ReasoningEffortEnumApi.High]: 'High',
    [ReasoningEffortEnumApi.Xhigh]: 'Extra high',
    [ReasoningEffortEnumApi.Max]: 'Max',
}

// Mirrors backend CLAUDE_REASONING_EFFORTS_BY_MODEL (products/tasks/backend/temporal/process_task/utils.py):
// xhigh/max are only offered for models that support them.
const EFFORTS_BY_MODEL: Record<string, ReasoningEffortEnumApi[]> = {
    'claude-opus-4-8': [
        ReasoningEffortEnumApi.Low,
        ReasoningEffortEnumApi.Medium,
        ReasoningEffortEnumApi.High,
        ReasoningEffortEnumApi.Xhigh,
        ReasoningEffortEnumApi.Max,
    ],
    'claude-sonnet-4-6': [ReasoningEffortEnumApi.Low, ReasoningEffortEnumApi.Medium, ReasoningEffortEnumApi.High],
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
