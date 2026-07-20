import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import {
    LemonButton,
    LemonInput,
    LemonInputSelect,
    LemonModal,
    LemonSwitch,
    LemonTable,
    LemonTag,
} from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { LogsMetricRuleApi } from 'products/logs/frontend/generated/api.schemas'
import { LogsFeatureFlagKeys } from 'products/logs/frontend/logsFeatureFlagKeys'

import { DropRuleFilterEditor } from '../LogsSampling/DropRuleFilterEditor'
import { GROUP_BY_SUGGESTIONS, logsMetricRuleFormLogic } from './logsMetricRuleFormLogic'
import { logsMetricRulesSectionLogic } from './logsMetricRulesSectionLogic'

export function LogsMetricRulesSection(): JSX.Element | null {
    const enabled = useFeatureFlag(LogsFeatureFlagKeys.metricRules)
    if (!enabled) {
        return null
    }
    return (
        <BindLogic logic={logsMetricRulesSectionLogic} props={{}}>
            <div className="space-y-3">
                <p className="text-muted m-0">
                    Generate metrics from your logs at ingestion time. Count log lines matching a filter, or aggregate a
                    numeric log attribute, and use the result in dashboards, alerts, and queries in the Metrics product.
                    Metrics are computed before drop rules, so you can drop noisy logs and keep the trend.
                </p>
                <LogsMetricRulesTable />
                <LogsMetricRuleModal />
            </div>
        </BindLogic>
    )
}

function LogsMetricRulesTable(): JSX.Element {
    const { rules, rulesLoading } = useValues(logsMetricRulesSectionLogic)
    const { openNewRuleModal, openEditRuleModal, deleteRule, setRuleEnabled } = useActions(logsMetricRulesSectionLogic)

    return (
        <div className="space-y-2">
            <LemonTable
                dataSource={rules}
                loading={rulesLoading}
                rowKey="id"
                emptyState="No metric rules yet. Create one to start generating metrics from your logs."
                columns={[
                    {
                        title: 'Name',
                        key: 'name',
                        render: (_, rule: LogsMetricRuleApi) => <span className="font-medium">{rule.name}</span>,
                    },
                    {
                        title: 'Metric',
                        key: 'metric_name',
                        render: (_, rule: LogsMetricRuleApi) => <code>{rule.metric_name}</code>,
                    },
                    {
                        title: 'Type',
                        key: 'type',
                        render: (_, rule: LogsMetricRuleApi) =>
                            rule.value_attribute ? (
                                <LemonTag type="highlight">{rule.value_attribute}</LemonTag>
                            ) : (
                                <LemonTag>count</LemonTag>
                            ),
                    },
                    {
                        title: 'Group by',
                        key: 'group_by',
                        render: (_, rule: LogsMetricRuleApi) =>
                            rule.group_by?.length ? rule.group_by.join(', ') : <span className="text-muted">—</span>,
                    },
                    {
                        title: 'Enabled',
                        key: 'enabled',
                        render: (_, rule: LogsMetricRuleApi) => (
                            <LemonSwitch
                                checked={rule.enabled ?? false}
                                onChange={(checked) => setRuleEnabled(rule, checked)}
                            />
                        ),
                    },
                    {
                        key: 'actions',
                        width: 0,
                        render: (_, rule: LogsMetricRuleApi) => (
                            <More
                                overlay={
                                    <>
                                        <LemonButton fullWidth onClick={() => openEditRuleModal(rule)}>
                                            Edit
                                        </LemonButton>
                                        <LemonButton fullWidth status="danger" onClick={() => deleteRule(rule)}>
                                            Delete
                                        </LemonButton>
                                    </>
                                }
                            />
                        ),
                    },
                ]}
            />
            <LemonButton type="primary" onClick={openNewRuleModal}>
                New metric rule
            </LemonButton>
        </div>
    )
}

function LogsMetricRuleModal(): JSX.Element | null {
    const { ruleModalOpen, editingRule } = useValues(logsMetricRulesSectionLogic)
    const { closeRuleModal } = useActions(logsMetricRulesSectionLogic)

    if (!ruleModalOpen) {
        return null
    }
    return (
        <LemonModal
            isOpen
            onClose={closeRuleModal}
            title={editingRule ? 'Edit metric rule' : 'New metric rule'}
            width={720}
            footer={null}
        >
            <LogsMetricRuleForm rule={editingRule} />
        </LemonModal>
    )
}

function LogsMetricRuleForm({ rule }: { rule: LogsMetricRuleApi | null }): JSX.Element {
    const logic = logsMetricRuleFormLogic({ rule })
    const { metricRuleForm, isMetricRuleFormSubmitting } = useValues(logic)
    const { setMetricRuleFormValue } = useActions(logic)
    const { closeRuleModal } = useActions(logsMetricRulesSectionLogic)

    const isEdit = rule !== null

    return (
        <Form logic={logsMetricRuleFormLogic} props={{ rule }} formKey="metricRuleForm" enableFormOnSubmit>
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
                        logicKey={`logs-metric-rule:${rule?.id ?? 'new'}`}
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
                    <LemonButton type="secondary" onClick={closeRuleModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        htmlType="submit"
                        loading={isMetricRuleFormSubmitting}
                        disabledReason={isMetricRuleFormSubmitting ? 'Saving…' : undefined}
                    >
                        {isEdit ? 'Save changes' : 'Create metric rule'}
                    </LemonButton>
                </div>
            </div>
        </Form>
    )
}
