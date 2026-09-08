import { useValues } from 'kea'
import { useMemo } from 'react'

import { LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { modelCatalogueLogic } from 'products/posthog_ai/frontend/logics/modelCatalogueLogic'
import {
    filterEffortForModel,
    getEffortsForModel,
    getRuntimeAdapterLabel,
    listRuntimeAdapters,
    modelsForRuntimeAdapter,
} from 'products/posthog_ai/frontend/utils/composerModels'

import type { AIRunPreferenceDraft } from '../utils/aiRunPreferenceDraft'

export function AIRunPreferenceEditor({
    draft,
    dirty,
    saving,
    inheritLabel,
    onChange,
    onSave,
    onReset,
    canReset,
    restrictionReason,
    dataAttrPrefix = 'task-agent-default',
}: {
    draft: AIRunPreferenceDraft
    dirty: boolean
    saving: boolean
    inheritLabel: string
    onChange: (draft: Partial<AIRunPreferenceDraft>) => void
    onSave: () => void
    onReset?: () => void
    canReset?: boolean
    /** Set when the viewer may not edit this level, which disables every control here. */
    restrictionReason?: string | null
    dataAttrPrefix?: string
}): JSX.Element {
    const { catalogue } = useValues(modelCatalogueLogic)

    // Grouped by harness off the same catalogue the composer renders, so a model you can pick for a
    // run is always settable as a default and vice versa — including the Codex models that only
    // Slack and PostHog Desktop drive today.
    const modelOptions = useMemo(
        () =>
            listRuntimeAdapters(catalogue).map((adapter) => ({
                title: getRuntimeAdapterLabel(adapter),
                options: modelsForRuntimeAdapter(catalogue, adapter).map((choice) => ({
                    value: choice.model,
                    label: choice.display_name,
                })),
            })),
        [catalogue]
    )
    const effortOptions = useMemo(() => getEffortsForModel(catalogue, draft.model), [catalogue, draft.model])

    return (
        <div className="flex flex-wrap items-end gap-2">
            <LemonField.Pure label="Model" className="min-w-60">
                <LemonSelect
                    fullWidth
                    value={draft.model}
                    onChange={(model) =>
                        onChange({
                            model,
                            // A model switch may invalidate the picked effort; drop it rather than store one
                            // the model can't run, and let the server-side default apply instead.
                            reasoning_effort:
                                draft.reasoning_effort && model
                                    ? filterEffortForModel(catalogue, draft.reasoning_effort, model)
                                    : null,
                        })
                    }
                    options={[{ options: [{ value: null as string | null, label: inheritLabel }] }, ...modelOptions]}
                    placeholder={inheritLabel}
                    disabledReason={restrictionReason ?? (saving ? 'Saving…' : undefined)}
                    data-attr={`${dataAttrPrefix}-model`}
                />
            </LemonField.Pure>
            <LemonField.Pure label="Reasoning effort" className="min-w-48">
                <LemonSelect
                    fullWidth
                    value={draft.reasoning_effort}
                    onChange={(reasoning_effort) => onChange({ reasoning_effort })}
                    options={[
                        { value: null as string | null, label: 'Default effort' },
                        ...effortOptions.map(({ value, label }) => ({ value: value as string, label })),
                    ]}
                    disabledReason={
                        restrictionReason ?? (saving ? 'Saving…' : draft.model ? undefined : 'Pick a model first')
                    }
                    data-attr={`${dataAttrPrefix}-effort`}
                />
            </LemonField.Pure>
            <LemonButton
                type="primary"
                onClick={onSave}
                loading={saving}
                disabledReason={restrictionReason ?? (dirty ? undefined : 'No changes to save')}
            >
                Save
            </LemonButton>
            {onReset && (
                <LemonButton
                    type="secondary"
                    onClick={onReset}
                    loading={saving}
                    disabledReason={canReset ? undefined : 'Already using the project default'}
                >
                    Reset to project default
                </LemonButton>
            )}
        </div>
    )
}
