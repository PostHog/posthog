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
    pinModel,
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
        const previousEffort =
            options.model === 'default'
                ? defaultModelSelection(defaults)?.reasoningEffort
                : options.model.reasoningEffort
        setModel(pinModel(catalogue, option, previousEffort), option.runtime_adapter)
        trackOptionChanged('model')
    }
    const pickEffort = (reasoningEffort: ReasoningEffortApi): void => {
        const { options, setModel } = useRunOptionsStore.getState()
        if (options.model !== 'default') {
            setModel({ ...options.model, reasoningEffort }, options.model.runtimeAdapter)
        } else {
            const entry = catalogueEntry(catalogue, defaultModelSelection(defaults)?.model)
            if (!entry) {
                return
            }
            setModel(
                { runtimeAdapter: entry.runtime_adapter, model: entry.model, reasoningEffort },
                entry.runtime_adapter
            )
        }
        trackOptionChanged('effort')
    }
    const resetModel = (): void => {
        const { options, setModel } = useRunOptionsStore.getState()
        if (options.model === 'default') {
            return
        }
        setModel('default', effectiveRuntimeAdapter(DEFAULT_RUN_OPTIONS, defaults))
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
