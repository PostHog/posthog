import { useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import type { CustomInputRendererProps } from 'lib/components/CyclotronJob/customInputRenderers'

import { taskModelPickerLogic } from './taskModelPickerLogic'

type TaskModelValue = { model: string; reasoning_effort?: string }

export default function CyclotronJobInputTaskModel({ value, onChange }: CustomInputRendererProps): JSX.Element {
    const { models, modelsLoading } = useValues(taskModelPickerLogic)

    const selected: Partial<TaskModelValue> = value ?? {}
    const selectedChoice = models.find((choice) => choice.model === selected.model)
    const efforts = selectedChoice?.supported_efforts ?? []

    const modelOptions = models.map((choice) => ({ value: choice.model, label: choice.display_name }))
    // A stored model that has since left the catalogue still needs to render as itself, not as blank.
    if (selected.model && !selectedChoice) {
        modelOptions.push({ value: selected.model, label: selected.model })
    }

    return (
        <div className="flex gap-2">
            <LemonSelect
                className="flex-1"
                placeholder={modelsLoading ? 'Loading models...' : 'Default model'}
                allowClear
                disabledReason={
                    !modelsLoading && models.length === 0 && !selected.model
                        ? 'Model list is unavailable right now. The task will use the default model.'
                        : undefined
                }
                value={selected.model ?? null}
                options={modelOptions}
                onChange={(model) => {
                    if (!model) {
                        onChange(null)
                        return
                    }
                    const choice = models.find((c) => c.model === model)
                    const supported = choice?.supported_efforts ?? []
                    // Keep the chosen effort across a model switch when the new model supports it;
                    // otherwise drop it so the server applies that model's default.
                    const effort =
                        selected.reasoning_effort && (supported as string[]).includes(selected.reasoning_effort)
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
