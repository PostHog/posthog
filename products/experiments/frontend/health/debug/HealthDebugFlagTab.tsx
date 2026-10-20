import { useValues } from 'kea'

import { LemonBanner, LemonTable } from '@posthog/lemon-ui'

import { experimentLogic } from 'scenes/experiments/experimentLogic'

import { SetupFactsTable } from '../../setupInspector/SetupFactsTable'
import { formatCount, formatYesNo } from '../../setupInspector/setupInspectorUtils'
import { experimentHealthDebugLogic } from './experimentHealthDebugLogic'
import type { HealthDebugFlagChange, HealthDebugReleaseCondition } from './healthDebugInputs'
import { HealthDebugSection } from './HealthDebugSection'

export function HealthDebugFlagTab(): JSX.Element {
    const { experimentId } = useValues(experimentLogic)
    const {
        flagFacts,
        releaseConditions,
        flagHistoryFacts,
        flagChanges,
        trafficFacts,
        healthInputs,
        healthInputsLoading,
        healthInputsError,
    } = useValues(experimentHealthDebugLogic({ experimentId }))
    const trafficRead = !!healthInputs?.condition_set_traffic
    const flagHistoryChecked = !!healthInputs?.flag_history?.checked

    return (
        <div className="flex flex-col gap-4">
            {healthInputsError && <LemonBanner type="error">{healthInputsError}</LemonBanner>}
            <HealthDebugSection
                title="Configuration"
                description="The flag as the health checks read it on the server."
            >
                <SetupFactsTable facts={flagFacts} />
                <LemonTable<HealthDebugReleaseCondition>
                    size="small"
                    loading={healthInputsLoading}
                    dataSource={releaseConditions}
                    rowKey="number"
                    emptyState="No release conditions."
                    columns={[
                        { title: 'Set', key: 'number', render: (_, condition) => condition.number },
                        {
                            title: 'Rollout',
                            key: 'rollout',
                            align: 'right',
                            render: (_, condition) =>
                                condition.rolloutPercentage === null ? 'Unset' : `${condition.rolloutPercentage}%`,
                        },
                        {
                            title: 'Properties',
                            key: 'properties',
                            align: 'right',
                            render: (_, condition) => condition.propertyCount ?? 'Unknown',
                        },
                        {
                            title: 'Reachable',
                            key: 'reachable',
                            render: (_, condition) => formatYesNo(condition.reachable),
                        },
                        {
                            title: 'Pinned variant',
                            key: 'pinned',
                            render: (_, condition) =>
                                condition.pinnedVariant ? (
                                    <code translate="no">{condition.pinnedVariant}</code>
                                ) : (
                                    <span className="text-secondary">None</span>
                                ),
                        },
                        ...(trafficRead
                            ? [
                                  {
                                      title: 'People in the window',
                                      key: 'people',
                                      align: 'right' as const,
                                      render: (_: unknown, condition: HealthDebugReleaseCondition) =>
                                          formatCount(condition.people),
                                  },
                              ]
                            : []),
                    ]}
                />
            </HealthDebugSection>
            <HealthDebugSection
                title="Changes since launch"
                description="What the split, bucketing and release-condition checks read from the flag's history."
            >
                <SetupFactsTable facts={flagHistoryFacts} />
                {flagChanges.length > 0 && (
                    <LemonTable<HealthDebugFlagChange>
                        size="small"
                        dataSource={flagChanges}
                        rowKey={(change, index) => `${change.changedAt}-${index}`}
                        columns={[
                            { title: 'Changed at', dataIndex: 'changedAt' },
                            { title: 'Changed', dataIndex: 'changed' },
                            { title: 'Before', dataIndex: 'before' },
                            { title: 'After', dataIndex: 'after' },
                            ...(flagHistoryChecked
                                ? [
                                      {
                                          title: 'Counts',
                                          key: 'counted',
                                          render: (_: unknown, change: HealthDebugFlagChange) =>
                                              formatYesNo(change.counted),
                                      },
                                  ]
                                : []),
                        ]}
                    />
                )}
            </HealthDebugSection>
            <HealthDebugSection
                title="Calls by release condition"
                description="The flag's recent calls that the forced-variant and release-condition checks grade overrides by."
            >
                <SetupFactsTable facts={trafficFacts} />
            </HealthDebugSection>
        </div>
    )
}
