import { afterMount, connect, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { projectLogic } from 'scenes/projectLogic'

import { tasksMyConfigList } from 'products/tasks/frontend/generated/api'
import type {
    TasksResolvedAIRunDefaultsApi,
    TasksUserConfigResponseApi,
} from 'products/tasks/frontend/generated/api.schemas'

import type { taskRunDefaultsLogicType } from './taskRunDefaultsLogicType'

/**
 * The server-side default AI run configuration for the current user in the current project —
 * the user's per-project preference over the project default, as resolved by the tasks backend.
 * Composers read it to show what a run launches with when nothing is picked; a run created
 * without an explicit selection gets the same defaults applied server-side.
 */
export const taskRunDefaultsLogic = kea<taskRunDefaultsLogicType>([
    path(['products', 'posthog_ai', 'frontend', 'logics', 'taskRunDefaultsLogic']),

    connect(() => ({
        values: [projectLogic, ['currentProjectId']],
    })),

    loaders(({ values }) => ({
        myConfig: {
            __default: null as TasksUserConfigResponseApi | null,
            loadMyConfig: async (): Promise<TasksUserConfigResponseApi | null> => {
                if (values.currentProjectId == null) {
                    return null
                }
                try {
                    return await tasksMyConfigList(String(values.currentProjectId))
                } catch {
                    // Defaults are a nicety — a failed fetch (missing scope, transient error) must never
                    // break the composer, which falls back to its built-in defaults.
                    return null
                }
            },
        },
    })),

    selectors({
        resolvedDefaults: [
            (s) => [s.myConfig],
            (myConfig): TasksResolvedAIRunDefaultsApi | null => myConfig?.resolved_ai_run_defaults ?? null,
        ],
        // The web task tracker only drives the Claude runtime, so a Codex-adapter default is treated as
        // "no default" here — the composer then pins its built-in Claude model explicitly rather than
        // letting the backend resolve to a runtime this surface can't render.
        claudeDefaultModel: [
            (s) => [s.resolvedDefaults],
            (defaults): string | null => (defaults?.runtime_adapter === 'claude' ? defaults.model : null),
        ],
        claudeDefaultEffort: [
            (s) => [s.resolvedDefaults],
            (defaults): string | null => (defaults?.runtime_adapter === 'claude' ? defaults.reasoning_effort : null),
        ],
    }),

    afterMount(({ actions }) => {
        actions.loadMyConfig()
    }),
])
