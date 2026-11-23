import posthog from 'posthog-js'

import { tasksModelOverrideCreate } from 'products/tasks/frontend/generated/api'
import {
    type ReasoningEffortEnumApi,
    RuntimeAdapterEnumApi,
    type TaskModelOverrideResponseApi,
} from 'products/tasks/frontend/generated/api.schemas'

const RUNTIME_ADAPTERS: ReadonlySet<string> = new Set(Object.values(RuntimeAdapterEnumApi))

function isRuntimeAdapter(value: string | null): value is RuntimeAdapterEnumApi {
    return value !== null && RUNTIME_ADAPTERS.has(value)
}

export type PromptModelSwitchSurface = 'new_task' | 'follow_up' | 'new_run'

export interface ModelPicker {
    setModel: (model: string) => void
    setEffort: (effort: ReasoningEffortEnumApi) => void
}

/**
 * Switch the picker to the model or effort that a message asks its run to use, such as "use opus for this".
 * A send path calls this before it reads the selection, so the picker stays the one source of the model a run
 * gets. Any failure leaves the picker alone, and the message goes out on the picked model.
 */
export async function applyPromptModelSwitch(
    projectId: string,
    message: string,
    surface: PromptModelSwitchSurface,
    picker: ModelPicker,
    runtimeAdapter: string | null = null
): Promise<void> {
    let requested: TaskModelOverrideResponseApi
    try {
        requested = await tasksModelOverrideCreate(projectId, {
            message,
            runtime_adapter: isRuntimeAdapter(runtimeAdapter) ? runtimeAdapter : null,
        })
    } catch {
        return
    }
    const { model, reasoning_effort } = requested
    if (!model && !reasoning_effort) {
        return
    }
    posthog.capture('posthog ai prompt model switch applied', { surface, model, reasoning_effort })
    if (model) {
        picker.setModel(model)
    }
    if (reasoning_effort) {
        picker.setEffort(reasoning_effort)
    }
}
