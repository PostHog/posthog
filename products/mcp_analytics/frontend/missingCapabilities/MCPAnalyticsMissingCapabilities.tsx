import { useActions, useValues } from 'kea'

import * as puzzlePng from '@posthog/brand/hoggies/png/puzzle'
import { IconBook, IconMCP, IconSearch } from '@posthog/icons'
import { LemonButton, LemonTable, Spinner } from '@posthog/lemon-ui'
import { InputGroup, InputGroupAddon, InputGroupInput, InputGroupText } from '@posthog/quill-primitives'

import { pngHoggie } from 'lib/brand/hoggies'
import { CommandBlock } from 'lib/components/CommandBlock/CommandBlock'
import { ACCENT_TEXT, ProductEmptyStatePreviewPanel } from 'lib/components/ProductEmptyState/ProductEmptyState'
import { TZLabel } from 'lib/components/TZLabel'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'

import { MCPMissingCapabilitiesItem } from '~/queries/schema/schema-general'

import { McpDateFilter } from '../components/McpDateFilter'
import { HarnessLogo } from '../dashboard/harness'
import { useMCPAnalyticsWizardCommand } from '../onboarding/MCPAnalyticsInstall'
import { isUnidentifiedClient, mcpMissingCapabilitiesLogic, parsePersonProperties } from './mcpMissingCapabilitiesLogic'
import { MissingCapabilitiesPreview } from './MissingCapabilitiesPreview'

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
 * tells people the feature exists — so this state pitches the surface and how to turn it on,
 * leading with the wizard command the way the onboarding hero does, rather than apologising for
 * empty rows behind a docs link.
 *
 * It reuses the shared empty state's building blocks (accent tokens, `ACCENT_TEXT`, the rainbow
 * `CommandBlock`, `ProductEmptyStatePreviewPanel`) but not `ProductEmptyState` itself: that is
 * the scene-level *product not set up* screen, so it fills the viewport and carries a "Skip for
 * now" that dismisses this product's whole onboarding gate — neither of which is true here,
 * where MCP analytics is already installed and one SDK option is all that's missing.
 */
function NeverConfiguredState(): JSX.Element {
    const { command, isCloudOrDev } = useMCPAnalyticsWizardCommand()

    return (
        <div
            className="grid w-full grid-cols-1 items-center gap-8 py-4 md:grid-cols-[minmax(0,1fr)_40%]"
            style={
                {
                    '--empty-state-accent': 'var(--color-product-mcp-analytics-light)',
                    '--empty-state-accent-dark': 'var(--color-product-mcp-analytics-dark)',
                } as React.CSSProperties
            }
            data-attr="mcp-missing-capabilities-empty"
        >
            <div className="flex min-w-0 flex-col gap-4">
                <div className="flex items-start gap-4">
                    <HedgehogPuzzle className="hidden w-24 shrink-0 sm:block" />
                    <div className="flex flex-col gap-1">
                        <div className={`inline-flex items-center gap-1.5 text-sm font-semibold ${ACCENT_TEXT}`}>
                            <IconMCP className="text-base" />
                            Missing capabilities
                        </div>
                        <h3 className="m-0 text-xl font-semibold">Let agents tell you which tool to build next</h3>
                        <p className="m-0 text-sm text-secondary">
                            When an agent can&apos;t finish a job with the tools you expose, it can say so in its own
                            words. Every report lands here, newest first — the sharpest read you get on demand your
                            server isn&apos;t serving yet.
                        </p>
                    </div>
                </div>

                {/* Wizard commands only work against cloud; self-hosted gets the manual path promoted instead. */}
                {isCloudOrDev ? (
                    <div className="flex flex-col gap-2">
                        <p className="m-0 text-xs text-tertiary">
                            Re-run the wizard from your MCP server&apos;s project root — it turns reporting on for you:
                        </p>
                        <CommandBlock
                            command={command}
                            copyLabel="MCP analytics wizard command"
                            ariaLabel="Copy MCP analytics wizard command"
                            size="md"
                            decoration="rainbow"
                            className="bg-bg-light border border-border hover:border-primary"
                        />
                    </div>
                ) : null}

                <p className="m-0 text-xs text-tertiary">
                    {isCloudOrDev ? 'Prefer to wire it up by hand?' : 'Reporting is opt-in.'} Set{' '}
                    <code>reportMissing: true</code> when you initialise the PostHog MCP SDK, and agents get a{' '}
                    <code>get_more_tools</code> tool they can call when they&apos;re stuck.
                </p>

                <LemonButton
                    type={isCloudOrDev ? 'tertiary' : 'primary'}
                    size={isCloudOrDev ? 'xsmall' : 'small'}
                    icon={<IconBook />}
                    to={MISSING_CAPABILITY_DOCS_URL}
                    targetBlank
                    className="self-start"
                >
                    {isCloudOrDev ? 'Read the docs' : 'Set up missing-capability reports'}
                </LemonButton>
            </div>

            <ProductEmptyStatePreviewPanel label="Reports, once agents start filing them">
                <MissingCapabilitiesPreview />
            </ProductEmptyStatePreviewPanel>
        </div>
    )
}

// A search miss is a different problem from a server that never reports: someone filtering an
// existing feed doesn't need to be told to install an SDK option they already have on.
function NoSearchResultsState({ search }: { search: string }): JSX.Element {
    return (
        <div className="p-6 text-center text-sm text-secondary">
            No reports match “{search}”. Try a broader term or a wider date range.
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

export function MCPAnalyticsMissingCapabilities(): JSX.Element {
    const { reports, reportsLoading, hasNext, search } = useValues(mcpMissingCapabilitiesLogic)
    const { loadMoreReports } = useActions(mcpMissingCapabilitiesLogic)

    // A server that has never reported gets the pitch instead of the table: column headers over
    // an onboarding surface read as a broken table. Filtering an existing feed keeps the table,
    // so the filter bar stays put and the miss is explained in place.
    const neverConfigured = !reportsLoading && reports.length === 0 && !search

    return (
        <div className="flex flex-col gap-4" data-attr="mcp-analytics-missing-capabilities">
            <FilterBar />
            {neverConfigured ? (
                <NeverConfiguredState />
            ) : (
                <LemonTable<MCPMissingCapabilitiesItem>
                    dataSource={reports}
                    loading={reportsLoading && reports.length === 0}
                    rowKey={(row, index) => `${row.timestamp}-${index}`}
                    emptyState={<NoSearchResultsState search={search} />}
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
            )}
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
