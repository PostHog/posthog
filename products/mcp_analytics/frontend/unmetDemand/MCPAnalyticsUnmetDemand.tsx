import { useActions, useValues } from 'kea'

import { IconSearch } from '@posthog/icons'
import { LemonButton, LemonTable, Link, Spinner } from '@posthog/lemon-ui'
import { InputGroup, InputGroupAddon, InputGroupInput, InputGroupText } from '@posthog/quill-primitives'

import { TZLabel } from 'lib/components/TZLabel'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'

import { MCPUnmetDemandItem } from '~/queries/schema/schema-general'

import { McpDateFilter } from '../components/McpDateFilter'
import { HarnessLogo } from '../dashboard/harness'
import { isUnidentifiedClient, mcpUnmetDemandLogic, parsePersonProperties } from './mcpUnmetDemandLogic'

const MISSING_CAPABILITY_DOCS_URL = 'https://posthog.com/docs/mcp-analytics/missing-capability'

function FilterBar(): JSX.Element {
    const { search, dateFilter, reportsLoading } = useValues(mcpUnmetDemandLogic)
    const { setSearch, setDateFilter } = useActions(mcpUnmetDemandLogic)

    return (
        <div className="flex flex-wrap items-center gap-2" data-quill>
            <InputGroup className="min-w-[240px] flex-1">
                <InputGroupAddon align="inline-start">
                    <InputGroupText>{reportsLoading && search ? <Spinner /> : <IconSearch />}</InputGroupText>
                </InputGroupAddon>
                <InputGroupInput
                    type="search"
                    placeholder="Search what agents asked for"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    data-attr="mcp-unmet-demand-search"
                />
            </InputGroup>
            <McpDateFilter
                dateFrom={dateFilter.dateFrom}
                dateTo={dateFilter.dateTo}
                onChange={(dateFrom, dateTo) => setDateFilter(dateFrom, dateTo)}
                dataAttr="mcp-unmet-demand-date-filter"
            />
        </div>
    )
}

// Most projects have none of these, because reportMissing is off by default and almost
// nothing tells people the feature exists — so the empty state's job is to explain the
// surface and how to turn it on, not to apologise for having no rows.
function EmptyState(): JSX.Element {
    const { search } = useValues(mcpUnmetDemandLogic)

    if (search) {
        return (
            <div className="p-6 text-center text-sm text-secondary">
                No reports match “{search}”. Try a broader term or a wider date range.
            </div>
        )
    }
    return (
        <div className="flex flex-col items-center gap-3 p-8 text-center" data-attr="mcp-unmet-demand-empty">
            <h3 className="m-0 text-lg font-semibold">No unmet-demand reports yet</h3>
            <p className="m-0 max-w-md text-sm text-muted">
                When an agent can&apos;t do what a user asked with the tools you expose, it can tell you so in its own
                words — and those reports land here, newest first. It&apos;s the clearest signal you get about which
                tool to build next.
            </p>
            <p className="m-0 max-w-md text-sm text-muted">
                Reporting is opt-in: set <code>reportMissing: true</code> when you initialise the PostHog MCP SDK, and
                agents get a <code>get_more_tools</code> tool they can call when they&apos;re stuck.
            </p>
            <Link to={MISSING_CAPABILITY_DOCS_URL} target="_blank">
                How to enable unmet-demand reporting
            </Link>
        </div>
    )
}

// The client is often genuinely unknown: the SDK only stamps $mcp_client_name on
// $mcp_initialize, so most reports arrive without one. Say so plainly instead of leaving
// a blank cell — and without implying the customer mis-instrumented anything.
function ClientCell({ harness }: { harness: string }): JSX.Element {
    if (isUnidentifiedClient(harness)) {
        return (
            <span className="text-muted" title="This report didn't include which MCP client filed it.">
                Unknown client
            </span>
        )
    }
    return (
        <span className="flex items-center gap-1.5">
            <HarnessLogo category={harness} className="h-3.5 w-3.5" />
            <span className="truncate">{harness}</span>
        </span>
    )
}

export function MCPAnalyticsUnmetDemand(): JSX.Element {
    const { reports, reportsLoading, hasNext } = useValues(mcpUnmetDemandLogic)
    const { loadMoreReports } = useActions(mcpUnmetDemandLogic)

    return (
        <div className="flex flex-col gap-4" data-attr="mcp-analytics-unmet-demand">
            <FilterBar />
            <LemonTable<MCPUnmetDemandItem>
                dataSource={reports}
                loading={reportsLoading && reports.length === 0}
                rowKey={(row, index) => `${row.timestamp}-${index}`}
                emptyState={<EmptyState />}
                columns={[
                    {
                        title: 'When',
                        key: 'timestamp',
                        width: 130,
                        render: (_, row) => <TZLabel time={row.timestamp} />,
                    },
                    {
                        title: 'The ask',
                        key: 'intent',
                        render: (_, row) =>
                            row.intent ? (
                                <span className="text-base">{row.intent}</span>
                            ) : (
                                // The agent called get_more_tools without saying what it wanted.
                                <span className="text-muted text-base">No description given</span>
                            ),
                    },
                    {
                        title: 'Client',
                        key: 'harness',
                        width: 170,
                        render: (_, row) => <ClientCell harness={row.harness} />,
                    },
                    {
                        title: 'Person',
                        key: 'person',
                        width: 200,
                        render: (_, row) => (
                            <PersonDisplay
                                person={{
                                    distinct_id: row.distinct_id,
                                    properties: parsePersonProperties(row.person_properties),
                                }}
                                withIcon
                                noPopover={false}
                            />
                        ),
                    },
                ]}
            />
            {hasNext ? (
                <div className="flex justify-center">
                    <LemonButton
                        type="secondary"
                        size="small"
                        loading={reportsLoading}
                        onClick={() => loadMoreReports()}
                        data-attr="mcp-unmet-demand-load-more"
                    >
                        Load more
                    </LemonButton>
                </div>
            ) : null}
        </div>
    )
}
