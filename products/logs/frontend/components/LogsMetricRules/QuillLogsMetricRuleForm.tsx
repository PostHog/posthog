import { useActions, useValues } from 'kea'
import { Field as KeaField, Form } from 'kea-forms'
import { useId } from 'react'

import {
    Button,
    DialogBody,
    DialogFooter,
    Field,
    FieldDescription,
    FieldLabel,
    FieldTitle,
    Input,
    Switch,
    Text,
    ToggleGroup,
    ToggleGroupItem,
} from '@posthog/quill'

import { TagsCombobox } from 'lib/components/Scenes/TagsCombobox'

import type { LogsFilterPreviewLookback } from 'products/logs/frontend/components/LogsFilterPreview/logsFilterVolumePreview'
import { LogsFilterVolumeSparkline } from 'products/logs/frontend/components/LogsFilterPreview/LogsFilterVolumeSparkline'
import { LogsMetricRuleApi } from 'products/logs/frontend/generated/api.schemas'

import { DropRuleFilterEditor } from '../LogsSampling/DropRuleFilterEditor'
import { GROUP_BY_SUGGESTIONS, logsMetricRuleFormLogic } from './logsMetricRuleFormLogic'
import { QuillLogsMetricRuleFormField } from './QuillLogsMetricRuleFormField'

const PREVIEW_LOOKBACK_OPTIONS: { value: LogsFilterPreviewLookback; dataAttr: string }[] = [
    { value: '1h', dataAttr: 'logs-metric-rule-preview-lookback-1h' },
    { value: '24h', dataAttr: 'logs-metric-rule-preview-lookback-24h' },
]

export interface QuillLogsMetricRuleFormProps {
    rule: LogsMetricRuleApi | null
    onCancel: () => void
}

