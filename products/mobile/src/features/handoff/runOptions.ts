import type {
    HandoffRunFieldsApi,
    ModelChoiceApi,
    PermissionModeApi,
    ReasoningEffortApi,
    ResolvedAiRunDefaultsApi,
    RunRuntimeSelectionApi,
    RuntimeAdapterApi,
} from '@/api/tasks'

// Ports of `products/posthog_ai/frontend/utils/composerModels.ts` and `composerModes.ts`, with the catalogue
// data from `products/tasks/frontend/modelCatalog.generated.ts`. Keep them in step with those files.

export interface PinnedModel {
    runtimeAdapter: RuntimeAdapterApi
    model: string
    reasoningEffort: ReasoningEffortApi | null
}

export interface RunOptions {
    model: PinnedModel | 'default'
    permissionMode: PermissionModeApi
    branch: string
}

const DEFAULT_PERMISSION_MODE: PermissionModeApi = 'auto'

export const DEFAULT_RUN_OPTIONS: RunOptions = { model: 'default', permissionMode: DEFAULT_PERMISSION_MODE, branch: '' }

/** What the web Inbox's Create PR pins when the user has no stored default (`REPORT_FALLBACK_RUNTIME`). */
export const HANDOFF_FALLBACK_RUNTIME: RunRuntimeSelectionApi & { reasoning_effort: ReasoningEffortApi } = {
    runtime_adapter: 'claude',
    model: 'claude-opus-5-5',
    reasoning_effort: 'high',
}

export const HARNESS_LABELS: Record<RuntimeAdapterApi, string> = { claude: 'Claude Code', codex: 'Codex' }

export const EFFORT_LABELS: Record<ReasoningEffortApi, string> = {
    low: 'Low',
    medium: 'Medium',
    high: 'High',
    xhigh: 'Extra high',
    max: 'Max',
    ultracode: 'Ultracode',
}

export const COST_BASELINE_LABEL = 'Claude Sonnet 5'

const DEFAULT_EFFORT: ReasoningEffortApi = 'high'

const FALLBACK_EFFORTS: ReasoningEffortApi[] = ['low', 'medium', 'high']

// `GET tasks/models/` does not filter these, and no picker may offer them.
const RETIRED_MODEL_IDS: ReadonlySet<string> = new Set([
    '@cf/zai-org/glm-5.2',
    'claude-opus-4-5',
    'claude-opus-4-6',
    'claude-opus-4-7',
    'claude-sonnet-4-6',
])

const PROVIDER_PREFIXES = ['anthropic/', 'openai/']

export const STATIC_CATALOGUE: ModelChoiceApi[] = [
    {
        runtime_adapter: 'claude',
        model: 'claude-opus-5-5',
        display_name: 'Claude Opus 5.5',
        supported_efforts: ['low', 'medium', 'high', 'xhigh', 'max', 'ultracode'],
        cost_multiplier: '2×',
    },
    {
        runtime_adapter: 'claude',
        model: 'claude-sonnet-5-5',
        display_name: 'Claude Sonnet 5.5',
        supported_efforts: ['low', 'medium', 'high', 'xhigh', 'max', 'ultracode'],
        cost_multiplier: '1×',
    },
    {
        runtime_adapter: 'claude',
        model: 'claude-fable-5-1',
        display_name: 'Claude Fable 5.1',
        supported_efforts: ['low', 'medium', 'high', 'xhigh', 'max', 'ultracode'],
        cost_multiplier: '5×',
    },
    {
        runtime_adapter: 'claude',
        model: 'moonshotai/kimi-k3',
        display_name: 'Kimi K3',
        supported_efforts: [],
        cost_multiplier: '1.5×',
    },
    {
        runtime_adapter: 'codex',
        model: 'gpt-6.1-sol',
        display_name: 'GPT-6.1 Sol',
        supported_efforts: ['low', 'medium', 'high', 'xhigh', 'max'],
        cost_multiplier: '1× base',
    },
    {
        runtime_adapter: 'codex',
        model: 'gpt-6-luna',
        display_name: 'GPT-6 Luna',
        supported_efforts: ['low', 'medium', 'high', 'xhigh', 'max'],
        cost_multiplier: '0.05×',
    },
]

// A stored run or default can carry a provider-qualified id for a model the catalogue lists bare.
function normalizeModelId(model: string): string {
    const normalized = model.trim().toLowerCase()
    const prefix = PROVIDER_PREFIXES.find((candidate) => normalized.startsWith(candidate))
    return prefix ? normalized.slice(prefix.length) : normalized
}

/**
 * The models a picker lists: everything still offered, plus `keepModel` when the catalogue has since retired it, so
 * a stored default keeps its display name. Port of the web's `pickerModels`.
 */
