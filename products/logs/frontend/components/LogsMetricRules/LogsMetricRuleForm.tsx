import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonInput, LemonInputSelect, LemonSegmentedButton, LemonSwitch } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import type { LogsFilterPreviewLookback } from 'products/logs/frontend/components/LogsFilterPreview/logsFilterVolumePreview'
import { LogsFilterVolumeSparkline } from 'products/logs/frontend/components/LogsFilterPreview/LogsFilterVolumeSparkline'
import { LogsMetricRuleApi } from 'products/logs/frontend/generated/api.schemas'

import { DropRuleFilterEditor } from '../LogsSampling/DropRuleFilterEditor'
import { GROUP_BY_SUGGESTIONS, logsMetricRuleFormLogic } from './logsMetricRuleFormLogic'
import type { LogsMetricRuleSeed } from './metricRuleSeed'

export interface LogsMetricRuleFormProps {
    rule: LogsMetricRuleApi | null
    seed?: LogsMetricRuleSeed | null
    onCancel: () => void
}

export function LogsMetricRuleForm({ rule, seed = null, onCancel }: LogsMetricRuleFormProps): JSX.Element {
    const logic = logsMetricRuleFormLogic({ rule, seed })
    const { metricRuleForm, isMetricRuleFormSubmitting, previewLookback } = useValues(logic)
    const { setMetricRuleFormValue, setPreviewLookback, submitAndAddAnother } = useActions(logic)

    const isEdit = rule !== null
    const valueAttribute = metricRuleForm.value_attribute.trim()

    return (
        <Form logic={logsMetricRuleFormLogic} props={{ rule, seed }} formKey="metricRuleForm" enableFormOnSubmit>
            <div className="space-y-4">
                <LemonField name="name" label="Name">
                    <LemonInput placeholder="API errors" />
                </LemonField>
                <LemonField
                    name="metric_name"
                    label="Metric name"
                    help={
                        isEdit
                            ? 'The metric name cannot be changed after creation. Create a new rule instead.'
                            : 'How the generated metric appears in the Metrics product.'
                    }
                >
                    <LemonInput placeholder="log.api_errors" disabled={isEdit} />
                </LemonField>
                <LemonField
                    name="value_attribute"
                    label="Value attribute (optional)"
                    help={
                        isEdit
                            ? 'The value attribute cannot be changed after creation, since it determines the metric type.'
                            : 'Leave empty to count matching log lines. Set a numeric log attribute (e.g. `attributes.duration_ms`) to aggregate its value instead.'
                    }
                >
                    <LemonInput placeholder="attributes.duration_ms" disabled={isEdit} />
                </LemonField>
                <div className="space-y-1">
                    <label className="font-semibold">Filters</label>
                    <p className="text-muted text-xs m-0">
                        Only log lines matching these filters feed the metric. Leave empty to match all logs.
                    </p>
                    <DropRuleFilterEditor
                        filterGroup={metricRuleForm.filter_group}
                        onChange={(group) => setMetricRuleFormValue('filter_group', group)}
                        logicKey={`logs-metric-rule:${rule?.id ?? seed?.seedKey ?? 'new'}`}
                    />
                    <div className="flex items-center justify-end gap-2 mt-2">
                        <span className="text-xs text-muted">Preview lookback</span>
                        <LemonSegmentedButton
                            size="xsmall"
                            value={previewLookback}
                            onChange={(value) => setPreviewLookback(value as LogsFilterPreviewLookback)}
                            options={[
                                { value: '1h', label: '1h', 'data-attr': 'logs-metric-rule-preview-lookback-1h' },
                                { value: '24h', label: '24h', 'data-attr': 'logs-metric-rule-preview-lookback-24h' },
                            ]}
                        />
                    </div>
                    <LogsFilterVolumeSparkline
                        filterGroup={metricRuleForm.filter_group}
                        metric="count"
                        lookback={previewLookback}
                        renderCaption={() =>
                            valueAttribute ? (
                                <span className="text-xs text-muted">
                                    The preview counts matching log lines. The metric will aggregate{' '}
                                    <code>{valueAttribute}</code> from these lines.
                                </span>
                            ) : null
                        }
                    />
                </div>
                <LemonField
                    name="group_by"
                    label="Group by (optional)"
                    help="Each distinct value combination becomes its own metric series. Avoid high-cardinality keys like user or request IDs."
                >
                    {({ value, onChange }) => (
                        <LemonInputSelect
                            mode="multiple"
                            allowCustomValues
                            value={value}
                            onChange={onChange}
                            options={GROUP_BY_SUGGESTIONS.map((key) => ({ key, label: key }))}
                            placeholder="service_name, severity_text, attributes.…"
                        />
                    )}
                </LemonField>
                <LemonField name="enabled">
                    {({ value, onChange }) => (
                        <LemonSwitch checked={value} onChange={onChange} label="Enabled" bordered />
                    )}
                </LemonField>
                <div className="flex justify-end gap-2">
                    <LemonButton type="secondary" onClick={onCancel}>
                        Cancel
                    </LemonButton>
                    {!isEdit && (
                        <LemonButton
                            type="secondary"
                            onClick={submitAndAddAnother}
                            loading={isMetricRuleFormSubmitting}
                            disabledReason={isMetricRuleFormSubmitting ? 'Saving…' : undefined}
                            data-attr="logs-metric-rule-create-and-add-another"
                        >
                            Create and add another
                        </LemonButton>
                    )}
                    <LemonButton
                        type="primary"
                        htmlType="submit"
                        loading={isMetricRuleFormSubmitting}
                        disabledReason={isMetricRuleFormSubmitting ? 'Saving…' : undefined}
                    >
                        {isEdit ? 'Save changes' : 'Create log-based metric'}
                    </LemonButton>
                </div>
            </div>
        </Form>
    )
}
