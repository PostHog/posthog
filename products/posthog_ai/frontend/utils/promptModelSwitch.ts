import posthog from 'posthog-js'

import { tasksModelOverrideCreate } from 'products/tasks/frontend/generated/api'
import { type ReasoningEffortEnumApi, RuntimeAdapterEnumApi } from 'products/tasks/frontend/generated/api.schemas'
import { tasksModelOverrideCreateBodyMessageMax } from 'products/tasks/frontend/generated/api.zod'

const RUNTIME_ADAPTERS: ReadonlySet<string> = new Set(Object.values(RuntimeAdapterEnumApi))

function isRuntimeAdapter(value: string | null): value is RuntimeAdapterEnumApi {
    return value !== null && RUNTIME_ADAPTERS.has(value)
}

export type PromptModelSwitchSurface = 'new_task' | 'follow_up' | 'new_run'

export interface PromptModelSwitch {
    model: string | null
    reasoningEffort: ReasoningEffortEnumApi | null
}

/**
 * The model or effort that a message asks its run to use, such as "use opus for this", or `null` when it asks
 * for neither. A send path applies the answer to its picker before it reads the selection, so the picker stays
 * the one source of the model a run gets. Any failure answers `null`, and the message goes out on the picked model.
 */
export async function requestPromptModelSwitch(
    projectId: string,
    message: string,
    surface: PromptModelSwitchSurface,
    runtimeAdapter: string | null = null
): Promise<PromptModelSwitch | null> {
    if (message.length > tasksModelOverrideCreateBodyMessageMax) {
        return null
    }
    try {
        const { model, reasoning_effort } = await tasksModelOverrideCreate(projectId, {
            message,
            runtime_adapter: isRuntimeAdapter(runtimeAdapter) ? runtimeAdapter : null,
        })
        if (!model && !reasoning_effort) {
            return null
        }
        posthog.capture('posthog ai prompt model switch applied', { surface, model, reasoning_effort })
        return { model, reasoningEffort: reasoning_effort }
    } catch {
        return null
    }
}
