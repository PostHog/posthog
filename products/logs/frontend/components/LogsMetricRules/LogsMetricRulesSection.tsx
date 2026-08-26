import { BindLogic, useActions, useValues } from 'kea'

import { LemonButton, LemonSwitch, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { More } from 'lib/lemon-ui/LemonButton/More'

import { LogsMetricRuleApi } from 'products/logs/frontend/generated/api.schemas'
import { LogsFeatureFlagKeys } from 'products/logs/frontend/logsFeatureFlagKeys'

import { LogsMetricRuleModal } from './LogsMetricRuleModal'
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
                emptyState="No log-based metrics yet. Create one to start generating metrics from your logs."
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
                New log-based metric
            </LemonButton>
        </div>
    )
}
