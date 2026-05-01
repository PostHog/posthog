import { BindLogic, useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTag } from '@posthog/lemon-ui'
import type { LemonTableColumns } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { urls } from 'scenes/urls'

import { RuleTypeEnumApi } from 'products/logs/frontend/generated/api.schemas'
import { LogsFeatureFlagKeys } from 'products/logs/frontend/logsFeatureFlagKeys'

import { logsSamplingSectionLogic } from './logsSamplingSectionLogic'

export function LogsSamplingSection(): JSX.Element | null {
    const enabled = useFeatureFlag(LogsFeatureFlagKeys.samplingRules)
    if (!enabled) {
        return null
    }
    return (
        <BindLogic logic={logsSamplingSectionLogic} props={{}}>
            <div className="space-y-3">
                <p className="text-muted m-0">
                    Drop or sample logs before storage using ordered rules. Evaluation runs in ingestion after scrubbing
                    and optional JSON parse. See the public logs docs for ingestion and retention.
                </p>
                <LogsSamplingSectionTable />
            </div>
        </BindLogic>
    )
}

function ruleTypeLabel(t: RuleTypeEnumApi): string {
    if (t === RuleTypeEnumApi.SeveritySampling) {
        return 'Severity sampling'
    }
    if (t === RuleTypeEnumApi.PathDrop) {
        return 'Path drop'
    }
    return 'Rate limit'
}

function LogsSamplingSectionTable(): JSX.Element {
    const { rules, rulesLoading } = useValues(logsSamplingSectionLogic)
    const { loadRules } = useActions(logsSamplingSectionLogic)

    const columns: LemonTableColumns<(typeof rules)[0]> = [
        {
            title: 'Name',
            dataIndex: 'name',
            render: (_, row) => (
                <LemonButton
                    size="small"
                    type="tertiary"
                    to={urls.logsSamplingDetail(row.id)}
                    data-attr="logs-sampling-rule-link"
                >
                    <strong>{row.name}</strong>
                </LemonButton>
            ),
        },
        {
            title: 'Type',
            dataIndex: 'rule_type',
            render: (_, row) => ruleTypeLabel(row.rule_type),
        },
        {
            title: 'Priority',
            dataIndex: 'priority',
            width: 90,
        },
        {
            title: 'Status',
            dataIndex: 'enabled',
            width: 100,
            render: (_, row) =>
                row.enabled ? <LemonTag type="success">Enabled</LemonTag> : <LemonTag type="muted">Disabled</LemonTag>,
        },
    ]

    return (
        <div>
            <div className="flex justify-end mb-2">
                <LemonButton type="primary" icon={<IconPlus />} to={urls.logsSamplingNew()}>
                    New sampling rule
                </LemonButton>
            </div>
            <LemonTable
                columns={columns}
                dataSource={rules}
                loading={rulesLoading}
                emptyState="No sampling rules yet"
                rowKey="id"
                size="small"
            />
            <div className="mt-2">
                <LemonButton size="small" type="secondary" onClick={() => loadRules()}>
                    Refresh list
                </LemonButton>
            </div>
        </div>
    )
}