export function offeredModels(catalogue: readonly ModelChoiceApi[], keepModel?: string | null): ModelChoiceApi[] {
    const kept = catalogueEntry(catalogue, keepModel)
    return catalogue.filter(
        (option) => !RETIRED_MODEL_IDS.has(normalizeModelId(option.model)) || option.model === kept?.model
    )
}

export function catalogueEntry(
    catalogue: readonly ModelChoiceApi[],
    model: string | null | undefined
): ModelChoiceApi | undefined {
    if (!model) {
        return undefined
    }
    const normalized = normalizeModelId(model)
    return catalogue.find((option) => option.model === normalized)
}

function effortsForModel(catalogue: readonly ModelChoiceApi[], model: string | null | undefined): ReasoningEffortApi[] {
    return catalogueEntry(catalogue, model)?.supported_efforts ?? FALLBACK_EFFORTS
}

/** Clamps an effort carried over from another model to one this model accepts, as the backend rejects the rest. */
export function resolveEffortForModel(
    catalogue: readonly ModelChoiceApi[],
    effort: string | null | undefined,
    model: string | null | undefined
): ReasoningEffortApi {
    const allowed = effortsForModel(catalogue, model)
    if (!allowed.length) {
        return DEFAULT_EFFORT
    }
    const match = allowed.find((value) => value === effort)
    if (match) {
        return match
    }
    return allowed.includes(DEFAULT_EFFORT) ? DEFAULT_EFFORT : (allowed[allowed.length - 1] ?? DEFAULT_EFFORT)
}

/** The harnesses the catalogue offers, in catalogue order, so one the gateway stops serving drops out. */
export function runtimeAdapters(catalogue: readonly ModelChoiceApi[]): RuntimeAdapterApi[] {
    return [...new Set(catalogue.map((option) => option.runtime_adapter))]
}

export function pinModel(
    catalogue: readonly ModelChoiceApi[],
    option: ModelChoiceApi,
    previousEffort: string | null | undefined
): PinnedModel {
    const hasEfforts = effortsForModel(catalogue, option.model).length > 0
    return {
        runtimeAdapter: option.runtime_adapter,
        model: option.model,
        reasoningEffort: hasEfforts ? resolveEffortForModel(catalogue, previousEffort, option.model) : null,
    }
}

interface ModeOption {
    value: PermissionModeApi
    label: string
    description: string
}

const MODE_OPTIONS: Record<PermissionModeApi, ModeOption> = {
    default: {
        value: 'default',
        label: 'Default',
        description: 'Asks before anything that changes files, runs commands, or touches live data.',
    },
    acceptEdits: {
        value: 'acceptEdits',
        label: 'Accept edits',
        description: 'Accepts file edits automatically. Still asks before shell commands and live data.',
    },
    plan: {
        value: 'plan',
        label: 'Plan',
        description: 'Plans the work first. Nothing runs until you approve the plan.',
    },
    'read-only': {
        value: 'read-only',
        label: 'Read only',
        description: 'Inspects the repo and answers, but changes nothing.',
    },
    auto: {
        value: 'auto',
        label: 'Auto',
        description:
            'Accepts file edits and shell commands automatically. Always asks before PostHog tools that change live data. Creating or publishing content asks only while you watch the run.',
    },
    bypassPermissions: {
        value: 'bypassPermissions',
        label: 'Full auto',
        description: 'Never asks. The agent can change or delete live data on its own.',
    },
    'full-access': {
        value: 'full-access',
        label: 'Full access',
        description: 'Never asks. The agent can change or delete live data on its own.',
    },
}

const CLAUDE_MODES: PermissionModeApi[] = ['default', 'acceptEdits', 'plan', 'bypassPermissions', 'auto']
const CODEX_MODES: PermissionModeApi[] = ['plan', 'read-only', 'auto', 'full-access']

// Hidden like the web and desktop pickers hide them until a setting allows them. They stay in the vocabularies so
// coercion across harnesses still maps onto them.
const GATED_MODES: PermissionModeApi[] = ['bypassPermissions', 'full-access']

// A mode that only exists on the other harness maps to its nearest equivalent. Default and Accept edits become Auto
// on Codex, which has no asking mode short of Plan; Read only becomes Plan on Claude.
const CODEX_FALLBACKS: Partial<Record<PermissionModeApi, PermissionModeApi>> = {
    default: 'auto',
    acceptEdits: 'auto',
    bypassPermissions: 'full-access',
}
const CLAUDE_FALLBACKS: Partial<Record<PermissionModeApi, PermissionModeApi>> = {
    'read-only': 'plan',
    'full-access': 'bypassPermissions',
}

export function modesForRuntimeAdapter(runtimeAdapter: RuntimeAdapterApi): ModeOption[] {
    const vocabulary = runtimeAdapter === 'codex' ? CODEX_MODES : CLAUDE_MODES
    return vocabulary.filter((mode) => !GATED_MODES.includes(mode)).map((mode) => MODE_OPTIONS[mode])
}

