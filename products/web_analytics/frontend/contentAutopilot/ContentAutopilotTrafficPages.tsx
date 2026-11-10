import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSelect, LemonSkeleton, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'
import { PagePerformanceCard } from 'scenes/web-analytics/PagePerformanceCard'
import { PagePerformanceCardHeader } from 'scenes/web-analytics/PagePerformanceCardHeader'
import { PagePerformanceEmptyState } from 'scenes/web-analytics/PagePerformanceEmptyState'

import type { AiTrafficPageFilter, AiTrafficPageStatus } from './aiTraffic'
import { contentAutopilotAiTrafficLogic } from './contentAutopilotAiTrafficLogic'

const STATUS_LABELS: Record<AiTrafficPageStatus, string> = {
    cited_and_visited: 'Cited and visited',
    cited_not_visited: 'Cited, no visits',
    visited_not_cited: 'Visited, not cited',
}

const STATUS_TAG_TYPES: Record<AiTrafficPageStatus, 'success' | 'warning' | 'muted'> = {
    cited_and_visited: 'success',
    cited_not_visited: 'warning',
    visited_not_cited: 'muted',
}

const PageComparisonBody = (): JSX.Element => {
    const { promptTrackingEnabled, pageSourcesError, pageSourcesLoading, filteredPageRows, pageRows, pageCounts } =
        useValues(contentAutopilotAiTrafficLogic)
    const { loadPageSources } = useActions(contentAutopilotAiTrafficLogic)

    if (!promptTrackingEnabled) {
        return (
            <PagePerformanceEmptyState title="Prompt tracking is not turned on">
                <p className="m-0">
                    The comparison needs the citation checks from prompt tracking. Ask PostHog support to turn it on.
                </p>
            </PagePerformanceEmptyState>
        )
    }
    if (pageSourcesError) {
        return (
            <LemonBanner
                type="error"
                action={{ children: 'Try again', onClick: loadPageSources, loading: pageSourcesLoading }}
            >
                Couldn't load the cited and visited pages. Try again, and if it keeps happening contact support.
            </LemonBanner>
        )
    }
    if (!pageRows || !pageCounts || !filteredPageRows) {
        return <LemonSkeleton className="h-48 w-full" />
    }
    if (pageRows.length === 0) {
        return (
            <PagePerformanceEmptyState title="No cited or visited pages in this range">
                <p className="m-0">
                    No check cited a page on your site, and no visitor from an AI assistant landed on one.
                </p>
            </PagePerformanceEmptyState>
        )
    }

    return (
        <LemonTable
            dataSource={filteredPageRows}
            loading={pageSourcesLoading}
            size="small"
            rowKey="path"
            pagination={{ pageSize: 20 }}
            emptyState="No pages match this filter."
            data-attr="content-autopilot-ai-traffic-pages-table"
            columns={[
                {
                    title: 'Page',
                    key: 'path',
                    render: (_, row) => (
                        <span className="whitespace-nowrap" title={row.path}>
                            {row.path}
                        </span>
                    ),
                },
                {
                    title: 'Status',
                    key: 'status',
                    render: (_, row) => (
                        <LemonTag type={STATUS_TAG_TYPES[row.status]} className="whitespace-nowrap">
                            {STATUS_LABELS[row.status]}
                        </LemonTag>
                    ),
                },
                {
                    title: 'Citing answers',
                    key: 'answers',
                    align: 'right',
                    sorter: (a, b) => a.answers - b.answers,
                    render: (_, row) => <span className="tabular-nums">{humanFriendlyNumber(row.answers)}</span>,
                },
                {
                    title: 'AI sessions',
                    key: 'sessions',
                    align: 'right',
                    sorter: (a, b) => a.sessions - b.sessions,
                    render: (_, row) => <span className="tabular-nums">{humanFriendlyNumber(row.sessions)}</span>,
                },
            ]}
        />
    )
}

/** Pages the engines cite in prompt checks next to the pages visitors from AI assistants land on. */
export const ContentAutopilotTrafficPages = (): JSX.Element => {
    const { pageFilter, pageCounts } = useValues(contentAutopilotAiTrafficLogic)
    const { setPageFilter } = useActions(contentAutopilotAiTrafficLogic)

    const option = (value: AiTrafficPageStatus): { value: AiTrafficPageFilter; label: string } => ({
        value,
        label: pageCounts ? `${STATUS_LABELS[value]} (${pageCounts[value]})` : STATUS_LABELS[value],
    })

    return (
        <PagePerformanceCard className="min-w-0">
            <PagePerformanceCardHeader
                title="Cited pages and landing pages"
                actions={
                    pageCounts ? (
                        <LemonSelect<AiTrafficPageFilter>
                            size="small"
                            aria-label="Show pages"
                            value={pageFilter}
                            onChange={setPageFilter}
                            options={[
                                { value: 'all', label: 'All pages' },
                                option('cited_and_visited'),
                                option('cited_not_visited'),
                                option('visited_not_cited'),
                            ]}
                            data-attr="content-autopilot-ai-traffic-pages-filter"
                        />
                    ) : null
                }
            />
            <p className="m-0 px-3 py-2 text-xs text-muted">
                Pages on your site that answers cited in prompt checks, matched by path to the pages where sessions from
                AI assistants started. A page visited but never cited may be cited for prompts you don't track.
            </p>
            <div className="overflow-x-auto px-3 pb-3" data-attr="content-autopilot-ai-traffic-pages">
                <PageComparisonBody />
            </div>
        </PagePerformanceCard>
    )
}
