import { useActions, useValues } from 'kea'

import * as puzzlePng from '@posthog/brand/hoggies/png/puzzle'
import { IconBook, IconMCP, IconSearch } from '@posthog/icons'
import { LemonButton, LemonTable, Spinner } from '@posthog/lemon-ui'
import { InputGroup, InputGroupAddon, InputGroupInput, InputGroupText } from '@posthog/quill-primitives'

import { pngHoggie } from 'lib/brand/hoggies'
import { ACCENT_TEXT } from 'lib/components/ProductEmptyState/ProductEmptyState'
import { TZLabel } from 'lib/components/TZLabel'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'

import { MCPMissingCapabilitiesItem } from '~/queries/schema/schema-general'

import { McpDateFilter } from '../components/McpDateFilter'
import { HarnessLogo } from '../dashboard/harness'
import { isUnidentifiedClient, mcpMissingCapabilitiesLogic, parsePersonProperties } from './mcpMissingCapabilitiesLogic'

const MISSING_CAPABILITY_DOCS_URL = 'https://posthog.com/docs/mcp-analytics/missing-capability'

const HedgehogPuzzle = pngHoggie(puzzlePng)

function FilterBar(): JSX.Element {
    const { search, dateFilter, reportsLoading } = useValues(mcpMissingCapabilitiesLogic)
    const { setSearch, setDateFilter } = useActions(mcpMissingCapabilitiesLogic)

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
                    data-attr="mcp-missing-capabilities-search"
                />
            </InputGroup>
            <McpDateFilter
                dateFrom={dateFilter.dateFrom}
                dateTo={dateFilter.dateTo}
                onChange={(dateFrom, dateTo) => setDateFilter(dateFrom, dateTo)}
                dataAttr="mcp-missing-capabilities-date-filter"
            />
        </div>
    )
}

/**
 * Most projects have no reports, because `reportMissing` is off by default and almost nothing
 * tells people the feature exists — so this state pitches the surface and how to turn it on
 * rather than apologising for empty rows.
 *
 * It speaks the product's own empty-state language (hedgehog, accent-tinted eyebrow, headline
 * / lead / hint, docs button) at tab scale. The shared `ProductEmptyState` can't be dropped in
 * as-is: it is the scene-level *product not set up* screen, so it fills the viewport, pitches
 * the wizard, and carries a "Skip for now" that dismisses this product's whole onboarding gate
 * — none of which is true here, where MCP analytics is already installed and one SDK option is
 * all that's missing.
 */
function NeverConfiguredState(): JSX.Element {
    return (
        <div
            className="flex flex-col items-center gap-4 px-6 py-10 text-center"
            style={
                {
                    '--empty-state-accent': 'var(--color-product-mcp-analytics-light)',
                    '--empty-state-accent-dark': 'var(--color-product-mcp-analytics-dark)',
                } as React.CSSProperties
            }
            data-attr="mcp-missing-capabilities-empty"
        >
            <HedgehogPuzzle className="w-28 shrink-0" />
            <div className={`inline-flex items-center gap-1.5 text-sm font-semibold ${ACCENT_TEXT}`}>
                <IconMCP className="text-base" />
                Missing capabilities
            </div>
            <div className="flex max-w-lg flex-col gap-1">
                <h3 className="m-0 text-xl font-semibold">Let agents tell you which tool to build next</h3>
                <p className="m-0 text-sm text-secondary">
                    When an agent can&apos;t finish a job with the tools you expose, it can say so in its own words.
                    Every report lands here, newest first — the sharpest read you get on demand your server isn&apos;t
                    serving yet.
                </p>
            </div>
            <p className="m-0 max-w-lg text-xs text-tertiary">
                Reporting is opt-in: set <code>reportMissing: true</code> when you initialise the PostHog MCP SDK, and
                agents get a <code>get_more_tools</code> tool they can call when they&apos;re stuck.
            </p>
            <LemonButton type="secondary" icon={<IconBook />} to={MISSING_CAPABILITY_DOCS_URL} targetBlank>
                Read the docs
            </LemonButton>
        </div>
    )
}

function EmptyState(): JSX.Element {
    const { search } = useValues(mcpMissingCapabilitiesLogic)

    // A search miss is a different problem from a server that never reports: someone filtering
    // an existing feed doesn't need to be told to install an SDK option they already have on.
    if (search) {
        return (
            <div className="p-6 text-center text-sm text-secondary">
                No reports match “{search}”. Try a broader term or a wider date range.
            </div>
        )
    }
    return <NeverConfiguredState />
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

export function MCPAnalyticsMissingCapabilities(): JSX.Element {
    const { reports, reportsLoading, hasNext } = useValues(mcpMissingCapabilitiesLogic)
    const { loadMoreReports } = useActions(mcpMissingCapabilitiesLogic)

    return (
        <div className="flex flex-col gap-4" data-attr="mcp-analytics-missing-capabilities">
            <FilterBar />
            <LemonTable<MCPMissingCapabilitiesItem>
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
                        data-attr="mcp-missing-capabilities-load-more"
                    >
                        Load more
                    </LemonButton>
                </div>
            ) : null}
        </div>
    )
}
