import { useValues } from 'kea'
import { useMemo } from 'react'

import { LemonSelect } from '@posthog/lemon-ui'

import type { CustomInputRendererProps } from 'lib/components/CyclotronJob/customInputRenderers'

import { modelCatalogueLogic } from 'products/posthog_ai/frontend/logics/modelCatalogueLogic'
import { normalizeModelId } from 'products/tasks/frontend/modelCatalog'
import { REASONING_EFFORT_LABELS } from 'products/tasks/frontend/modelCatalog.generated'

type TaskModelValue = { model: string; reasoning_effort?: string }

// Widened to take the plain strings a stored workflow config carries.
const EFFORT_LABELS: Record<string, string> = REASONING_EFFORT_LABELS

export default function CyclotronJobInputTaskModel({ value, onChange }: CustomInputRendererProps): JSX.Element {
    const { catalogue } = useValues(modelCatalogueLogic)
    const selected: Partial<TaskModelValue> = value ?? {}
    // Folded onto the bare catalog id so a value stored as `openai/gpt-5.6-sol` selects the option it names and
    // offers that model's efforts, rather than matching no option and rendering blank.
    const selectedModel = selected.model ? normalizeModelId(selected.model) : null
    const effortsByModel = useMemo(
        () => new Map<string, readonly string[]>(catalogue.map((choice) => [choice.model, choice.supported_efforts])),
        [catalogue]
    )
    const efforts = (selectedModel && effortsByModel.get(selectedModel)) || []

    const modelOptions = catalogue
        .filter((choice) => choice.offered || choice.model === selectedModel)
        .map((choice) => ({ value: choice.model, label: choice.display_name }))
    // A stored model that has since left the catalog still needs to render as itself, not as blank.
    if (selectedModel && !effortsByModel.has(selectedModel)) {
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
                    const supported = effortsByModel.get(model) ?? []
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
                    options={efforts.map((effort) => ({ value: effort, label: EFFORT_LABELS[effort] ?? effort }))}
                    onChange={(effort) =>
                        onChange(effort ? { model: selectedModel, reasoning_effort: effort } : { model: selectedModel })
                    }
                    data-attr="task-model-picker-effort"
                />
            )}
        </div>
    )
}