export function resolveModeForRuntimeAdapter(
    runtimeAdapter: RuntimeAdapterApi,
    mode: PermissionModeApi
): PermissionModeApi {
    if (runtimeAdapter === 'codex') {
        return CODEX_MODES.includes(mode) ? mode : (CODEX_FALLBACKS[mode] ?? 'auto')
    }
    return CLAUDE_MODES.includes(mode) ? mode : (CLAUDE_FALLBACKS[mode] ?? 'default')
}

export function isPermissionMode(value: string): value is PermissionModeApi {
    return Object.hasOwn(MODE_OPTIONS, value)
}

export function isReasoningEffort(value: string): value is ReasoningEffortApi {
    return Object.hasOwn(EFFORT_LABELS, value)
}

export function modeLabel(mode: PermissionModeApi): string {
    return MODE_OPTIONS[mode].label
}

function asRuntimeAdapter(value: string | null | undefined): RuntimeAdapterApi | undefined {
    return value === 'claude' || value === 'codex' ? value : undefined
}

// Mirrors `usable` in `resolve_ai_run_selection`: a run that pins no runtime starts on ACP, which discards a Pi default.
function hasUsableDefault(
    defaults: ResolvedAiRunDefaultsApi
): defaults is ResolvedAiRunDefaultsApi & { runtime: 'acp'; model: string } {
    return defaults.runtime === 'acp' && defaults.model !== null && defaults.runtime_adapter !== null
}

export function effectiveRuntimeAdapter(
    options: RunOptions,
    defaults: ResolvedAiRunDefaultsApi | undefined
): RuntimeAdapterApi {
    if (options.model !== 'default') {
        return options.model.runtimeAdapter
    }
    if (!defaults || !hasUsableDefault(defaults)) {
        return HANDOFF_FALLBACK_RUNTIME.runtime_adapter
    }
    return asRuntimeAdapter(defaults.runtime_adapter) ?? 'claude'
}

export function defaultModelSelection(
    defaults: ResolvedAiRunDefaultsApi | undefined
): { model: string; reasoningEffort: string | null } | undefined {
    if (!defaults) {
        return undefined
    }
    if (!hasUsableDefault(defaults)) {
        return { model: HANDOFF_FALLBACK_RUNTIME.model, reasoningEffort: HANDOFF_FALLBACK_RUNTIME.reasoning_effort }
    }
    return { model: defaults.model, reasoningEffort: defaults.reasoning_effort }
}

/**
 * The run fields for a hand-off. An untouched model sends no runtime, because a model sent with the run is final
 * server-side and would override the user's stored default. Opus 5.5 / high goes out only when the server reports
 * no usable stored default (none, or a Pi one), matching the web Inbox. While the defaults are unknown the server
 * resolves them.
 */
export function buildHandoffRunRequest(
    options: RunOptions,
    defaults: ResolvedAiRunDefaultsApi | undefined
): HandoffRunFieldsApi {
    const branch = options.branch.trim()
    const branchField = branch ? { branch } : {}
    if (options.model !== 'default') {
        const { runtimeAdapter, model, reasoningEffort } = options.model
        return {
            runtime_adapter: runtimeAdapter,
            model,
            ...(reasoningEffort ? { reasoning_effort: reasoningEffort } : {}),
            initial_permission_mode: resolveModeForRuntimeAdapter(runtimeAdapter, options.permissionMode),
            ...branchField,
        }
    }
    if (defaults && !hasUsableDefault(defaults)) {
        return {
            ...HANDOFF_FALLBACK_RUNTIME,
            initial_permission_mode: resolveModeForRuntimeAdapter('claude', options.permissionMode),
            ...branchField,
        }
    }
    const adapter = asRuntimeAdapter(defaults?.runtime_adapter)
    return {
        initial_permission_mode: adapter
            ? resolveModeForRuntimeAdapter(adapter, options.permissionMode)
            : options.permissionMode,
        ...branchField,
    }
}

export function modelDisplayName(catalogue: readonly ModelChoiceApi[], model: string): string {
    return (
        catalogueEntry(catalogue, model)?.display_name ?? catalogueEntry(STATIC_CATALOGUE, model)?.display_name ?? model
    )
}

function effortLabel(effort: string | null | undefined): string | undefined {
    return effort && effort in EFFORT_LABELS ? EFFORT_LABELS[effort as ReasoningEffortApi] : undefined
}

export function modelSummary(catalogue: readonly ModelChoiceApi[], model: string, effort: string | null): string {
    const label = effortLabel(effort)
    const name = modelDisplayName(catalogue, model)
    return label ? `${name} · ${label}` : name
}
