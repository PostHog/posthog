import { useActions, useValues } from 'kea'

import { IconArrowLeft, IconCheckCircle } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCard, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyLargeNumber } from 'lib/utils/numbers'
import { tryDecodeURIComponent } from 'lib/utils/url'

import { WebAgentAnalyticsQueryType } from '~/queries/schema/schema-general'

import { IssueVariant, agentAnalyticsLogic } from './agentAnalyticsLogic'
import { AgentAnalyticsSection } from './AgentAnalyticsSection'
import { AgentIssueTypeTag } from './AgentIssueTypeTag'
import { agentIssueDemandLabel } from './agentIssueUtils'
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

export const AgentIssueDetail = (): JSX.Element | null => {
    const { selectedIssue, variants, variantsLoading, variantsError, resultPaginations } =
        useValues(agentAnalyticsLogic)
    const { setSelectedIssueKey, loadVariants } = useActions(agentAnalyticsLogic)

    if (!selectedIssue) {
        return null
    }

    return (
        <div className="flex flex-col gap-5">
            <div className="flex flex-col gap-2">
                <LemonButton
                    icon={<IconArrowLeft />}
                    size="small"
                    type="tertiary"
                    onClick={() => setSelectedIssueKey(null)}
                    className="self-start"
                    data-attr="agent-analytics-back-to-issues"
                >
                    Back to issues
                </LemonButton>
                <div className="flex items-center gap-2 flex-wrap">
                    <AgentIssueTypeTag type={selectedIssue.type} />
                    <h2 className="text-xl font-semibold">{selectedIssue.title}</h2>
                </div>
                <p className="text-sm text-secondary max-w-2xl">{selectedIssue.subtitle}</p>
            </div>

            <div className="@container">
                <div className="grid grid-cols-1 gap-3 @md:grid-cols-2 @3xl:grid-cols-4">
                    <LemonCard hoverEffect={false} className="flex min-h-24 flex-col justify-between gap-2">
                        <span className="text-sm font-medium text-secondary">Requests</span>
                        <span className="text-2xl font-semibold tabular-nums">
                            {agentIssueDemandLabel(selectedIssue)}
                        </span>
                    </LemonCard>
                    <LemonCard hoverEffect={false} className="flex min-h-24 flex-col justify-between gap-2">
                        <span className="text-sm font-medium text-secondary">Top agent</span>
                        <span className="font-semibold">{selectedIssue.topAgent ?? 'No agent identified'}</span>
                    </LemonCard>
                    <LemonCard hoverEffect={false} className="flex min-h-24 flex-col justify-between gap-2">
                        <span className="text-sm font-medium text-secondary">First seen</span>
                        <span className="font-semibold">
                            {selectedIssue.firstSeen ? <TZLabel time={selectedIssue.firstSeen} /> : 'Not available'}
                        </span>
                    </LemonCard>
                    <LemonCard hoverEffect={false} className="flex min-h-24 flex-col justify-between gap-2">
                        <span className="text-sm font-medium text-secondary">Last seen</span>
                        <span className="font-semibold">
                            {selectedIssue.lastSeen ? <TZLabel time={selectedIssue.lastSeen} /> : 'Not available'}
                        </span>
                    </LemonCard>
                </div>
            </div>

            {selectedIssue.type === 'content_gap' ? (
                <AgentAnalyticsSection
                    title="Requested URL variants"
                    description={`${selectedIssue.variants} ${selectedIssue.variants === 1 ? 'variant' : 'variants'} grouped into this issue.`}
                >
                    <AgentQueryError
                        error={variantsError}
                        message="Could not load URL variants. Try again. If it keeps happening, contact support."
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
                </AgentAnalyticsSection>
            ) : null}

            <AgentAnalyticsSection title="Recommended fix">
                <LemonCard hoverEffect={false}>
                    <ol className="ml-4 flex list-decimal flex-col gap-2 text-sm">
                        {selectedIssue.recommendedFix.map((step) => (
                            <li key={step}>{step}</li>
                        ))}
                    </ol>
                </LemonCard>
            </AgentAnalyticsSection>

            <AgentAnalyticsSection title="How to verify">
                <LemonBanner type="info" icon={<IconCheckCircle />}>
                    After shipping a fix, compare the same date range with the previous period. A working fix should
                    reduce requests to missing paths and move demand to the valid page.
                </LemonBanner>
            </AgentAnalyticsSection>
        </div>
    )
}
