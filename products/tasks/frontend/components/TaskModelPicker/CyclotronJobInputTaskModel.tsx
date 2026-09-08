import { LemonSelect } from '@posthog/lemon-ui'

import type { CustomInputRendererProps } from 'lib/components/CyclotronJob/customInputRenderers'

import { normalizeModelId } from 'products/tasks/frontend/modelCatalog'
import { MODELS } from 'products/tasks/frontend/modelCatalog.generated'

type TaskModelValue = { model: string; reasoning_effort?: string }

const MODEL_OPTIONS = MODELS.map((model) => ({ value: model.id, label: model.label }))
const EFFORTS_BY_MODEL = new Map<string, readonly string[]>(MODELS.map((model) => [model.id, model.reasoningEfforts]))

export default function CyclotronJobInputTaskModel({ value, onChange }: CustomInputRendererProps): JSX.Element {
    const selected: Partial<TaskModelValue> = value ?? {}
    // Folded onto the bare catalog id so a value stored as `openai/gpt-5.6-sol` selects the option it names and
    // offers that model's efforts, rather than matching no option and rendering blank.
    const selectedModel = selected.model ? normalizeModelId(selected.model) : null
    const efforts = (selectedModel && EFFORTS_BY_MODEL.get(selectedModel)) || []

    const modelOptions = [...MODEL_OPTIONS]
    // A stored model that has since left the catalog still needs to render as itself, not as blank.
    if (selectedModel && !EFFORTS_BY_MODEL.has(selectedModel)) {
        modelOptions.push({ value: selectedModel, label: selectedModel })
    }

    return (
        <div className="flex gap-2">
            <LemonSelect
                className="flex-1"
                placeholder="Default model"
                allowClear
                value={selectedModel}
                options={modelOptions}
                onChange={(model) => {
                    if (!model) {
                        onChange(null)
                        return
                    }
                    // Keep the chosen effort across a model switch when the new model supports it;
                    // otherwise drop it so the server applies that model's default.
                    const supported = EFFORTS_BY_MODEL.get(model) ?? []
                    const effort =
                        selected.reasoning_effort && supported.includes(selected.reasoning_effort)
                            ? selected.reasoning_effort
                            : undefined
                    onChange(effort ? { model, reasoning_effort: effort } : { model })
                }}
                data-attr="task-model-picker-model"
            />
            {selectedModel && efforts.length > 0 && (
                <LemonSelect
                    placeholder="Default effort"
                    allowClear
                    value={selected.reasoning_effort ?? null}
                    options={efforts.map((effort) => ({ value: effort, label: effort }))}
                    onChange={(effort) =>
                        onChange(
                            effort ? { model: selectedModel, reasoning_effort: effort } : { model: selectedModel }
                        )
                    }
                    data-attr="task-model-picker-effort"
                />
            )}
        </div>
    )
}
