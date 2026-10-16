import { useActions, useValues } from 'kea'

import {
    LemonButton,
    LemonCheckbox,
    LemonInput,
    LemonInputSelect,
    LemonSegmentedButton,
    LemonTag,
    LemonTextArea,
} from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import type { MetricsDashboardVariable, MetricsDashboardVariableSource } from '~/queries/schema/schema-general'

import { metricVariableEditorLogic } from './metricVariableEditorLogic'

const QUERY_PLACEHOLDERS: Record<'promql' | 'sql', string> = {
    promql: 'label_values(up{job="$job"}, instance)',
    sql: 'SELECT DISTINCT service_name FROM posthog.metrics WHERE timestamp >= {date_from}',
}

/** The settings of the selected dashboard variable in the variable editor. */
export function MetricVariableForm({ variable }: { variable: MetricsDashboardVariable }): JSX.Element {
    const { selectedIndex, errors, preview, previewLoading } = useValues(metricVariableEditorLogic)
    const { updateVariable, loadPreview } = useActions(metricVariableEditorLogic)
    const update = (patch: Partial<MetricsDashboardVariable>): void => updateVariable(selectedIndex, patch)

    return (
        <div className="flex flex-col gap-3 flex-1 min-w-0">
            <div className="flex gap-2 flex-wrap">
                <LemonField.Pure
                    label="Name"
                    help={`Queries refer to it as $${variable.name}`}
                    error={errors[variable.name]}
                    className="flex-1 min-w-40"
                >
                    <LemonInput value={variable.name} onChange={(name) => update({ name: name.trim() })} />
                </LemonField.Pure>
                <LemonField.Pure label="Label" help="Shown on the dashboard" className="flex-1 min-w-40">
                    <LemonInput
                        value={variable.label ?? ''}
                        placeholder={variable.name}
                        onChange={(label) => update({ label: label || null })}
                    />
                </LemonField.Pure>
            </div>
            <LemonField.Pure label="Options from">
                <LemonSegmentedButton<MetricsDashboardVariableSource>
                    size="small"
                    value={variable.source}
                    onChange={(source) => update({ source })}
                    options={[
                        { value: 'custom', label: 'List' },
                        { value: 'promql', label: 'PromQL' },
                        { value: 'sql', label: 'SQL' },
                        { value: 'textbox', label: 'Text input' },
                    ]}
                />
            </LemonField.Pure>
            {variable.source === 'custom' && (
                <LemonField.Pure label="Values" help="Type a value and press Enter">
                    <LemonInputSelect
                        mode="multiple"
                        allowCustomValues
                        value={variable.customValues ?? []}
                        onChange={(customValues) => update({ customValues })}
                        placeholder="production, staging"
                    />
                </LemonField.Pure>
            )}
            {(variable.source === 'promql' || variable.source === 'sql') && (
                <>
                    <LemonField.Pure
                        label="Query"
                        help={
                            variable.source === 'promql'
                                ? 'Use label_values(label), label_values(selector, label), label_names(), metrics(regex) or query_result(expr). Refer to other variables as $name.'
                                : 'The first column gives the options. Refer to other variables as $name.'
                        }
                    >
                        <LemonTextArea
                            className="font-mono"
                            value={variable.query ?? ''}
                            placeholder={QUERY_PLACEHOLDERS[variable.source]}
                            onChange={(query) => update({ query })}
                        />
                    </LemonField.Pure>
                    <LemonField.Pure
                        label="Regex"
                        help="Optional. Keeps the options that match. With a capture group, the option is the first group."
                    >
                        <LemonInput
                            className="font-mono"
                            value={variable.regex ?? ''}
                            placeholder="api-(.*)"
                            onChange={(regex) => update({ regex: regex || null })}
                        />
                    </LemonField.Pure>
                </>
            )}
            {variable.source !== 'textbox' && (
                <div className="flex gap-4 flex-wrap items-center">
                    <LemonCheckbox
                        checked={!!variable.multi}
                        onChange={(multi) => update({ multi: multi || null })}
                        label="Select more than one value"
                    />
                    <LemonCheckbox
                        checked={!!variable.includeAll}
                        onChange={(includeAll) => update({ includeAll: includeAll || null })}
                        label="Include All"
                    />
                    {variable.includeAll && (
                        <LemonInput
                            size="small"
                            className="font-mono w-40"
                            value={variable.allValue ?? ''}
                            placeholder=".*"
                            onChange={(allValue) => update({ allValue: allValue || null })}
                        />
                    )}
                </div>
            )}
            {variable.source !== 'textbox' && (
                <div className="flex flex-col gap-1">
                    <div className="flex items-center gap-2">
                        <LemonButton
                            size="small"
                            type="secondary"
                            loading={previewLoading}
                            onClick={loadPreview}
                            data-attr="dashboard-metric-variable-preview"
                        >
                            Preview values
                        </LemonButton>
                        {preview && <span className="text-xs text-secondary">{preview.length} values</span>}
                    </div>
                    {preview && (
                        <div className="flex flex-wrap gap-1 max-h-24 overflow-y-auto">
                            {preview.length ? (
                                preview.slice(0, 50).map((option) => <LemonTag key={option}>{option}</LemonTag>)
                            ) : (
                                <span className="text-xs text-secondary">
                                    No values. Check the query and the regex.
                                </span>
                            )}
                        </div>
                    )}
                </div>
            )}
        </div>
    )
}
