import { useActions, useValues } from 'kea'

import { LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyLargeNumber } from 'lib/utils/numbers'
import { tryDecodeURIComponent } from 'lib/utils/url'

import { WebAgentAnalyticsQueryType } from '~/queries/schema/schema-general'

import { AgentIssue, IssueVariant, agentAnalyticsLogic } from './agentAnalyticsLogic'
import { AgentQueryError } from './AgentQueryError'

const variantColumns: LemonTableColumns<IssueVariant> = [
    {
        title: 'Requested URL',
        key: 'variant',
        render: (_, variant) => <span className="font-mono text-xs">{tryDecodeURIComponent(variant.variant)}</span>,
    },
    {
        title: 'Requests',
        key: 'demand',
        align: 'right',
        render: (_, variant) => humanFriendlyLargeNumber(variant.demand),
    },
    {
        title: 'Top agent',
        key: 'agent',
        render: (_, variant) => variant.topAgent ?? <span className="text-secondary">-</span>,
    },
    {
        title: 'First seen in range',
        key: 'first_seen',
        render: (_, variant) =>
            variant.firstSeen ? <TZLabel time={variant.firstSeen} /> : <span className="text-secondary">-</span>,
    },
]

export const AgentIssueDetail = ({ issue }: { issue: AgentIssue }): JSX.Element => {
    const { variants, variantsLoading, variantsError, resultPaginations } = useValues(agentAnalyticsLogic)
    const { loadVariants } = useActions(agentAnalyticsLogic)

    return (
        <div className="flex flex-col gap-4 py-2">
            <div className="flex flex-col gap-2">
                <span className="text-sm font-medium">Recommended fix</span>
                <ol className="ml-4 flex list-decimal flex-col gap-1 text-sm">
                    {issue.recommendedFix.map((step) => (
                        <li key={step}>{step}</li>
                    ))}
                </ol>
            </div>

            {issue.type === 'content_gap' ? (
                <div className="flex flex-col gap-2">
                    <span className="flex flex-wrap items-center gap-2 text-sm font-medium">
                        Requested URL variants
                        {issue.lastSeen ? (
                            <span className="text-xs font-normal text-secondary">
                                last seen <TZLabel time={issue.lastSeen} />
                            </span>
                        ) : null}
                    </span>
                    <AgentQueryError
                        error={variantsError}
                        subject="URL variants"
                        onRetry={loadVariants}
                        loading={variantsLoading}
                    >
                        <LemonTable
                            columns={variantColumns}
                            dataSource={variants}
                            loading={variantsLoading}
                            size="small"
                            nouns={['variant', 'variants']}
                            pagination={resultPaginations[WebAgentAnalyticsQueryType.IssueVariants]}
                            emptyState="No URL variants were found in this range."
                        />
                    </AgentQueryError>
                </div>
            ) : null}
        </div>
    )
}