export function QuillLogsMetricRuleForm({ rule, onCancel }: QuillLogsMetricRuleFormProps): JSX.Element {
    const logic = logsMetricRuleFormLogic({ rule, seed: null })
    const { metricRuleForm, isMetricRuleFormSubmitting, previewLookback } = useValues(logic)
    const { setMetricRuleFormValue, setPreviewLookback, submitAndAddAnother } = useActions(logic)
    const enabledId = useId()

    const isEdit = rule !== null
    const valueAttribute = metricRuleForm.value_attribute.trim()
    const savingReason = isMetricRuleFormSubmitting ? 'Saving…' : undefined

    return (
        <Form
            logic={logsMetricRuleFormLogic}
            props={{ rule, seed: null }}
            formKey="metricRuleForm"
            enableFormOnSubmit
            className="contents"
        >
            <DialogBody>
                <div className="flex flex-col gap-4">
                    <QuillLogsMetricRuleFormField name="name" label="Name">
                        {({ id, value, onChange, invalid }) => (
                            <Input
                                id={id}
                                value={value}
                                onChange={(event) => onChange(event.target.value)}
                                placeholder="API errors"
                                aria-invalid={invalid || undefined}
                            />
                        )}
                    </QuillLogsMetricRuleFormField>
                    <QuillLogsMetricRuleFormField
                        name="metric_name"
                        label="Metric name"
                        description={
                            isEdit
                                ? 'The metric name cannot be changed after creation. Create a new rule instead.'
                                : 'How the generated metric appears in the Metrics product.'
                        }
                    >
                        {({ id, value, onChange, invalid }) => (
                            <Input
                                id={id}
                                value={value}
                                onChange={(event) => onChange(event.target.value)}
                                placeholder="log.api_errors"
                                disabled={isEdit}
                                aria-invalid={invalid || undefined}
                            />
                        )}
                    </QuillLogsMetricRuleFormField>
                    <QuillLogsMetricRuleFormField
                        name="value_attribute"
                        label="Value attribute (optional)"
                        description={
                            isEdit
                                ? 'The value attribute cannot be changed after creation, since it determines the metric type.'
                                : 'Leave empty to count matching log lines. Set a numeric log attribute (e.g. `attributes.duration_ms`) to aggregate its value instead.'
                        }
                    >
                        {({ id, value, onChange, invalid }) => (
                            <Input
                                id={id}
                                value={value}
                                onChange={(event) => onChange(event.target.value)}
                                placeholder="attributes.duration_ms"
                                disabled={isEdit}
                                aria-invalid={invalid || undefined}
                            />
                        )}
                    </QuillLogsMetricRuleFormField>
                    <Field>
                        <FieldTitle>Filters</FieldTitle>
                        <FieldDescription>
                            Only log lines matching these filters feed the metric. Leave empty to match all logs.
                        </FieldDescription>
                        <DropRuleFilterEditor
                            filterGroup={metricRuleForm.filter_group}
                            onChange={(group) => setMetricRuleFormValue('filter_group', group)}
                            logicKey={`logs-metric-rule:${rule?.id ?? 'new'}`}
                        />
                        <div className="flex flex-wrap items-center justify-end gap-2">
                            <Text size="xs" variant="muted" render={<span />}>
                                Preview lookback
                            </Text>
                            <ToggleGroup
                                variant="outline"
                                aria-label="Preview lookback"
                                value={[previewLookback]}
                                onValueChange={(next: string[]) => {
                                    if (next[0]) {
                                        setPreviewLookback(next[0] as LogsFilterPreviewLookback)
                                    }
                                }}
                            >
                                {PREVIEW_LOOKBACK_OPTIONS.map((option) => (
                                    <ToggleGroupItem
                                        key={option.value}
                                        value={option.value}
                                        data-attr={option.dataAttr}
                                    >
                                        {option.value}
                                    </ToggleGroupItem>
                                ))}
                            </ToggleGroup>
                        </div>
                        <LogsFilterVolumeSparkline
                            filterGroup={metricRuleForm.filter_group}
                            metric="count"
                            lookback={previewLookback}
                            renderCaption={() =>
                                valueAttribute ? (
                                    <Text size="xs" variant="muted" render={<span />}>
                                        The preview counts matching log lines. The metric will aggregate{' '}
                                        <code>{valueAttribute}</code> from these lines.
                                    </Text>
                                ) : null
                            }
                        />
                    </Field>
                    <QuillLogsMetricRuleFormField
                        name="group_by"
                        label="Group by (optional)"
                        description="Each distinct value combination becomes its own metric series. Avoid high-cardinality keys like user or request IDs."
                    >
                        {({ value, onChange }) => (
                            <TagsCombobox
                                value={value}
                                onChange={onChange}
                                options={GROUP_BY_SUGGESTIONS}
                                customValueNoun="key"
                                placeholder="service_name, severity_text, attributes.…"
                            />
                        )}
                    </QuillLogsMetricRuleFormField>
                    <KeaField name="enabled" noStyle>
                        {({ value, onChange }) => (
                            <Field orientation="horizontal" className="w-fit">
                                <Switch id={enabledId} checked={value} onCheckedChange={onChange} />
                                <FieldLabel htmlFor={enabledId}>Enabled</FieldLabel>
                            </Field>
                        )}
                    </KeaField>
                </div>
            </DialogBody>
            <DialogFooter className="flex-wrap">
                <Button variant="outline" onClick={onCancel}>
                    Cancel
                </Button>
                {!isEdit && (
                    <Button
                        variant="outline"
                        onClick={submitAndAddAnother}
                        loading={isMetricRuleFormSubmitting}
                        disabledReason={savingReason}
                        data-attr="logs-metric-rule-create-and-add-another"
                    >
                        Create and add another
                    </Button>
                )}
                <Button
                    variant="primary"
                    type="submit"
                    loading={isMetricRuleFormSubmitting}
                    disabledReason={savingReason}
                >
                    {isEdit ? 'Save changes' : 'Create log-based metric'}
                </Button>
            </DialogFooter>
        </Form>
    )
}
