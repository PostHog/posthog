import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { IconChat, IconRefresh } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSwitch, LemonTable, LemonTag, Link } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { TZLabel } from 'lib/components/TZLabel'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { dateFilterToText } from 'lib/utils'
import { urls } from 'scenes/urls'

import { llmAnalyticsSharedLogic } from './llmAnalyticsSharedLogic'
import { ConversationListItem, llmAnalyticsConversationsViewLogic } from './tabs/llmAnalyticsConversationsViewLogic'
import { formatLLMCost, sanitizeTraceUrlSearchParams } from './utils'

const TITLE_PREVIEW_MAX_LENGTH = 140
const PROPERTY_FILTER_TAXONOMIC_TYPES: TaxonomicFilterGroupType[] = [
    TaxonomicFilterGroupType.EventProperties,
    TaxonomicFilterGroupType.PersonProperties,
    TaxonomicFilterGroupType.Cohorts,
    TaxonomicFilterGroupType.HogQLExpression,
]

function truncateTitle(value: string | null | undefined): string {
    if (!value) {
        return '(no user message)'
    }
    const cleaned = value.replace(/\s+/g, ' ').trim()
    if (!cleaned) {
        return '(no user message)'
    }
    if (cleaned.length <= TITLE_PREVIEW_MAX_LENGTH) {
        return cleaned
    }
    return cleaned.slice(0, TITLE_PREVIEW_MAX_LENGTH) + '…'
}

export function LLMAnalyticsConversationsScene(): JSX.Element {
    const { searchParams } = useValues(router)
    const traceSearchParams = sanitizeTraceUrlSearchParams(searchParams, { removeSearch: true })

    const { dateFilter, shouldFilterTestAccounts, propertyFilters } = useValues(llmAnalyticsSharedLogic)
    const { setDates, setShouldFilterTestAccounts, setPropertyFilters } = useActions(llmAnalyticsSharedLogic)

    const { setIncludeOrphanTraces, loadConversations } = useActions(llmAnalyticsConversationsViewLogic)
    const { conversations, conversationsLoading, conversationsError, includeOrphanTraces } = useValues(
        llmAnalyticsConversationsViewLogic
    )

    const periodLabel = dateFilterToText(dateFilter.dateFrom, dateFilter.dateTo, 'all time')?.toLowerCase()

    return (
        <div className="flex flex-col gap-3">
            <div className="flex flex-wrap gap-x-4 gap-y-2 items-center py-4 -mt-4 mb-2 border-b">
                <DateFilter dateFrom={dateFilter.dateFrom} dateTo={dateFilter.dateTo} onChange={setDates} />
                <PropertyFilters
                    propertyFilters={propertyFilters}
                    taxonomicGroupTypes={PROPERTY_FILTER_TAXONOMIC_TYPES}
                    onChange={setPropertyFilters}
                    pageKey="llm-analytics-conversations"
                />
                <div className="flex-1" />
                <TestAccountFilterSwitch checked={shouldFilterTestAccounts} onChange={setShouldFilterTestAccounts} />
                <LemonSwitch
                    bordered
                    label="Include traces without session"
                    tooltip="Show single-trace conversations that have no $ai_session_id. Hidden by default to focus on multi-turn chats."
                    checked={includeOrphanTraces}
                    onChange={setIncludeOrphanTraces}
                />
                <LemonButton
                    onClick={() => loadConversations()}
                    type="secondary"
                    size="small"
                    icon={conversationsLoading ? <Spinner textColored /> : <IconRefresh />}
                    disabledReason={conversationsLoading ? 'Loading...' : undefined}
                >
                    {conversationsLoading ? 'Refreshing…' : 'Reload'}
                </LemonButton>
            </div>
            {conversationsError && (
                <LemonBanner type="error">Failed to load conversations: {conversationsError}</LemonBanner>
            )}
            <LemonTable<ConversationListItem>
                dataSource={conversations}
                loading={conversationsLoading}
                useURLForSorting={false}
                defaultSorting={{ columnKey: 'last_seen', order: -1 }}
                rowKey={(row) => `${row.kind}:${row.id}`}
                emptyState={
                    <div className="flex flex-col items-center gap-2 py-8 text-center">
                        <IconChat className="text-4xl text-muted" />
                        <div className="font-semibold">No conversations in {periodLabel}</div>
                        <div className="text-muted text-sm max-w-md">
                            Try widening the date range, removing property filters, or toggling{' '}
                            <strong>Include traces without session</strong> to also show one-off traces.
                        </div>
                    </div>
                }
                columns={[
                    {
                        title: 'Conversation',
                        key: 'title',
                        sorter: (a, b) => (a.title ?? '').localeCompare(b.title ?? ''),
                        render: (_, row) => {
                            const detailUrl = combineUrl(
                                urls.llmAnalyticsConversation(row.kind, row.id),
                                traceSearchParams
                            ).url
                            return (
                                <Link to={detailUrl} className="font-semibold">
                                    {truncateTitle(row.title)}
                                </Link>
                            )
                        },
                    },
                    {
                        title: 'Type',
                        key: 'kind',
                        sorter: (a, b) => a.kind.localeCompare(b.kind),
                        width: 130,
                        render: (_, row) =>
                            row.kind === 'trace' ? (
                                <LemonTag type="warning" size="small">
                                    No session
                                </LemonTag>
                            ) : (
                                <LemonTag type="primary" size="small">
                                    Session
                                </LemonTag>
                            ),
                    },
                    {
                        title: 'Turns',
                        key: 'turns',
                        sorter: (a, b) => a.turns - b.turns,
                        width: 70,
                        align: 'right',
                        render: (_, row) => <span className="tabular-nums">{row.turns}</span>,
                    },
                    {
                        title: 'User',
                        key: 'distinct_id',
                        sorter: (a, b) => (a.distinct_id ?? '').localeCompare(b.distinct_id ?? ''),
                        width: 200,
                        render: (_, row) =>
                            row.distinct_id ? (
                                <Tooltip title={row.distinct_id}>
                                    <span className="font-mono text-xs truncate inline-block max-w-[180px]">
                                        {row.distinct_id}
                                    </span>
                                </Tooltip>
                            ) : (
                                <span className="text-muted">–</span>
                            ),
                    },
                    {
                        title: 'Cost',
                        key: 'total_cost',
                        // Null totals (free / fully cached) sort below any real cost regardless of direction.
                        sorter: (a, b) => (a.total_cost ?? -Infinity) - (b.total_cost ?? -Infinity),
                        width: 90,
                        align: 'right',
                        render: (_, row) =>
                            row.total_cost ? (
                                <span className="tabular-nums">{formatLLMCost(row.total_cost)}</span>
                            ) : (
                                <span className="text-muted">–</span>
                            ),
                    },
                    {
                        title: 'Last activity',
                        key: 'last_seen',
                        sorter: (a, b) => a.last_seen.localeCompare(b.last_seen),
                        width: 160,
                        render: (_, row) => <TZLabel time={row.last_seen} />,
                    },
                ]}
            />
        </div>
    )
}
