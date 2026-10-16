import { useActions, useValues } from 'kea'

import { IconTrash } from '@posthog/icons'
import {
    LemonButton,
    LemonCheckbox,
    LemonInput,
    LemonInputSelect,
    LemonSegmentedButton,
    LemonTag,
    LemonTextArea,
    Spinner,
} from '@posthog/lemon-ui'

import { IconArrowDown, IconArrowUp } from 'lib/lemon-ui/icons'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import type { MetricsDashboardVariable, MetricsDashboardVariableSource } from '~/queries/schema/schema-general'

import { metricVariableEditorLogic } from './metricVariableEditorLogic'
import { ownValue } from './metricVariables'

const QUERY_PLACEHOLDERS: Record<'promql' | 'sql', string> = {
    promql: 'label_values(up{job=~"$job"}, instance)',
    sql: "SELECT DISTINCT attribute_value FROM posthog.metric_attributes WHERE attribute_key = 'http.route'",
}
const QUERY_HELP: Record<'promql' | 'sql', string> = {
    promql: 'Use label_values(label), label_values(selector, label), label_names(), metrics(regex) or query_result(expr).',
    sql: 'The first column gives the values. {date_from} and {date_to} are the dashboard date range.',
}
const PREVIEW_LIMIT = 60

/** The settings of the selected dashboard variable in the variable editor. */
export function MetricVariableForm({ variable }: { variable: MetricsDashboardVariable }): JSX.Element {
    const { draft, selectedIndex, shownErrors, preview, previewError, previewLoading } =
        useValues(metricVariableEditorLogic)
    const { updateVariable, removeVariable, moveVariable } = useActions(metricVariableEditorLogic)
    const update = (patch: Partial<MetricsDashboardVariable>): void => updateVariable(selectedIndex, patch)
    const error = ownValue(shownErrors, variable.name)
    const references = [`$${variable.name}`, `\${${variable.name}:regex}`, `\${${variable.name}:csv}`]

    return (
        <div className="flex flex-col gap-4 flex-1 min-w-0">
            <div className="flex items-start gap-2">
                <div className="flex flex-col gap-1 flex-1 min-w-0">
                    <h3 className="font-mono m-0 truncate">${variable.name}</h3>
                    <div className="flex items-center gap-1 flex-wrap text-xs text-secondary">
                        Use in a tile:
                        {references.map((reference) => (
                            <LemonTag
                                key={reference}
                                className="font-mono cursor-pointer"
                                onClick={() => void copyToClipboard(reference, 'variable reference')}
                            >
                                {reference}
                            </LemonTag>
                        ))}
                    </div>
                </div>
                <LemonButton
                    size="small"
                    icon={<IconArrowUp />}
                    tooltip="Move up"
                    disabledReason={selectedIndex === 0 ? 'This is the first variable' : undefined}
                    onClick={() => moveVariable(selectedIndex, -1)}
                />
                <LemonButton
                    size="small"
                    icon={<IconArrowDown />}
                    tooltip="Move down"
                    disabledReason={selectedIndex === draft.length - 1 ? 'This is the last variable' : undefined}
                    onClick={() => moveVariable(selectedIndex, 1)}
                />
                <LemonButton
                    size="small"
                    status="danger"
                    icon={<IconTrash />}
                    tooltip="Remove variable"
                    onClick={() => removeVariable(selectedIndex)}
                    data-attr="dashboard-metric-variable-remove"
                />
            </div>
            <div className="grid grid-cols-2 gap-3">
                <LemonField.Pure label="Name" error={error?.field === 'name' ? error.message : undefined}>
                    <LemonInput
                        className="font-mono"
                        value={variable.name}
                        onChange={(name) => update({ name: name.trim() })}
                    />
                </LemonField.Pure>
                <LemonField.Pure label="Label" info="Shown above the select on the dashboard">
                    <LemonInput
                        value={variable.label ?? ''}
                        placeholder={variable.name}
                        onChange={(label) => update({ label: label || null })}
                    />
                </LemonField.Pure>
            </div>
            <LemonField.Pure label="Values from">
                <LemonSegmentedButton<MetricsDashboardVariableSource>
                    size="small"
                    value={variable.source}
                    onChange={(source) => update({ source })}
                    options={[
                        { value: 'custom', label: 'List' },
                        { value: 'promql', label: 'PromQL query' },
                        { value: 'sql', label: 'SQL query' },
                        { value: 'textbox', label: 'Text input' },
                    ]}
                />
            </LemonField.Pure>
            {variable.source === 'custom' && (
                <LemonField.Pure
                    label="Values"
                    help="Type a value and press Enter"
                    error={error?.field === 'values' ? error.message : undefined}
                >
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
                        help={`${QUERY_HELP[variable.source]} Refer to other variables as $name.`}
                        error={error?.field === 'query' ? error.message : undefined}
                    >
                        <LemonTextArea
                            className="font-mono text-xs"
                            minRows={2}
                            value={variable.query ?? ''}
                            placeholder={QUERY_PLACEHOLDERS[variable.source]}
                            onChange={(query) => update({ query })}
                        />
                    </LemonField.Pure>
                    <LemonField.Pure
                        label="Regex"
                        showOptional
                        info="Keeps the values that match. With a capture group, the value is the first group."
                    >
                        <LemonInput
                            className="font-mono"
                            value={variable.regex ?? ''}
                            placeholder="/api-(.*)/"
                            onChange={(regex) => update({ regex: regex || null })}
                        />
                    </LemonField.Pure>
                </>
            )}
            {variable.source === 'textbox' ? (
                <p className="text-secondary text-sm m-0">
                    People type a value on the dashboard. The value goes into the queries as written.
                </p>
            ) : (
                <>
                    <div className="flex gap-x-4 gap-y-2 flex-wrap items-center">
                        <LemonCheckbox
                            checked={!!variable.multi}
                            onChange={(multi) => update({ multi: multi || null })}
                            label="Allow more than one value"
                        />
                        <LemonCheckbox
                            checked={!!variable.includeAll}
                            onChange={(includeAll) => update({ includeAll: includeAll || null })}
                            label="Include All"
                        />
                        {variable.includeAll && (
                            <LemonInput
                                size="small"
                                className="font-mono w-48"
                                value={variable.allValue ?? ''}
                                placeholder="Value for All (default .*)"
                                onChange={(allValue) => update({ allValue: allValue || null })}
                            />
                        )}
                    </div>
                    {error?.field === 'allValue' && <p className="text-danger text-sm m-0">{error.message}</p>}
                    {(variable.source === 'promql' || variable.source === 'sql') && (
                        <div className="flex flex-col gap-1 border-t border-primary pt-3">
                            <span className="flex items-center gap-2 text-sm font-semibold">
                                Values preview
                                {previewLoading && <Spinner textColored />}
                                {preview && !previewLoading && (
                                    <span className="text-xs text-secondary font-normal">
                                        {preview.length > PREVIEW_LIMIT
                                            ? `First ${PREVIEW_LIMIT} of ${preview.length}`
                                            : `${preview.length} ${preview.length === 1 ? 'value' : 'values'}`}
                                    </span>
                                )}
                            </span>
                            {previewError ? (
                                <p className="text-danger text-sm m-0">{previewError}</p>
                            ) : preview?.length ? (
                                <div className="flex flex-wrap gap-1 max-h-28 overflow-y-auto">
                                    {preview.slice(0, PREVIEW_LIMIT).map((option) => (
                                        <LemonTag key={option} className="font-mono">
                                            {option}
                                        </LemonTag>
                                    ))}
                                </div>
                            ) : (
                                <p className="text-secondary text-sm m-0">
                                    {preview
                                        ? 'No values. Check the query and the regex.'
                                        : 'Values show here when the query is complete.'}
                                </p>
                            )}
                        </div>
                    )}
                </>
            )}
        </div>
    )
}
