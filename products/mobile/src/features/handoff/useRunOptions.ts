import { type QueryClient, useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'

import { type ProjectScope, scopeKey } from '@/api/reports'
import {
    getMyTaskConfig,
    getTaskModels,
    type ModelChoiceApi,
    type PermissionModeApi,
    type ReasoningEffortApi,
    type ResolvedAiRunDefaultsApi,
    type RuntimeAdapterApi,
} from '@/api/tasks'
import { useProjectScope } from '@/auth/useProjectScope'
import { useDemoMode } from '@/demo/demoMode'
import { track } from '@/lib/analytics'

import {
    catalogueEntry,
    DEFAULT_RUN_OPTIONS,
    defaultModelSelection,
    effectiveRuntimeAdapter,
    offeredModels,
    type PinnedModel,
    pinModel,
    type RunOptions,
    STATIC_CATALOGUE,
} from './runOptions'
import { useRunOptionsStore } from './runOptionsStore'

const CATALOGUE_STALE_MS = 10 * 60_000
const DEFAULTS_STALE_MS = 60_000

export const runOptionKeys = {
    models: (scope: ProjectScope | null) => ['tasks', ...scopeKey(scope), 'models'] as const,
    myConfig: (scope: ProjectScope | null) => ['tasks', ...scopeKey(scope), 'my_config'] as const,
}

// Demo mode has no account, so the pickers show the sample catalogue on the Inbox fallback.
const DEMO_DEFAULTS: ResolvedAiRunDefaultsApi = {
    runtime: 'acp',
    runtime_adapter: null,
    model: null,
    reasoning_effort: null,
    source: 'none',
}

export interface ModelCatalogueState {
    catalogue: ModelChoiceApi[]
    loading: boolean
    /** True when the request failed or the gateway listed nothing. The run then uses the default model. */
    unavailable: boolean
}

export function useModelCatalogue(enabled: boolean, keepModel: string | undefined): ModelCatalogueState {
    const demo = useDemoMode((state) => state.enabled)
    const scope = useProjectScope()
    const query = useQuery({
        queryKey: runOptionKeys.models(scope),
        queryFn: ({ signal }) => getTaskModels(signal),
        enabled: enabled && !demo && scope !== null,
        staleTime: CATALOGUE_STALE_MS,
    })
    const catalogue = useMemo(
        () => offeredModels(demo ? STATIC_CATALOGUE : (query.data ?? []), keepModel),
        [demo, query.data, keepModel]
    )
    if (demo) {
        return { catalogue, loading: false, unavailable: false }
    }
    return {
        catalogue,
        loading: query.isPending && query.fetchStatus !== 'idle',
        unavailable: query.isError || (query.isSuccess && catalogue.length === 0),
    }
}

export function useRunDefaults(enabled: boolean): ResolvedAiRunDefaultsApi | undefined {
    const demo = useDemoMode((state) => state.enabled)
    const scope = useProjectScope()
    const query = useQuery({
        queryKey: runOptionKeys.myConfig(scope),
        queryFn: ({ signal }) => getMyTaskConfig(signal),
        enabled: enabled && !demo && scope !== null,
        staleTime: DEFAULTS_STALE_MS,
    })
    return demo ? DEMO_DEFAULTS : query.data?.resolved_ai_run_defaults
}

export async function fetchRunDefaults(
    queryClient: QueryClient,
    scope: ProjectScope | null
): Promise<ResolvedAiRunDefaultsApi | undefined> {
    try {
        const config = await queryClient.fetchQuery({
            queryKey: runOptionKeys.myConfig(scope),
            queryFn: ({ signal }) => getMyTaskConfig(signal),
            staleTime: DEFAULTS_STALE_MS,
            // The hand-off is waiting on this, and a failure only means the server picks the defaults.
            retry: false,
        })
        return config.resolved_ai_run_defaults
    } catch {
        return undefined
    }
}

type RunOption = 'model' | 'effort' | 'mode' | 'branch'

// The option name only: a value such as a branch can carry repository or customer names.
function trackOptionChanged(option: RunOption): void {
    track('mobile_handoff_option_changed', { option })
}

type ModelSelection = RunOptions['model']

export function modelAfterPick(
    catalogue: readonly ModelChoiceApi[],
    defaults: ResolvedAiRunDefaultsApi | undefined,
    current: ModelSelection,
    option: ModelChoiceApi
): PinnedModel {
    const previousEffort =
        current === 'default' ? defaultModelSelection(defaults)?.reasoningEffort : current.reasoningEffort
    return pinModel(catalogue, option, previousEffort)
}

/**
 * The model an effort pick pins. With an untouched model this pins the default model at the picked effort, so it is
 * undefined when the catalogue does not list the default model.
 */
export function modelAfterEffort(
    catalogue: readonly ModelChoiceApi[],
    defaults: ResolvedAiRunDefaultsApi | undefined,
    current: ModelSelection,
    reasoningEffort: ReasoningEffortApi
): PinnedModel | undefined {
    if (current !== 'default') {
        return { ...current, reasoningEffort }
    }
    const entry = catalogueEntry(catalogue, defaultModelSelection(defaults)?.model)
    return entry ? { runtimeAdapter: entry.runtime_adapter, model: entry.model, reasoningEffort } : undefined
}

export function defaultRuntimeAdapter(defaults: ResolvedAiRunDefaultsApi | undefined): RuntimeAdapterApi {
    return effectiveRuntimeAdapter(DEFAULT_RUN_OPTIONS, defaults)
}

export interface RunOptionActions {
    pickModel: (option: ModelChoiceApi) => void
    /** With an untouched model this pins the default model at the picked effort. */
    pickEffort: (effort: ReasoningEffortApi) => void
    resetModel: () => void
    pickMode: (mode: PermissionModeApi) => void
    /** Stores the text as typed, so leaving the page any way keeps it. Tracks nothing. */
    editBranch: (branch: string) => void
    /** Tracks one change when the page closes on a different branch than `openedWith`. */
    finishBranch: (openedWith: string) => void
}

export function useRunOptionActions(
    catalogue: readonly ModelChoiceApi[],
    defaults: ResolvedAiRunDefaultsApi | undefined
): RunOptionActions {
    const pickModel = (option: ModelChoiceApi): void => {
        const { options, setModel } = useRunOptionsStore.getState()
        setModel(modelAfterPick(catalogue, defaults, options.model, option), option.runtime_adapter)
        trackOptionChanged('model')
    }
    const pickEffort = (reasoningEffort: ReasoningEffortApi): void => {
        const { options, setModel } = useRunOptionsStore.getState()
        const model = modelAfterEffort(catalogue, defaults, options.model, reasoningEffort)
        if (!model) {
            return
        }
        setModel(model, model.runtimeAdapter)
        trackOptionChanged('effort')
    }
    const resetModel = (): void => {
        const { options, setModel } = useRunOptionsStore.getState()
        if (options.model === 'default') {
            return
        }
        setModel('default', defaultRuntimeAdapter(defaults))
        trackOptionChanged('model')
    }
    const pickMode = (mode: PermissionModeApi): void => {
        const { options, setPermissionMode } = useRunOptionsStore.getState()
        if (options.permissionMode !== mode) {
            setPermissionMode(mode)
            trackOptionChanged('mode')
        }
    }
    const editBranch = (branch: string): void => {
        useRunOptionsStore.getState().setBranch(branch.trim())
    }
    const finishBranch = (openedWith: string): void => {
        if (useRunOptionsStore.getState().options.branch !== openedWith.trim()) {
            trackOptionChanged('branch')
        }
    }
    return { pickModel, pickEffort, resetModel, pickMode, editBranch, finishBranch }
}
