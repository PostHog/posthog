import { LemonSelect } from '@posthog/lemon-ui'

import type { CustomInputRendererProps } from 'lib/components/CyclotronJob/customInputRenderers'

import { MODELS } from 'products/tasks/frontend/modelCatalog.generated'

type TaskModelValue = { model: string; reasoning_effort?: string }

const MODEL_OPTIONS = MODELS.map((model) => ({ value: model.id, label: model.label }))
const EFFORTS_BY_MODEL = new Map<string, readonly string[]>(MODELS.map((model) => [model.id, model.reasoningEfforts]))

export default function CyclotronJobInputTaskModel({ value, onChange }: CustomInputRendererProps): JSX.Element {
    const selected: Partial<TaskModelValue> = value ?? {}
    const efforts = (selected.model && EFFORTS_BY_MODEL.get(selected.model)) || []

    const modelOptions = [...MODEL_OPTIONS]
    // A stored model that has since left the catalog still needs to render as itself, not as blank.
    if (selected.model && !EFFORTS_BY_MODEL.has(selected.model)) {
        modelOptions.push({ value: selected.model, label: selected.model })
    }

    return (
        <div className="flex gap-2">
            <LemonSelect
                className="flex-1"
                placeholder="Default model"
                allowClear
                value={selected.model ?? null}
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
            {efforts.length > 0 && (
                <LemonSelect
                    placeholder="Default effort"
                    allowClear
                    value={selected.reasoning_effort ?? null}
                    options={efforts.map((effort) => ({ value: effort, label: effort }))}
                    onChange={(effort) =>
                        onChange(
                            effort ? { model: selected.model, reasoning_effort: effort } : { model: selected.model }
                        )
                    }
                    data-attr="task-model-picker-effort"
                />
            )}
        </div>
    )
}
